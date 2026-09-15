# I-Sentinel — Fase 2: Zona, Events, Clips, Web Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zona digambar di UI → vision-node eksekusi intrusion → event dengan clip mainstream + snapshot diputar di web inbox master-detail. Bukti Fase 2: orang melewati zona terlarang di kamera test → event `intrusion` + clip 1080p + snapshot tampil & diputar di browser.

**Architecture:** Zone model + editor UI (polygon norm 0–1, min 3 titik, tutup via start-point); config push MQTT retained (`isentinel/config/{node_id}`) — vision-node apply on-connect/on-change; analyzer intrusion (point-in-polygon di track centroid + jadwal); recorder (ffmpeg segment concat pre/post dari go2rtc mp4 segments, tanpa re-encode jika GOP memungkinkan); media API auth + web inbox.

**Tech Stack:** existing stack + ffmpeg (ada di server), go2rtc mp4 segments.

**Spec:** `docs/plans/2026-09-08-isentinel-design.md` §3–4 · Master: `docs/plans/00-master.md` · Brief: `docs/plans/03-fase-2-zona-events.md`

## Global Constraints

- Lihat master plan §Global Constraints — semua berlaku.
- Polygon tersimpan normalisasi 0–1 (JSON array titik), min 3 titik — enforced DB + API + UI; denormalisasi runtime di vision.
- Event JSON schema tetap master plan (zone_id kini terisi, payload.tambahan diperbolehkan).
- Clips/snapshots di `STORAGE_ROOT/clips|snapshots/YYYY/MM/DD/<event_id>.<ext>`; media HANYA lewat API auth (bukan static mount).
- Recorder TIDAK decode penuh — pakai segment go2rtc + ffmpeg concat; re-encode hanya jika concat gagal (ponytail note).
- Intrusion event rate-limit per zona dilaksanakan di Fase 3 (telegram); Fase 2 hanya event terbit + dedup_key existing.

---

### Task 1: Zone model + migration + zones API

**Files:**
- Create: `backend/app/models/zone.py`, `backend/alembic/versions/0003_zones.py`, `backend/app/schemas/zone.py`, `backend/app/api/zones.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`
- Test: `backend/tests/test_zones_api.py`

**Interfaces:**
- Produces:
  - `Zone(id, camera_id FK, name, type: free|restricted|absensi, direction: entry|exit|null, polygon JSON [[x,y],...] norm 0-1, schedule JSON null ({"days":[1-7],"start":"HH:MM","end":"HH:MM"} — null = 24/7), severity, rate_limit_min int default 5, snapshot bool default true, telegram bool default false, active bool default true, created_at)`.
  - Validasi: type restricted→severity wajib; absensi→direction wajib; polygon ≥3 titik, tiap koordinat 0–1; camera_id exists.
  - API: GET/POST /api/v1/zones?camera_id (GET viewer, POST admin), GET/PATCH/DELETE /api/v1/zones/{id} (admin utk mutasi). DELETE/PATCH → trigger config re-push (Task 3 hook stub dulu, publish di Task 3).

- [ ] **Step 1: Failing test** — CRUD + validasi polygon (2 titik → 422; koordinat 1.5 → 422; absensi tanpa direction → 422).
- [ ] **Step 2: Run — verify fail**
- [ ] **Step 3: Implement** + migration 0003 (hand-write, FK camera ON DELETE CASCADE).
- [ ] **Step 4: Run — pass** + full suite.
- [ ] **Step 5: Commit** — `feat: zone model + api (polygon validation, schedule)`

---

### Task 2: Vision config push (backend → MQTT retained)

**Files:**
- Create: `backend/app/services/config_push.py`
- Modify: `backend/app/api/zones.py`, `backend/app/api/cameras.py` (hook setelah create/update/delete zone/kamera → republish), `backend/app/core/config.py` (tidak ada perubahan)
- Test: `backend/tests/test_config_push.py` (mock paho publish)

**Interfaces:**
- Produces:
  - `publish_node_config(node_name: str)` — kumpulkan semua kamera aktif milik node + zona aktif per kamera + detection config (dari settings: model, nms, conf, imgsz + analyzer flags) → JSON → publish retained QoS1 ke `isentinel/config/{node_name}`. Kamera source_url untuk node server = `rtsp://localhost:8554/cam_{id}` (via go2rtc); untuk edge = `rtsp://{host}{path}` langsung (Fase edge).
  - Dipanggil: startup API (retained refresh), zone CRUD, camera CRUD.
  - Hook oportunistik: try/except log — publish gagal tidak boleh gagalkan request.

- [ ] **Step 1: Failing test** — publish payload berisi kamera+zona yang benar (assert struktur + retained flag), error tolerant.
- [ ] **Step 2: verify fail** → **Step 3: implement** → **Step 4: pass** → **Step 5: Commit** — `feat: mqtt config push (retained per node)`

---

### Task 3: Vision-node — config apply + analyzer intrusion

**Files:**
- Create: `vision/vision/analyzers/__init__.py`, `vision/vision/analyzers/base.py`, `vision/vision/analyzers/intrusion.py`
- Modify: `vision/vision/config.py` (parse zonas), `vision/vision/node.py` (subscribe config topic, apply → rebuild workers; analyzer chain per kamera), `vision/vision/transport/mqtt.py` (subscribe + callback)
- Test: `vision/tests/test_intrusion.py`, `vision/tests/test_config_apply.py`

**Interfaces:**
- Produces:
  - `analyzers/base.py`: `class Analyzer:` `on_frame(frame_ts, tracks) -> list[dict-event-payload-partial]`; registry `ANALYZERS = {"intrusion": IntrusionAnalyzer}` — analyzer baru = tambah 1 file + 1 entry.
  - `IntrusionAnalyzer(zone: dict)` — zona sudah denormalisasi? NO: analyzer menerima polygon norm + frame dims (w,h dikirim dari node per frame) → point-in-polygon (ray casting, pure math) pada track centroid; hanya dalam jadwal aktif (null = selalu); emit payload `{"zone_name":..., "polygon_ok": true}` sekali per track per masuk (state: set track_id yang sudah di dalam; keluar → remove).
  - Config apply: `node.VisionNode` — MQTT subscribe `isentinel/config/{node_id}` (retained → auto apply on connect); on message → rebuild CameraWorkers (stop lama, start baru) tanpa matikan proses; per kamera analyzers = [IntrusionAnalyzer(z) for z in zonas if type=restricted & active].
  - Event intrusion: type "intrusion", severity dari zona, zone_id terisi, payload + zone info; ts_event = frame ts.

- [ ] **Step 1: Failing tests** — point-in-polygon (in/out/edge case polygon konkaf); jadwal (di luar jam → tidak emit); track masuk→emit 1×, keluar→masuk lagi→emit lagi; config apply rebuild workers (2 kamera → 3 kamera).
- [ ] **Step 2: verify fail** → **Step 3: implement** → **Step 4: pass** (vision suite)
- [ ] **Step 5: Commit** — `feat: intrusion analyzer + config apply (hot reload)`

---

### Task 4: Recorder (clips + snapshots)

**Files:**
- Create: `vision/vision/recorder.py` (di vision: buffer segment per kamera, paling dekat source) — ATAU `backend/app/services/recorder.py`. RULING: recorder di **vision-node** (butuh akses disk lokal + segment mainstream via go2rtc yang jalan satu host dengannya; backend tetap menerima clip via HTTP blob upload yang sudah ada di kontrak). Blob endpoint diperluas di Task 5.
- Modify: `vision/vision/node.py` (worker: setelah analyzer emit event → recorder.capture(event)), `vision/vision/transport/mqtt.py` (tidak berubah), `vision/pyproject.toml` (ffmpeg via subprocess — tanpa dep baru)
- Test: `vision/tests/test_recorder.py` (ffmpeg mock; queue clip upload)

**Interfaces:**
- Produces:
  - `class Recorder:` per kamera — `update(ts)` menyimpan rolling buffer path segment mp4 go2rtc? RULING SIMPEL (ponytail): go2rtc menyediakan **MP4 recording via API** `/api/frame.jpeg` (snapshot) dan stream MP4 on-the-fly `http://go2rtc/api/stream.mp4?src=X&duration=Y` — recorder memanggil endpoint ini saat event: **pre-buffer tidak real-time; rekam post-event 30s + pre 8s dicoba via go2rtc mp4 offset** — jika go2rtc tidak mendukung offset, fallback: rekam post-only (30s) + snapshot pre-frame dari buffer frame PNG ring (numpy, 8s @ fps, 40 frame — murah). Snapshot: frame terbaik (bbox terbesar) disimpan JPEG.
  - Output: `{data_dir}/outbox/<event_id>.mp4` + `.jpg` → upload via HTTP `POST /internal/nodes/{id}/blobs` (sudah ada di backend Fase 1) → path dikembalikan → publish event UPDATE (mqtt `isentinel/events/media` topic baru: {event_id, clip_path, snapshot_path}) → backend update row.
  - Backend: tambah handler `isentinel/events/media` di consumer (Task 5).

- [ ] **Step 1: Failing tests** — recorder emits outbox files (fake ffmpeg via monkeypatch subprocess.run); upload queue retry; snapshot dari buffer frame.
- [ ] **Step 2: verify fail** → **Step 3: implement** → **Step 4: pass**
- [ ] **Step 5: Commit** — `feat: event recorder (clip via go2rtc mp4 + snapshot, blob upload)`

---

### Task 5: Media API + consumer media topic (backend)

**Files:**
- Modify: `backend/app/api/internal.py` (blobs endpoint: sudah ada? verifikasi Fase 1 — `POST /internal/nodes/{id}/blobs?kind=`), `backend/app/services/events_consumer.py` (subscribe `isentinel/events/media` → update event paths), `backend/app/api/events.py` (media endpoint)
- Create: `backend/app/api/media.py`, `backend/alembic/versions/0004_noop.py` (tidak perlu — kolom sudah ada)
- Test: `backend/tests/test_media.py`

**Interfaces:**
- Produces:
  - Verifikasi blob endpoint (Fase 1 Task brief menyebut tapi belum dibuat — buat sekarang): POST /internal/nodes/{id}/blobs?kind=clip|snapshot|crop (api-key) body binary → simpan `{STORAGE_ROOT}/{kind}s/YYYY/MM/DD/<uuid>.{mp4|jpg}` → `{"path": "clips/2026/09/15/<uuid>.mp4"}` (relative path).
  - Consumer: topic `isentinel/events/media` {event_id, clip_path, snapshot_path} → UPDATE event row (idempotent).
  - `GET /api/v1/media/{path:path}` (auth, path traversal guarded: resolved path harus di bawah STORAGE_ROOT) → FileResponse streaming (mp4 support range requests via FileResponse default).
- [ ] **Step 1: Failing tests** — blob upload saves file + returns relative path; media GET streams + 404 unknown; traversal `../../etc/passwd` → 400/404; consumer media topic updates event.
- [ ] **Step 2: verify fail** → **Step 3: implement** → **Step 4: pass**
- [ ] **Step 5: Commit** — `feat: blob storage + media streaming api + media topic consumer`

---

### Task 6: Frontend — Zone editor + Web inbox upgrade

**Files:**
- Create: `frontend/src/features/config/ZonesPage.tsx` (editor polygon canvas), `frontend/src/api/zones.ts`, `frontend/src/components/ZoneEditor.tsx`
- Modify: `frontend/src/features/events/EventsPage.tsx` (upgrade master-detail sesuai mockup 03: player clip `<video src=/api/v1/media/...>`, snapshot tab, metadata grid, aksi unduh), `frontend/src/main.tsx` (route /config/zones), i18n
- Test: `frontend/src/__tests__/zones.test.tsx` (klik-titik min 3, tutup start-point, properti save payload), update events test

**Interfaces:**
- Consumes: zones API, events API + media URL dari event row (clip_path/snapshot_path), snapshot frame kamera: `GET /api/v1/cameras/{id}/live` → snapshot URL (go2rtc) untuk background editor.
- Zone editor (mockup 06 tab Zona): frame kamera (img go2rtc snapshot, cache-bust) + SVG overlay polygon: klik = tambah titik (urut), ring start-point muncul ≥3 titik, klik ring = tutup; drag handle = pindah titik; dblclick = tambah titik di segmen terdekat? (YAGNI: cukup klik kanan hapus titik); properti panel: nama, tipe (restricted/absensi/free), severity, jadwal (24/7 atau jam+days), rate-limit (readonly note Fase 3), snapshot/telegram toggle (telegram disabled note), active.
- Events inbox (mockup 03): kiri daftar (severity dot, type badge, camera, waktu, thumb snapshot kecil), kanan detail: video player clip (atau placeholder bila belum ada clip), snapshot, metadata grid, tombol unduh + "buka live".

- [ ] **Step 1: Failing tests** — zone editor alur gambar (3 klik → ring → selesai → payload polygon norm); events master-detail render + video element dengan clip_path.
- [ ] **Step 2: verify fail** → **Step 3: implement** → **Step 4: vitest + build green**
- [ ] **Step 5: Commit** — `feat: zone editor (click-to-draw polygon) + events master-detail inbox`

---

### Task 7: Registrasi 20 kamera NVR + bring-up verifikasi (controller, di server)

**Files:** tidak ada code baru — verifikasi + data setup.

- [ ] Registrasi 20 kamera baru via API (ch 1,2,4,7..15,17..24 → id baru; sub ch+1) + probe + go2rtc sync (cam_{id})
- [ ] Buat zona test: 1 zona restricted di kamera aktif (mis. NVR-CAM-3) via API
- [ ] Restart vision-node → config applied (log analyzer aktif)
- [ ] Demo E2E: orang masuk polygon → event intrusion + clip + snapshot di DB → diputar di browser → screenshot bukti
- [ ] Catat bukti di plan + ROADMAP fase 2 [x] → merge + changelog 0.3.0

---

## Fase 2 — Definition of Done

1. Semua checkbox `[x]` dengan bukti.
2. `pytest backend/tests -q` + `pytest vision/tests -q` + vitest + build hijau (CPU, Windows & server).
3. Demo E2E: zona via UI → intrusion event dengan clip+snapshot diputar di browser.
4. Merge `feat/fase-2-zona` → `main`, tag `v0.3.0`, CHANGELOG update, server sync.

## Risiko (dari brief, updated)

- go2rtc mp4 endpoint offset pre-buffer → fallback post-only + snapshot pre-frame (tercatat ponytail).
- Polygon konkaf → ray casting handle semua simple polygon (unit test konkaf wajib).
- Event flood → zone filtering mengurangi; rate-limit Telegram di Fase 3.
- 24 kamera NVR aktif @5fps = 120 inferensi/s @4090 — aman (kapasitas ~590 FPS).
