# I-Sentinel — Fase 1: Vision Inti Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Person detection + tracking end-to-end pada kamera nyata: frame substream → YOLO26s (TensorRT FP16, nms=False) → ByteTrack → event MQTT → DB → dashboard/live view. Bukti Fase 1: gerakan orang di depan kamera 192.168.0.64 → event `person_detect` masuk DB < 2 s; live view WebRTC jalan di browser; heartbeat node di dashboard.

**Architecture:** vision-node = paket Python terpisah (`vision/`, tanpa dependensi FastAPI/SQLAlchemy) — pipeline stage tetap (source → detector → tracker → emit), komunikasi ke backend via MQTT (events, heartbeat, LWT) + HTTP blobs. Backend menambah consumer MQTT + tabel `event` + API events + WS. go2rtc menjadi pemilik tunggal koneksi RTSP; backend menulis stream config; frontend live view via go2rtc WebRTC.

**Tech Stack:** Ultralytics (YOLO26s `nms=False`), TensorRT FP16 (export di server GPU), ByteTrack (supervision atau implementation ringan), OpenCV/PyAV decode, paho-mqtt, go2rtc 1.9+, FastAPI existing.

**Spec:** `docs/plans/2026-09-08-isentinel-design.md` (§2.7 detektor) · Master: `docs/plans/00-master.md` · Brief: `docs/plans/02-fase-1-vision-inti.md`

## Global Constraints

- Lihat master plan §Global Constraints — semua berlaku.
- `vision/` TIDAK boleh import FastAPI/SQLAlchemy; kontrak hanya MQTT + HTTP (internal API key).
- Semua logic testable CPU-only (detector/tracker/mock frame sintetis); test GPU pakai marker `@pytest.mark.gpu`.
- Event JSON schema persis master plan §Kontrak (field: event_id, type, node_id, camera_id, zone_id, severity, ts_event, payload, dedup_key).
- MQTT topics: `isentinel/events`, `isentinel/nodes/{node_id}/heartbeat`, `isentinel/nodes/{node_id}/lwt` (retained), `isentinel/config/{node_id}` (retained — dipakai minimal di Fase 1, penuh di Fase 2).
- Kamera nyata untuk pengujian: 192.168.0.64 (sudah terdaftar, sub 640×480 @25fps). Kredensial via env server, TIDAK di repo.
- Detektor config-driven: `detector.model` + `detector.nms` di config vision-node — bukan hardcode.

---

### Task 1: Event model + migration + events API (backend)

**Files:**
- Create: `backend/app/models/event.py`, `backend/alembic/versions/0002_events.py`
- Create: `backend/app/api/events.py`, `backend/app/schemas/event.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`
- Test: `backend/tests/test_events_api.py`

**Interfaces:**
- Produces:
  - `Event(id int PK, event_id UUID unique, type str, node_id FK null, camera_id FK null, zone_id null, severity, ts_event tz-aware, payload JSON, clip_path null, snapshot_path null, dedup_key unique null, created_at)` — camera/zone FK nullable (zone datang Fase 2).
  - `POST /internal/nodes/{node_id}/events` (header `Authorization: Bearer <NODE_API_KEY>`) → ingest idempotent: INSERT ... ON CONFLICT(event_id) DO NOTHING → `{status: "created"|"duplicate", id}`. Route ini dipakai vision-node sebagai fallback selain MQTT (dan jadi jalur store-and-forward replay).
  - `GET /api/v1/events?camera_id&type&since&limit` (auth) → list EventOut desc ts_event.
  - `GET /api/v1/events/stats/today` (auth) → `{total, by_type: {…}}` untuk dashboard tile.
  - WS: `/api/v1/ws/events` (auth via query token) — broadcast event baru (pola hub sederhana `app/ws/hub.py`).

- [ ] **Step 1: Failing test** — ingest endpoint (created → duplicate dengan event_id sama), GET list filter, stats today; schema validation (event_id wajib UUID).
- [ ] **Step 2: Run — verify fail** (`pytest tests/test_events_api.py -v`)
- [ ] **Step 3: Implement** model + migration `0002_events` (hand-write, autogenerate hanya referensi) + API + hub.
- [ ] **Step 4: Run — verify pass** + full suite green.
- [ ] **Step 5: Commit** — `feat: event model, internal ingest (idempotent), events API + ws hub`

---

### Task 2: MQTT consumer (backend)

**Files:**
- Create: `backend/app/services/events_consumer.py`
- Modify: `backend/app/main.py` (lifespan: start/stop consumer), `backend/app/core/config.py` (tambah `mqtt_username`, `mqtt_password` optional)
- Test: `backend/tests/test_events_consumer.py` (mock paho client — parse + ingest path)

**Interfaces:**
- Consumes: ingest service dari Task 1 (fungsi `ingest_event(db, payload: dict) -> "created"|"duplicate"` dipisah dari router agar reusable).
- Produces: consumer thread daemon: subscribe `isentinel/events` (QoS1) → parse JSON → validate schema → ingest → publish WS. Reconnect otomatis (paho loop_forever). Tidak crash bila broker down (log + retry).

- [ ] **Step 1: Failing test** — handler menerima payload JSON valid → ingest terpanggil; payload rusak → log error, tidak raise; duplikat → ignored.
- [ ] **Step 2: Run — verify fail**
- [ ] **Step 3: Implement** (paho-mqtt di backend deps; connect ke settings.mqtt_url; LWT node offline handler: subscribe `isentinel/nodes/+/lwt` → set node.status offline + event system).
- [ ] **Step 4: Run — verify pass** + suite green.
- [ ] **Step 5: Commit** — `feat: mqtt events consumer (events + node lwt)`

---

### Task 3: go2rtc integration (backend + deploy)

**Files:**
- Create: `backend/app/services/go2rtc.py` (client API go2rtc), `backend/app/api/live.py`
- Modify: `backend/app/api/cameras.py` (on create/update/delete → sync stream ke go2rtc), `deploy/go2rtc/go2rtc.yaml` (tetap; stream dinamis via API)
- Test: `backend/tests/test_go2rtc.py` (mock httpx — add/remove stream, error tolerant)

**Interfaces:**
- Produces:
  - `go2rtc.add_stream(name, src)`, `go2rtc.remove_stream(name)`, `go2rtc.stream_info(name)` — httpx ke `settings.go2rtc_url`, timeout 5s, SEMUA error di-catch → log warning (go2rtc down tidak boleh menghentikan CRUD kamera).
  - Stream naming: `cam_{camera_id}` (sub) & `cam_{camera_id}_main`.
  - Full URL dibangun runtime: `rtsp://{CAM_USERNAME}:{CAM_PASSWORD}@{host}{rtsp_path}` (zero-secret tetap).
  - `GET /api/v1/cameras/{id}/live` (auth) → `{webrtc: "http://host:1984/api/ws?src=cam_{id}", mse: ..., snapshot: ...}` untuk frontend.
- Catatan: go2rtc service belum jalan sebagai systemd di Fase 1 Task ini — dibawa di Task 8 (install + start). Semua panggilan tolerant-down.

- [ ] **Step 1: Failing test** — add_stream memanggil PUT `/api/streams?src=...`; remove DELETE; error → tidak raise.
- [ ] **Step 2: Run — verify fail**
- [ ] **Step 3: Implement** + hook di CRUD kamera.
- [ ] **Step 4: Run — verify pass** + suite green.
- [ ] **Step 5: Commit** — `feat: go2rtc stream sync + live url endpoint`

---

### Task 4: vision-node — source + detector + tracker (CPU-testable)

**Files:**
- Create: `vision/vision/__init__.py`, `vision/vision/pipeline/__init__.py`, `vision/vision/pipeline/source.py`, `vision/vision/pipeline/detector.py`, `vision/vision/pipeline/tracker.py`
- Modify: `vision/pyproject.toml` (deps: opencv-python-headless, pyav atau opencv VideoCapture; ultralytics di extras `gpu`)
- Test: `vision/tests/test_source.py`, `vision/tests/test_detector.py`, `vision/tests/test_tracker.py`

**Interfaces:**
- Produces:
  - `source.FrameSource(url, target_fps)` — iterator `(frame_ndarray, ts)`; decode via OpenCV `VideoCapture` (fallback PyAV); frame-skip sampling ke target_fps; reconnect dengan backoff saat read gagal.
  - `detector.PersonDetector` — `detect(frame) -> list[Detection(bbox xyxy norm 0-1, conf, cls)]`; backend: Ultralytics YOLO (`model` path dari config, class filter person, `nms=False` default per spec §2.7); **DI-MOCK di test CPU** via `detector.Detection` + `MockDetector` yang membaca bbox dari frame metadata test. Weight loading hanya di mode gpu.
  - `tracker.ByteTracker` — `update(detections, ts) -> list[Track(id, bbox, centroid, age, velocity)]`; state: smoothing centroid, velocity EMA; track hilang → `lost` setelah N frame tanpa match. Implementasi ByteTrack ringan sendiri (algoritma publik, ~80 baris) ATAU supervision library — putuskan saat implementasi, test tetap sama.
- Ruling prinsip: model YOLO TIDAK di-download saat install (extras gpu opt-in); CI/dev tidak menyentuh GPU.

- [ ] **Step 1: Failing tests** — source: feed sintetis (list frame) → yield sesuai target_fps; detector: MockDetector bbox dari frame; tracker: 2 frame dengan bbox bergeser → track id sama, velocity > 0; bbox hilang 15 frame → track lost.
- [ ] **Step 2: Run — verify fail** (`cd vision && python -m pytest tests/ -v`)
- [ ] **Step 3: Implement** minimal.
- [ ] **Step 4: Run — verify pass**.
- [ ] **Step 5: Commit** — `feat: vision pipeline stages (source, detector iface, byte tracker)`

---

### Task 5: vision-node — transport MQTT + node runner

**Files:**
- Create: `vision/vision/transport/__init__.py`, `vision/vision/transport/mqtt.py`, `vision/vision/transport/queue.py`, `vision/vision/node.py`, `vision/vision/config.py`
- Test: `vision/tests/test_transport.py`, `vision/tests/test_node.py`

**Interfaces:**
- Produces:
  - `config.NodeConfig` (pydantic-settings): node_id, mqtt_url, mqtt_username/password, api_url, api_key (NODE_API_KEY), detector {model, nms, conf, imgsz}, cameras [{camera_id, source_url, ai_fps}].
  - `transport.MqttTransport` — publish event (QoS1, JSON), heartbeat 10 s (cpu/gpu_mem/cameras), LWT `{"status":"offline"}` retained via will_set; `queue.DiskQueue(dir)` — antre event saat publish gagal, flush saat reconnect (max disk 100 MB, FIFO drop oldest).
  - `node.VisionNode(config)` — per kamera 1 thread: source → detector → tracker → debug analyzer `person_detect` (event setiap track baru + heartbeat movement; throttle 1 event/track/10 s via dedup_key `cam:type:track:ts_bucket`) → transport.publish. Signal handling → graceful stop. Event ts_event = timestamp frame (bukan waktu publish).
- dedup_key bucket: `f"{camera_id}:{type}:{track_id}:{int(ts // 10)}"`.

- [ ] **Step 1: Failing tests** — transport: publish gagal → masuk DiskQueue; reconnect → flush urut; node: 3 frame sintetis dengan MockDetector → event terbit dengan schema persis master plan (assert field per field).
- [ ] **Step 2: Run — verify fail**
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run — verify pass** (vision suite).
- [ ] **Step 5: Commit** — `feat: vision node runner (mqtt transport, disk queue, graceful)`

---

### Task 6: Export engine YOLO26s + smoke GPU (server, marker gpu)

**Files:**
- Create: `vision/scripts/export_engine.py` (arg: --model yolo26s.pt --imgsz 640 --nms false → TensorRT engine via ultralytics export), `vision/tests/test_detector_gpu.py` (`@pytest.mark.gpu`)
- Catatan: file engine TIDAK di-commit (gitignore `*.engine`).

- [ ] **Step 1: Tulis script export + gpu test** (gpu test: load engine, detect frame sintetis dengan gambar person, assert ≥1 deteksi conf > 0.5; latency print).
- [ ] **Step 2: Jalankan di gspe-ai3 via SSH** (venv server + `pip install ultralytics`, `python vision/scripts/export_engine.py`, `pytest -m gpu`): catat output (engine size, latency ms @640, deteksi ok) ke plan ini.
- [ ] **Step 3: Commit** script (bukan engine) — `feat: yolo26s tensorrt export script + gpu smoke test`

---

### Task 7: Node registry + API key (backend) + deploy systemd vision

**Files:**
- Modify: `backend/app/api/nodes.py` (heartbeat endpoint internal: `POST /internal/nodes/{id}/heartbeat` api-key → update last_seen/status online + upsert node by name), `backend/app/core/config.py` (NODE_API_KEY sudah ada)
- Create: `deploy/systemd/vision-node.service` (ExecStart python -m vision.node --config /etc/isentinel/vision.yaml), `deploy/vision.example.yaml`
- Test: `backend/tests/test_nodes_internal.py`

**Interfaces:**
- Produces: internal heartbeat ingest (auth NODE_API_KEY, sama pattern Task 1); node status di DB = sumber dashboard.

- [ ] **Step 1: Failing test** — heartbeat dengan api key benar → node online + last_seen update; salah key → 401.
- [ ] **Step 2: Run — verify fail** → **Step 3: Implement** → **Step 4: pass**
- [ ] **Step 5: Commit** — `feat: internal heartbeat ingest + vision systemd unit`

---

### Task 8: Frontend — dashboard tile + live view + events live list

**Files:**
- Create: `frontend/src/features/dashboard/DashboardPage.tsx`, `frontend/src/features/live/LiveViewPage.tsx`, `frontend/src/features/events/EventsPage.tsx` (list-only di fase ini), `frontend/src/api/events.ts`, `frontend/src/api/useWs.ts` (hook WebSocket dengan reconnect)
- Modify: `frontend/src/main.tsx` (route nyata untuk dashboard/live/events), i18n keys
- Live view: integrasi go2rtc WebRTC client (fetch script dari go2rtc `/api/ws` — embed lib via index.html atau vendored kecil); grid klik=fokus dblclick=fullscreen sesuai mockup 02; fallback MSE/WebRTC gagal → tampil snapshot API.

**Interfaces:**
- Consumes: `/api/v1/events*`, `/api/v1/ws/events`, `/api/v1/cameras/{id}/live`, `/api/v1/nodes`.
- Dashboard tile: kamera online/offline (dari cameras+nodes), event hari ini (stats), node status (heartbeat age).

- [ ] **Step 1: Failing tests** — DashboardPage render tile dari mocked stats; EventsPage render list + WS push menambah baris; LiveViewPage memilih src dari /live.
- [ ] **Step 2: Run — verify fail** → **Step 3: Implement** → **Step 4: vitest + build green**
- [ ] **Step 5: Commit** — `feat: dashboard tiles, live view (go2rtc webrtc), events live list`

---

### Task 9: Bring-up & verifikasi end-to-end di gspe-ai3

**Files:** tidak ada code baru — ini verifikasi (controller + user).

- [ ] Install go2rtc binary di server (github release amd64) + systemd unit `go2rtc.service` (port 1984)
- [ ] Install mosquitto client/passwd: user `isentinel` + NODE_API_KEY sync ke `.env` server & vision config
- [ ] Deploy vision config (`/etc/isentinel/vision.yaml`): node server, kamera 192.168.0.64 sub via go2rtc `rtsp://localhost:8554/cam_2`, ai_fps 5
- [ ] `systemctl enable --now go2rtc vision-node` → cek log: detector engine loaded (TensorRT), heartbeat masuk
- [ ] Uji end-to-end: orang lewat depan kamera → `SELECT type, ts_event FROM event ORDER BY id DESC LIMIT 5` < 2 s dari gerakan → dashboard tile bertambah → live view tampil di browser
- [ ] Catat semua bukti di plan + ROADMAP (latency, fps inferensi, GPU mem)

---

## Fase 1 — Definition of Done

1. Semua checkbox `[x]` dengan bukti (output command, screenshot browser, angka latency).
2. `pytest backend/tests -q` + `pytest vision/tests -q` (CPU) hijau di Windows; `-m gpu` hijau di server.
3. vitest + build hijau.
4. Demo end-to-end tercatat: event masuk DB < 2 s, live view jalan, heartbeat dashboard.
5. Merge `feat/fase-1-vision` → `main` + push + server sync.

## Risiko & mitigasi (dari brief)

- Decode substream varian codec → go2rtc transcode opsi (config), bukan kode custom.
- TensorRT export butuh GPU → dilakukan sekali di gspe-ai3 (Task 6), script di-commit bukan engine.
- MQTT auth → mosquitto passwd dibuat di Task 9; NODE_API_KEY dari .env.
- YOLO26 muda → benchmark task (n/s, e2e/default, 640/960) di Task 6; detektor config-driven.
