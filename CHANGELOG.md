# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/) ringkas — satu baris per commit.
Skema versi: [SemVer](https://semver.org/). Status proyek: pra-rilis (`0.x`).

## [0.7.0] — 2026-09-21 · Fase 5: GPU hardware probe + device delegation + soak

### GPU hardware probe per node + detector device pin (Task 9)

- Vision node kini melaporkan hardware GPU lewat heartbeat MQTT: kolom `hw`
  (daftar GPU: nama, VRAM used/total, util %, **proses pemakai lintas user** via
  NVML, `python_vram_mb`) dan `modules.detector` (device pin, model,
  ms/frame). File baru `vision/vision/hardware.py` (pynvml, graceful fallback
  `{}` tanpa NVIDIA — heartbeat tetap jalan). Dep baru: `pynvml`.
- Task 9: `VISION_DETECTOR_DEVICE` (mis. `cuda:1`) — pin device detektor,
  diteruskan ke `YOLO.predict`; **fail-fast** saat pin tidak valid (node exit
  dengan log ERROR, bukan fallback senyap ke GPU lain).
- Backend: migration `0009` (`node.hw`, `node.modules` JSON nullable,
  expand-only), heartbeat consumer menyimpan keduanya, `GET /api/v1/nodes`
  mengembalikan. Heartbeat lama tanpa `hw` tetap kompatibel.
- Frontend: kartu **Perangkat node** di Dashboard — GPU chips + proses pemakai
  + badge `Detektor: PIN cuda:N` / `AUTO`. i18n id+en.

### Detector device delegation via UI (Nodes tab) + hot-reload (Task 9 lanjutan)

- Tab **Node** di Konfigurasi: dropdown device per node — sumber dari heartbeat
  `hw`; simpan → config push MQTT → node **hot-reload tanpa restart**.
- Backend: migration `0010` (`node.detector_device`), API
  `PUT /api/v1/nodes/{id}/detector-device` (admin, validasi `cuda:N` + cek hw).
- Prioritas: **DB (config push) > env > auto**; key `device` selalu ada —
  `""` = auto eksplisit. Pin invalid via config push → **reject config, node
  tetap hidup** (beda dari fail-fast start).

### Soak harness + laporan (Task 10–11)

- `deploy/loadtest/`: `make-streams.sh` (32 stream via go2rtc API `ffmpeg:`
  file source), `register-cams.py` (kamera SYNTH-01..N), `soak.sh` (sampler
  30 s per-GPU + RSS), `soak-churn.sh` (remove+add 32).
- Soak 2 jam + churn: **RSS delta 2.2% < 10% = tanpa leak**; GPU1 pinned
  bersih; 0 detector error selama soak. Laporan:
  `docs/evidence/fase-5/soak.md` (termasuk catatan jujur: p95 latensi event
  tak terukur — 0 person di video sintetis).

### RUNBOOK + rekonsiliasi unit (Task 12)

- `docs/RUNBOOK.md` baru: restart/backup/kamera/pin GPU/troubleshooting/
  alert/JWT/retensi/load test.
- `deploy/systemd/` direkonsiliasi ke aktual (`User=gspe-ai3`, path
  `project_cv`, `isentinel-vision`, + `isentinel-web.service`) — P5 tuntas.
- Diagram arsitektur ASCII di README.

### Perbaikan

- Engine TensorRT tidak lintas-device: rebuild `yolo26s.engine` di device pin
  (`CUDA_VISIBLE_DEVICES=1`, smoke 9.9 ms/frame) setelah runtime gagal memuat
  engine lama (dibangun untuk compute 12.0).

Rollback semua: `git revert` + `alembic downgrade` per-migration (expand-only).

## [Unreleased] — R4 Dwell trigger + WS cookie auth + events tabstrip

### WS events auth fallback cookie (Task 1)

- `backend/app/api/events.py`: `ws_events` menerima JWT dari query `?token=`
  **atau** cookie `isentinel_token` (`app.api.deps.COOKIE`). Sebelum ini UI selalu
  ditolak 1008 (JWT httpOnly tak bisa ditaruh di query) sehingga bbox person
  realtime tak pernah sampai Live View debugger.
- Test baru `backend/tests/test_events_ws.py`: cookie valid → konek + terima
  broadcast; tanpa cookie/token dan cookie rusak → 1008; query token lama tetap.
- Bukti: backend `pytest -m "not gpu"` 279 passed. Klien (`frontend/src/api/useWs.ts`)
  menghubung tanpa `?token` (cookie httpOnly saja) — komentar basi di file itu
  ikut dikoreksi agar kontraknya jelas.

### zone.dwell_seconds — trigger setelah N detik di zona (Task 2)

- Migration `0013_zone_dwell_seconds` (expand-only, `Integer NULL=false
  server_default '0'`), kolom model `backend/app/models/zone.py`, dan 3 kelas
  schema (`ZoneIn`/`ZonePatch`/`ZoneOut`, `ge=0`) di `backend/app/schemas/zone.py`.
- `config_push.build_node_config` mengirim `dwell_seconds` di payload zona —
  node memakainya untuk menahan emit event (Task 3). `0` = perilaku lama.
- Bukti: backend `pytest -m "not gpu"` 284 passed; migration round-trip
  `upgrade 0013 → downgrade 0012 → upgrade 0013` pd DB scratch ok, kolom
  `dwell_seconds INTEGER NOT NULL DEFAULT '0'`.

### Vision face_gate hormati dwell zona (Task 3)

- `vision/vision/analyzers/face_gate.py`: `dwell_seconds` > 0 menahan emit
  sampai track sudah di dalam polygon selama itu (jam mulai saat masuk zona,
  reset saat keluar). Cooldown 10s tetap; kunjungan yang tersedot cooldown tetap
  tidak emit. `0` = perilaku lama (emit saat masuk).
- Alasan: crop attendance sering berisi lantai/dinding (orang sudah lewat saat
  frame diambil) — dwell menahan orang di frame hingga crop+snapshot diambil.
- Bukti: `pytest vision/tests -m "not gpu"` 118 passed.

### Events detail tabstrip — revisi: Snapshot | Clip | Face crop (Task 4 review)

- Review user: tab **Detail dihapus** dari tabstrip. Sekarang 3 tab media —
  **Snapshot | Clip | Face crop** (crop hanya untuk event `attendance`, disabled
  bila `payload.crop_path` kosong), default **Snapshot**. Metadata grid
  (**Details**) dikembalikan tampil **di bawah media** untuk semua tab, seperti
  layout awal — bukan lagi tab terpisah.
- `frontend/src/features/events/EventsPage.tsx`, `frontend/src/app/theme.scss`
  (CSS tabstrip tetap), `frontend/src/app/i18n.tsx` (kunci `events.tab.detail`
  dihapus, jadi 2 bahasa). Bukti: `npx vitest run` 81 passed (15 di
  events.test.tsx), `npm run build` ok.

### Events detail tabstrip per mockup 03 (Task 4)

- `frontend/src/features/events/EventsPage.tsx`: panel detail kini tabstrip
  **Detail | Clip | Snapshot | Face crop** (mockup `mockup-ui/03-events.html`).
  Media tidak lagi ditumpuk: Clip = player + unduh, Snapshot = img beranotasi
  bbox/ID, Face crop = crop wajah beranotasi. Metadata grid tetap di Detail.
  Tab Face crop hanya muncul untuk event `attendance` dan **disabled** bila
  `payload.crop_path` kosong; ganti event → tab kembali ke Detail (derived state,
  tanpa effect).
- `frontend/src/app/theme.scss`: `.ev-tabstrip` / `.ev-tab` (+`.on` biru
  `#4589ff`, `:disabled` abu) persis nilai mockup. `frontend/src/app/i18n.tsx`:
  kunci `events.tab.*` + placeholder snapshot/crop, EN+ID.
- Bukti: `npx vitest run` 77 passed (14 di events.test.tsx), `npm run build` ok,
  `npm run lint` tanpa warning baru.

### Setting dwell di UI zona + gate (Task 5)

- `frontend/src/features/config/ZonesPage.tsx`: NumberInput **Dwell (detik)** di
  panel properti zona (semua tipe), helper "0 = langsung";
  `GatesPage.tsx`: kolom **DWELL (S)** per gate (PATCH langsung, disabled untuk
  non-admin). `frontend/src/api/zones.ts`: `dwell_seconds` di `Zone`/`ZonePayload`;
  `ZoneEditor.tsx` ikut menulis `dwell_seconds: 0` untuk zona baru.
- i18n EN+ID: `zones.dwell`, `zones.dwellHint`, `gates.col.dwell`.
- Bukti: `npx vitest run` 80 passed (3× berturut stabil), `npm run build` ok,
  `npm run lint` tanpa warning baru.

### Deploy Task 6 + inventaris behavior deteksi

- Deploy `gspe-ai3`: branch `feat/events-dwell-crop` (1c4d9dc → 541cca3),
  **alembic 0013** (0012 → 0013 head, dari `backend/` dgn `.env` root), event
  debug **#4625 dihapus** (`person_detect` tersisa 0), API restart (health ok),
  vision restart (`kill -9`; SIGTERM hang, 4 camera worker naik).
- Config push diverifikasi di retained MQTT `isentinel/config/server`:
  `cam 363 zones=[(9,'entry',3)]`, `detector cuda:1`, `face cuda:2` — **pin device
  tidak diubah** sesuai keputusan user (zona dwell 3 hanya zona 9 `Absence Server`).
- Bukti lapangan: 6 event attendance pasca-deploy dgn `crop_path`; snapshot
  berisi orang + bbox `ID n` terbakar (diunduh & diperiksa). **Temuan: crop wajah
  masih bisa berisi lantai** — bbox dari frame substream (waktu deteksi) dipetakan
  ke snapshot main stream yang *live* (keyframe bisa 2–4 s basi); crop `#4647`
  benar (face_quality 0.78), `#4650` salah. `attendance_event=0` karena belum ada
  wajah yang match ke karyawan ter-enroll (1 employee, 5 embedding).
- Dokumen baru `docs/detection-behavior-inventory.md`: peta alur, daftar analyzer
  + kondisi trigger persis (intrusion/loitering/running/face_gate/person_detect),
  media per event, dedup + rate limit + alerting, rantai attendance, plus 10
  temuan inkonsistensi untuk pembahasan penataan arsitektur.

### fix(dev): proxy Vite teruskan WebSocket — overlay deteksi akhirnya sampai

- `frontend/vite.config.ts`: proxy `/api` diubah dari string ke objek dengan
  **`ws: true`**. Tanpa ini browser (UI di port 5173) tidak pernah berhasil
  handshake `ws://<host>:5173/api/v1/ws/events` — terbukti: `ws://localhost:5173/...`
  timeout, `ws://localhost:8000/...` connect OK. Akibatnya overlay bbox detection
  di modal debugger Live View tak pernah terisi (zona tetap tampil karena dari REST).
- Jalur backend sudah benar dan diverifikasi: pesan disuntik ke MQTT
  `isentinel/detections/server` → diterima klien WS (cookie auth) sebagai
  `{"type":"detections",...}`.

### Perencanaan R5 + temuan sync go2rtc (Task 0 disetujui)

- Spec keputusan: `docs/superpowers/specs/2026-09-22-detection-model-redesign.md`
  (8 keputusan user: behaviors per zona + master per kamera, `trigger_seconds`
  per behavior, Advanced global, klip segment cache substream, attendance
  face-first substream, motion gate on+override, alias kamera single-stream,
  endpoint+tombol Sync go2rtc).
- Plan eksekusi: `docs/superpowers/plans/2026-09-22-detection-model-r5a.md`
  (Task 0–10; Task 0 = perbaikan sync go2rtc, R5b attendance & R5c klip menyusul).
- Temuan: kamera tanpa substream (ZKteco cam 364) hanya terdaftar sebagai
  `cam_364_main` di go2rtc → worker vision mati (`cannot open video source:
  rtsp://localhost:8554/cam_364`) dan `_save_clip` (yang memakai `cam_<id>`)
  akan gagal; sumber kameranya sendiri sehat (`h264 1920x1080 25fps`). Sync ke
  go2rtc hanya dipicu mutasi lewat API — tidak ada rekonsiliasi saat drift.

### R5 Task 0 — sync go2rtc: alias kamera single-stream + endpoint/tombol

- `backend/app/services/go2rtc.py`: `sync_camera` kini membangun `cam_<id>` dari
  `sub_src or main_src` dan `cam_<id>_main` dari `main_src or sub_src` — kamera
  yang hanya punya satu stream (mis. ZKteco `cam 364`, `rtsp_sub` kosong) tetap
  punya kedua nama, sehingga konsumen (`config_push` node server, `recorder`
  klip, snapshot) tidak lagi menunjuk stream yang tidak ada. Fungsi baru
  `sync_all(db)`: rekonsiliasi `cam_*` go2rtc vs kamera enabled (PUT yang hilang /
  sudah ada, DELETE yang tidak dimiliki, stream non-`cam_*` tidak disentuh).
- `backend/app/api/cameras.py`: `POST /api/v1/cameras/sync-go2rtc` (admin) →
  `{added, removed, kept}`. `backend/app/main.py`: sync best-effort saat startup
  (go2rtc belum tentu siap; gagal = warning, bukan crash).
- Frontend: tombol **Sync go2rtc** di tab Kamera (`data-testid="go2rtc-sync"`) +
  notification hasil `+n / −n stream`; `frontend/src/api/cameras.ts:syncGo2rtc()`;
  i18n EN/ID (`cameras.sync.*`).
- Bukti: backend `pytest -m "not gpu"` **289 passed** (5 test baru: alias sub→main,
  alias main→sub, skip tanpa path, `sync_all` idempotent + stream asing aman,
  endpoint admin-only); frontend `npx vitest run` **82 passed**; `npm run build` ok;
  `npm run lint` 22 warning (tidak bertambah).

### R5 Task 1 — migration 0014: zone.behaviors + setelan deteksi per kamera

- `backend/alembic/versions/0014_zone_behaviors.py`: tambah `zone.behaviors` (JSON),
  `zone.trigger_seconds`, `camera.ai_fps/confidence/analyzers/motion_enabled`
  (expand-only; kolom lama tetap ada). Backfill memetakan data lama → behaviors:
  `absensi`→`attendance` `[{kind:attendance,trigger:dwell}]`;
  `restricted`→`behavior` `[intrusion(trigger=dwell)]` + `loitering(trigger=loiter_seconds)`
  + `running(trigger=dwell,speed_limit_mps)`; `free`→`behavior` `[]`. `downgrade`
  mengembalikan `type` ke kosakata lama (`absensi`/`restricted`) supaya kode pra-R5
  tetap jalan.
- Model + schema: `backend/app/models/{zone,camera}.py`,
  `backend/app/schemas/zone.py` (validator `behaviors`: kind ∈
  intrusion|loitering|running|attendance, `trigger_seconds` int ≥ 0,
  `speed_limit_mps` opsional ≥ 0), `ZoneOut` membawa `behaviors`/`trigger_seconds`.
  `backend/app/api/zones.py`: PATCH type `attendance` wajib `direction`.
- Bukti: backend `pytest -m "not gpu"` **301 passed**; migration round-trip di
  scratch DB: backfill benar (`attendance [{'kind':'attendance','trigger_seconds':3}]`,
  `behavior [intrusion 2, loitering 30, running 2/1.5]`, `free []`), downgrade
  mengembalikan type + drop kolom, upgrade ulang jalan lagi.

### R5 Task 2 — config push: behaviors zona + setelan deteksi kamera

- `backend/app/services/config_push.py`: payload kamera kini membawa `ai_fps`
  (override kamera atau `settings.default_ai_fps`), `confidence` (override atau
  `detector_conf`), `analyzers` (`None` = semua, `[]` = tanpa analitik),
  `motion{enabled,threshold,min_area,force_interval_s}` dan tetap
  `meters_per_pixel` (dipakai analyzer running). Payload zona membawa `behaviors`
  + `trigger_seconds`; kolom lama (`dwell_seconds`,`loiter_seconds`,
  `speed_limit_mps`) tetap dikirim sebagai deprecated sampai node R5 terpasang.
- `backend/app/core/config.py`: setelan baru `default_ai_fps`, `motion_enabled`,
  `motion_threshold`, `motion_min_area`, `motion_force_interval_s` (nilai awal;
  nanti bisa dioverride dari DB di Task 6).
- Bukti: backend `pytest -m "not gpu"` **305 passed** (4 test baru: behaviors zona,
  override kamera, default global, `meters_per_pixel` tetap ada).

### R5 Task 3 — analyzer dibangun dari `behaviors` + master per kamera

- `vision/vision/node.py`: `behaviors_of(z)` (fallback kolom lama bila config
  pra-R5) + `_make_analyzers` membuat analyzer per entry behavior
  (`intrusion`/`attendance`/`loitering`/`running`), dengan `trigger_seconds` dan
  `speed_limit_mps` dari entry. Master `cam.analyzers` menyaring: `None` = semua,
  `[]` = tanpa analitik (hanya live view). `CameraCfg` menerima
  `analyzers`/`confidence`/`motion`.
- `vision/vision/analyzers/intrusion.py`: **trigger threshold** — zona dengan
  `trigger_seconds > 0` menahan emit sampai track bertahan selama itu di polygon
  (jam mulai saat masuk, reset saat keluar); `0` = perilaku lama.
- `confidence` per kamera kini benar-benar dipakai `PersonDetector` (sebelumnya
  field mati): `VisionNode._camera_conf` diisi saat config apply, factory detektor
  memakai `_camera_conf.get(cam_id) or detector_conf`.
- Bukti: `pytest vision/tests -m "not gpu"` **133 passed**.

### R5 Task 4 — motion gate (inferensi hanya saat ada gerakan)

- `vision/vision/motion.py` (baru): `FrameMotionGate` — frame di-downscale 64×36
  grayscale, `absdiff` + threshold piksel (default 25) + blob terbesar via
  `connectedComponentsWithStats`; gerak ≥ `min_area` (default 1%) → inferensi.
  `force_interval_s` (default 2 s) memaksa inferensi berkala agar objek diam tetap
  terdeteksi dan id ByteTrack tidak hilang (jarak frame < `max_age`).
- `CameraWorker` (node.py): gate dipasang dari config kamera; saat tertahan,
  inferensi dilewati dan `tracker.update([], ts)` dipanggil supaya track lama
  expire alami. **Config tanpa `motion` (pra-R5) → gate OFF** (perilaku lama).
- `backend/app/core/config.py`: `motion_threshold` = selisih intensitas piksel
  (0–255, default 25), `motion_min_area` = rasio blob minimum (default 0.01).
- Bukti: `pytest vision/tests -m "not gpu"` **133 passed** (8 test motion baru:
  frame statis tertahan, blok bergerak lolos, interval paksa, noise kecil ditolak,
  worker: 10 frame statis → 1 inferensi vs 10 tanpa gate vs 3 pra-R5).

### Perbaikan tes (flake) — isolasi fake MQTT

- `backend/tests/test_config_push.py`: patch `paho.mqtt.Client` bersifat global
  (modul paho dipakai bersama `events_consumer`), sehingga klien latar ikut
  tercatat di `FakeClient.calls` → `ValueError: too many values to unpack`. Kini
  assertion hanya menghitung klien yang benar-benar `publish`, plus stub
  `reconnect_delay_set`. Bukti: backend `pytest -m "not gpu"` **305 passed** 3×
  berturut (sebelumnya flaky 1 gagal per run).

## [Unreleased] — R3 Live View debugger

### Modal debugger kamera — overlay zona & bbox person realtime

- Vision node publish deteksi per frame ke MQTT `isentinel/detections/{node}`
  (QoS 0 fire-and-forget, drop saat broker putus — data deteksi lama tak berguna).
- Backend `events_consumer` subscribe topic itu → broadcast WS
  `{type: "detections", camera_id, boxes}` melalui hub yang sudah ada.
- Live View: klik tile → **modal debugger** (menggantikan big-on-top lama):
  stream kamera + overlay SVG — toggle **Tampilkan zona** (semua zona kamera,
  label nama+type: absensi hijau, restricted merah) dan **Tampilkan bbox person**
  (kotak + `ID n` oranye, realtime ~0.2s). Tile grid tetap hidup saat modal terbuka.
- person_detect = flag debug (`VISION_EMIT_PERSON_DETECT`, default false) —
  tidak pernah masuk produksi; 88 event debug terhapus dari DB + blob.
- Bukti: vision 113, backend 275, frontend 72, build ok.

## [Unreleased] — R2 Media capture toggles

### Snapshot bawa identitas track + toggle snapshot/clip per zona

- Vision: snapshot event kini **dibakar bbox track + label `ID n`** (warna per
  severity: critical merah, warning oranye, info hijau) — mengikat visual
  orang-pemicu ke snapshot; menjawab laporan "miss" (snapshot vs clip beda orang).
- Zona kini punya **toggle clip** (migration `0012` `zone.clip`, default true)
  di samping toggle snapshot yang sudah ada; recorder akhirnya **menghormati
  keduanya** (sebelumnya toggle snapshot diabaikan — selalu capture dua-duanya).
  Flag zona dibawa ke event envelope oleh worker (`ev.snapshot`/`ev.clip`);
  event tanpa flag (legacy) default capture. Clip tetap 30s post-event —
  go2rtc 1.9.9 tidak mendukung pre-roll (`back` param → 404, terverifikasi).
- UI: tab Zones/Attendance Gates — toggle "Rekam clip event (30 detik)";
  detail Events menampilkan **crop wajah beranotasi** (payload `crop_path`)
  untuk event attendance.
- Bukti: vision 112 test (recorder flags + draw, config apply media), backend
  273 (config push zone clip), frontend 71 + build.

## [Unreleased] — R1 Testing & Refining (anotasi wajah, device split, enrollment)

### Delegasi device per-analyzer (tab Node) + rebuild embedder

- Delegasi GPU kini per-analyzer: **detector YOLO** dan **face recognition**
  masing-masing punya pin sendiri. Backend: migration `0011` (`node.face_device`),
  API `PUT /api/v1/nodes/{id}/face-device` (pola + validasi sama dengan
  detector-device), config push kirim `face: {device}` berdampingan
  `detector: {device}` — struktur map per-analyzer siap diperluas untuk
  analyzer baru. Vision: device face dari config push menang atas env;
  perubahan device → **FaceEmbedder di-rebuild** (provider onnxruntime ikut),
  pin invalid → config ditolak, node tetap hidup.
- UI tab Node: dua dropdown per node (Device detektor / Device face
  recognition), i18n EN/ID; simpan hanya mengirim PUT untuk field yang berubah.

### Anotasi wajah + identitas pada crop attendance

- Vision node: bbox wajah (SCRFD) + label `face <det_score>` digambar pada
  crop attendance **sebelum upload**; `payload.face_bbox` ikut di event.
- Backend: setelah match sukses, crop di-overwrite dengan nama employee +
  match_score (`app/services/annotate.py`, Pillow best-effort — gagal tidak
  memblok attendance). Dep baru backend: `pillow`.

### Enrollment multi-upload + auto-crop + gate

- API baru `POST /employees/{id}/photos/batch` (≤5 foto): per-file hasil
  `{ok, quality, reason, duplicate_of?}` — foto mentah tidak disimpan,
  hanya hasil crop wajah (SCRFD bbox + margin 30%). Dup wajah employee lain
  → warning cosine ≥ `FACE_DUP_WARN` (default 0.6, non-blocking).
- UI Enrollment: input `multiple`, hasil per foto (ok/skor/duplikat/alasan
  gagal), i18n EN/ID.

### Operasional

- Runbook baru `docs/runbooks/events-cleanup.md`; eksekusi 2026-09-21:
  events 4491 → 5 (1 contoh per type dengan 2 media), blob disk terbersihkan.
- Bukti: vision 108 test, backend 272, frontend 70, `npm run build` ok.

## [Unreleased] — Face embed at node (Opsi B)

### Face embedding pindah ke vision node — server hanya match gallery

- **Delegasi wajah per-node**: vision node kini embed wajah sendiri (InsightFace
  SCRFD + ArcFace `buffalo_l`) dari crop yang sudah di-produksi face gate, lalu
  event MQTT attendance membawa `embedding` (512-d L2-normed) + `face_quality`
  (det_score). Backend tidak lagi menjalankan inferensi wajah untuk match —
  cukup cosine vs gallery terpusat (`match_vector`). Gallery tetap di server:
  enroll baru langsung efektif tanpa sentuh edge (kriteria Fase E tetap terpenuhi).
- Kompatibel mundur dua arah: payload tanpa `embedding` → backend embed crop
  seperti sebelumnya (`match_crop`); node tanpa insightface → kirim crop saja.
- File: `vision/vision/face.py` (FaceEmbedder, lazy import + cache gagal),
  wiring `vision/vision/node.py` (`_attach_crop` menempel embedding, embedder
  dibuat sekali per node dan dibagikan ke worker), config node
  `VISION_FACE_EMBED` (default true), `VISION_FACE_DEVICE` (""/cpu/cuda:N),
  `VISION_FACE_MODEL_DIR` (default `<data_dir>/faces_models`). Backend:
  `match_vector()` di `app/services/face.py`, cabang embedding di
  `handle_face_event` (`app/services/attendance.py`). Extra paket vision:
  `face = [insightface>=0.7, onnxruntime-gpu>=1.19]`.
- Bukti: vision 98→104 test (`tests/test_face_embed.py` 5, `tests/test_node_face_embed.py` 6), backend 16 test attendance logic baru (embedding match,
  low_quality reject, fallback crop), full suite backend 265 passed.
- Deploy server: `pip install -e "./vision[face]"` di venv, `VISION_FACE_MODEL_DIR`
  mengarah ke `faces_models` di STORAGE_ROOT, restart `isentinel-vision`.
  Catatan: dep insightface menarik `onnxruntime` (CPU) yang menutupi
  `onnxruntime-gpu` → setelah install, uninstall `onnxruntime` polos atau
  `pip install --force-reinstall --no-deps onnxruntime-gpu` supaya CUDA EP aktif.
- Rollback: `VISION_FACE_EMBED=false` + restart node (kembali kirim crop saja);
  backend menerima kedua bentuk payload tanpa perubahan.

## [Unreleased] — Fase E: Edge Jetson

### Detector device delegation via UI (Nodes tab) + hot-reload

- Admin kini pin GPU detektor **per node via UI**: tab **Node** di
  Konfigurasi — dropdown diisi dari heartbeat `hw` per node (Auto +
  `cuda:N — <nama GPU>`), simpan → config push MQTT → node **hot-reload
  tanpa restart**, badge Dashboard ikut berubah.
- Backend: migration `0010` (`node.detector_device` string nullable),
  `build_node_config()` kirim `detector.device`, API
  `PUT /api/v1/nodes/{id}/detector-device` (admin; validasi format
  `cuda:N` + cek jumlah GPU dari hw heartbeat; 422 bila invalid).
- Prioritas device: **DB (config push) > env `VISION_DETECTOR_DEVICE` >
  auto**; key `device` selalu ada di payload sehingga "" = auto eksplisit.
- Vision `apply_config()`: pin invalid dari config push → **reject config +
  log ERROR, node tetap hidup dengan device lama** (fail-fast exit tetap
  hanya di start).
- Keterbatasan hot-reload: inferensia pindah device seketika, tapi CUDA
  context lama di GPU sebelumnya baru lepas saat proses node direstart.
- Evidence: backend **262 passed**, vision **93 passed**, vitest **68**,
  build OK; live: pin cuda:1 via API & UI → heartbeat `device: cuda:1`
  tanpa restart vision; unpin → `auto`; invalid ditolak 422.
  Screenshots: `docs/evidence/2026-09-18-nodes-tab-pin-cuda1.png`,
  `nodes-tab-en.png`. Rollback: `git revert` + `alembic downgrade 0009`.

### GPU hardware probe per node + detector device pin (Task 9)

- Vision node kini melaporkan hardware GPU lewat heartbeat MQTT: kolom `hw`
  (daftar GPU: nama, VRAM used/total, util %, **proses pemakai lintas user** via
  NVML, `python_vram_mb`) dan `modules.detector` (device pin, model,
  ms/frame). File baru `vision/vision/hardware.py` (pynvml, graceful fallback
  `{}` tanpa NVIDIA — heartbeat tetap jalan). Dep baru: `pynvml`.
- Task 9: `VISION_DETECTOR_DEVICE` (mis. `cuda:1`) — pin device detektor,
  diteruskan ke `YOLO.predict`; **fail-fast** saat pin tidak valid (node exit
  dengan log ERROR, bukan fallback senyap ke GPU lain).
- Backend: migration `0009` (`node.hw`, `node.modules` JSON nullable,
  expand-only), heartbeat consumer menyimpan keduanya, `GET /api/v1/nodes`
  mengembalikan. Heartbeat lama tanpa `hw` tetap kompatibel.
- Frontend: kartu **Perangkat node** di Dashboard — GPU chips + proses pemakai
  + badge `Detektor: PIN cuda:N` / `AUTO` (kuning bila auto). i18n id+en.
- Evidence: vision **89 passed**, backend **256 passed** (`-m "not gpu"`),
  frontend **66 tests**, build OK; live di server: 3 GPU (4090 + 2×5080) +
  proses vLLM/isaacsim/vision tampil. Screenshots:
  `docs/evidence/2026-09-18-dashboard-node-hw-{en,id}.png`.
  Rollback: `git revert` + `alembic downgrade 0008`.

### Camera flow polish: self-contained wizard, compact panel, columns

- Wizard self-contained: field **Port** (default 554) di samping IP/Host;
  endpoint host = `ip` atau `ip:port`. Panel **Sumber & kredensial** collapsed
  jadi satu baris ringkasan (khusus import CCTV / perubahan NVR); section Grup
  dihapus dari UI (grup auto dari Lokasi); CamerasPage berhenti fetch
  `/location-groups`. List kamera: **kolom Lokasi terpisah** dari Nama.
  Live View: filter lokasi bisa direset ke **All locations** (item `__all__`).
- Evidence: frontend **13 files / 65 tests passed**, build **949 modules**;
  verifikasi browser di server (port default 554, form grup hilang, reset
  filter terbukti). Screenshots: `docs/evidence/camera-page-compact-final.png`,
  `camera-wizard-v3-port.png`, `camera-list-location-column.png`,
  `live-view-filter-all.png`. Rollback: `git revert`.

### Camera management: wizard sederhana + scan channel + FK SET NULL

- Wizard "Tambah kamera" disederhanakan sesuai keputusan desain: field Nama, Lokasi,
  IP/Host, Node, lalu "Deteksi otomatis" (POST `/api/v1/cameras/scan` memindai channel
  NVR 1-32 paralel wave, berhenti 2 wave kosong; dropdown stream terdeteksi dengan
  label `ch N — MAIN res·codec / SUB res·codec`, pilihan pertama otomatis terpilih),
  fallback "Isi path manual" (MAIN/SUB + probe exact). Combobox Sumber stream/Grup
  lokasi/Override kredensial dihapus dari wizard; grouping kini otomatis dari teks
  Lokasi (get-or-create grup sama nama, backend `_prepare_camera_data`), masih bisa
  eksplisit lewat import. Error simpan kini InlineNotification (409 duplicate jelas
  terlihat), bukan teks kecil. `LocationGroupSelect.tsx` dihapus (tak terpakai).
- `POST /api/v1/cameras/scan` (admin) + `scan_camera_channels()` di services/probe.py.
- Migration `0008`: `alert.camera_id` nullable + FK `event/alert.camera_id` →
  `ON DELETE SET NULL` (hapus kamera tidak lagi 500 oleh event/alert lama).
- Evidence: backend **252 passed**, frontend **13 files / 64 tests passed**,
  `npm run build` 949 modules. Rollback: `git revert` + alembic downgrade 0007.

### Agent contributor guide

- `AGENTS.md` (new) documents project overview, tech stack, key features, structure,
  commands, coding conventions, workflow, current-state pointers, and the repo rules
  (incl. the no-AI-attribution rule). Derived from the actual tree: `backend/app/*`,
  `vision/vision/*`, `frontend/src/*`, `deploy/*`, `docs/*`, `pyproject.toml`s,
  `package.json`, `.env.example`. Server credentials are deliberately NOT recorded —
  only host/IP/paths plus a pointer to the gitignored note and server `.env`.
  Alongside: `README.md` server path corrected `/opt/isentinel` →
  `/home/gspe-ai3/project_cv/I-Sentinel`, stale "frontend placeholder" line replaced,
  and the repo-vs-running systemd unit mismatch (Fase 5 Task 12) plus the
  no-passwordless-sudo restart procedure noted; `frontend/package.json` gained
  `"test": "vitest run"`; `.gitignore` now excludes `.commandcode/`,
  `.cooperstructure/`, `.impeccable/`. Evidence: `npm test` → **13 files / 64 tests
  passed** in 32.26s. Impact: agents and new contributors get one accurate entry
  point; no runtime code touched. Rollback: `git revert` the two commits.

### Runtime data layout

- Runtime data on `gspe-ai3` now lives under the sibling
  `/home/gspe-ai3/project_cv/I-Sentinel-data/{api,vision}` instead of the Git
  worktree/default home paths. `.env` carries `STORAGE_ROOT`, `FACE_MODEL_DIR`,
  and `VISION_DATA_DIR`; old roots were copied, not deleted. Evidence: API health
  returned `{"status":"ok"}`, both systemd services are active, live process
  environments report the target paths, and target contents include
  `clips/crops/faces/faces_models/models/snapshots` plus `outbox/queue`. Impact:
  deployments no longer mix runtime growth with source checkout. Rollback:
  restore `.env.before-runtime-migration-20260916-160718` and restart API/vision;
  delete neither old root until separately approved.

### Camera management B′

- `feat/camera-management-b-prime`: adds source-aware camera management in
  `backend/app/models/camera.py`, `backend/app/models/credential_profile.py`,
  `backend/app/models/location_group.py`, `backend/app/models/stream_source.py`,
  `backend/app/api/cameras.py`, `backend/app/api/probe.py`,
  `backend/app/api/credential_profiles.py`, `backend/app/api/location_groups.py`,
  `backend/app/api/stream_sources.py`, `backend/app/schemas/camera.py`,
  `backend/app/schemas/credential_profile.py`, `backend/app/schemas/location_group.py`,
  `backend/app/schemas/stream_source.py`, `backend/app/services/stream_endpoint.py`,
  `backend/app/services/probe.py`, `backend/app/services/go2rtc.py`,
  `backend/app/services/config_push.py`, `backend/scripts/camera_management_migrate.py`,
  `backend/alembic/versions/0007_camera_management_expand.py`,
  `frontend/src/api/cameras.ts`, `frontend/src/api/credentialProfiles.ts`,
  `frontend/src/api/locationGroups.ts`, `frontend/src/api/streamSources.ts`,
  `frontend/src/features/config/CamerasPage.tsx`,
  `frontend/src/features/config/CameraWizard.tsx`,
  `frontend/src/features/config/CameraSourcesPanel.tsx`,
  `frontend/src/features/config/LocationGroupSelect.tsx`,
  `frontend/src/app/i18n.tsx`, `.env.example`, and
  `docs/runbooks/camera-management-migration.md`. Evidence: offline PostgreSQL
  Alembic SQL contains all five required `0007` statements; backend **249/249**
  collected tests passed in isolated batches; focused frontend **3 files / 19 tests**
  passed; `npm run build` transformed **950 modules** in **5.94s**. Impact: admins
  manage sources, locations, and environment-referenced credentials without API
  secret leakage while legacy camera fields remain compatible. Rollback: follow
  `docs/runbooks/camera-management-migration.md`; no server migration was run.

### CCTV inventory import

- `0f2a4b3`: safe admin-only import parses `temp/data/cctv-list.txt` in
  `frontend/src/features/config/CamerasPage.tsx`, then previews/applies normalized
  `(host, rtsp_main)` matches in `backend/app/api/cameras.py` and
  `backend/app/schemas/camera.py`; `frontend/src/api/cameras.ts` and
  `frontend/src/app/i18n.tsx` carry the contract. Existing camera IDs and probe metadata stay
  intact; apply refuses unmatched or invalid input and never deletes cameras. Coverage:
  `backend/tests/test_cameras_api.py` and `frontend/src/__tests__/cameras.test.tsx`.
  Evidence: backend camera API **14 passed**, frontend cameras/events/alerts **23 passed**,
  `npm run build` (**945 modules transformed**), server preview at `192.168.2.133:5173`
  returned **24/24 matched, 24 changed**, then explicit approval produced
  `POST /api/v1/cameras/import?apply=true` **200**, `applied=true`, **24 updated**, **0 errors**,
  **0 unmatched**. GET verification returned **25 total**: imported IDs **4–27** match every
  file name/location/path; legacy ID 3 (`Cam 1`, `192.168.0.64`) stayed untouched by the
  no-delete contract. Screenshots: `docs/evidence/camera-import-preview-desktop.png` and
  `docs/evidence/camera-import-applied-desktop.png`. Rollback: revert `0f2a4b3` for code;
  restore pre-import values from the preview `before` payload for data.

### Camera Edit & Events triage

- `feat/camera-edit-events` (`35bd458`, `6b48bd9`, `29301bc`, `a3753f7`): Camera admin kini
  punya tombol **Ubah** dengan wizard terisi; perubahan metadata tersimpan langsung, sedangkan
  perubahan host/node wajib probe baru. Probe edit tidak menulis state sebelum **Simpan** dan
  respons probe lama diabaikan. Perubahan source: `frontend/src/features/config/CamerasPage.tsx`,
  `frontend/src/features/config/CameraWizard.tsx`, `frontend/src/app/i18n.tsx`,
  `backend/app/schemas/camera.py`; coverage: `frontend/src/__tests__/cameras.test.tsx` dan
  `backend/tests/test_cameras_api.py`.
- Events diubah menjadi master-detail triage mengikuti `mockup-ui/03-events.html`: filter tipe/
  kamera/severity, rentang 24 jam/7 hari/30 hari/semua, pencarian, jumlah hasil, tombol baris
  yang keyboard-accessible, metadata/media nyata, dan status alert/Telegram tetap memakai API
  yang ada. Tidak ada fake zone history/tracking/false-positive dan tidak ada penghapusan riwayat.
  Perubahan source: `frontend/src/features/events/EventsPage.tsx`, `frontend/src/app/theme.scss`,
  `frontend/src/app/i18n.tsx`; coverage: `frontend/src/__tests__/events.test.tsx`.
  Bukti: focused frontend **3 files / 22 tests PASS**, camera API **11 passed**, `npm run build`
  (**945 modules transformed**, **8.21s**), dan Playwright langsung ke `192.168.2.133:5173`
  membuktikan modal Camera Edit prefilled + gate probe, Events search/range/detail, serta mobile
  tanpa horizontal overflow (`documentScrollWidth=375`, viewport `390`). Screenshot:
  `docs/evidence/camera-edit-desktop.png`, `docs/evidence/events-redesign-desktop.png`, dan
  `docs/evidence/events-redesign-mobile.png`. Dampak: admin dapat mengubah kamera tanpa
  mengandalkan User Management; operator mendapat triage event ringkas tanpa mengubah data
  historis. Rollback: revert `29301bc`, `6b48bd9`, `a3753f7`, `35bd458` (kembali ke `f3d960f`).

### UI shell & Configuration workbench

- `feat/ui-shell-configuration` (`79fe25a`, `e6b12c5`, `8b29e8a`, `918d526`, `dbb093d`,
  `eacc1dc`, `1404c57`): konsolidasi empat halaman admin menjadi satu workbench
  `/configuration?tab=cameras|zones|gates|storage`; sidebar kini punya satu entry
  Configuration di System, logout berada di kartu akun, rail Carbon tidak melebar saat
  link menerima pointer/fokus keyboard, label toggle mengikuti state desktop/mobile,
  dan editor Zones menumpuk pada viewport sempit. Perubahan source: `frontend/src/app/AppShell.tsx`,
  `frontend/src/app/theme.scss`, `frontend/src/app/i18n.tsx`, `frontend/src/main.tsx`,
  `frontend/src/features/config/ConfigurationPage.tsx`,
  `frontend/src/features/config/CamerasPage.tsx`,
  `frontend/src/features/config/ZonesPage.tsx`,
  `frontend/src/features/config/GatesPage.tsx`,
  `frontend/src/features/config/StoragePage.tsx`. Regression coverage diperbarui di
  `frontend/src/__tests__/shell.test.tsx`, `frontend/src/__tests__/configuration.test.tsx`,
  `frontend/src/__tests__/cameras.test.tsx`, `frontend/src/__tests__/zones.test.tsx`,
  `frontend/src/__tests__/gates.test.tsx`, dan `frontend/src/__tests__/storage.test.tsx`.
  Bukti: focused Vitest **6 files / 26 tests PASS**, `npm run build` (**945 modules transformed,
  built in 6.59s**), Playwright langsung ke `192.168.2.133:5173` membuktikan empat tab,
  fallback query invalid/missing, back/forward, Gate → Zones, rail pointer/keyboard,
  logout expanded/rail, mobile query-close, dan Zones tanpa horizontal overflow.
  Screenshot: `docs/evidence/ui-shell-configuration-desktop.png` dan
  `docs/evidence/ui-shell-configuration-mobile-zones.png`. Dampak: admin mendapat satu
  konteks konfigurasi tanpa kehilangan operasi panel yang ada; rollback: revert commit
  `1404c57`, `eacc1dc`, `dbb093d`, `918d526`, `8b29e8a`, `e6b12c5`, lalu `79fe25a`.

- `0b0e3ca` feat: playback live view memakai **mainstream** (`cam_N_main`) — WebRTC/MSE/HLS
  URL `/live` beralih dari sub ke main; substream tetap milik AI (vision pull RTSP lokal) +
  snapshot fallback. Terbukti di browser LAN: 24/24 tile playing, 23 tile ≥1920 lebar
  (`docs/evidence/fase-5/live-mainstream.png`). Catatan: backend URL berubah → API harus
  restart setelah pull.

- `6de1c50`/`06e7869` feat: live view streaming go2rtc — `<video-stream>` (vendor player
  resmi go2rtc video-rtc.js v1.6.0) mode `webrtc,mse` per tile; fallback snapshot proxy
  2 detik kalau transport gagal 10 s; backend tidak berubah (URL `/live` yang sudah ada).
  Syarat infra: firewall ufw LAN membuka 1984/tcp + 8555/udp, dan `api.origin` go2rtc
  diperluas (go2rtc menolak WS handshake 403 dengan Origin web). Bukti: Playwright di
  `docs/evidence/fase-5/live-streaming.png` — **24/24 tile playing** (readyState 4),
  fokus tile playing, go2rtc RSS 160 MB / CPU ~10%.

## [0.6.0] — 2026-09-16 · Fase 5: Hardening (Task 1-8)

Hardening retensi, keamanan, dan resiliensi. Sistem live di server terverifikasi:
migration 0006 diterapkan, API restart + route baru aktif, halaman Retensi & Storage
berjalan dengan data nyata, harness resiliensi **5 PASS / 0 FAIL**.

### Perubahan

- **Retensi dua-lapis** (`82538f7`, `21d4931`): `Event.media_expired` + migrasi 0006;
  sweeper `app/services/retention.py` — lapis DB (event > `RETENTION_DAYS` → file dihapus,
  event ditandai, path di-null-kan) + sapuan orphan (file tanpa baris event, berbasis mtime),
  dengan guard path-escape (`_safe_join` — path DB tak bisa menghapus di luar `storage_root`)
  dan dry-run yang tidak menyentuh apa pun.
- **API storage** (`1962cad`): `GET /api/v1/storage/stats` (disk, per-jenis, sweep terakhir
  dari `Setting.retention_last_sweep`) + `POST /api/v1/storage/sweep?dry_run=` (admin-gated);
  helper test `admin_headers`/`viewer_headers` di conftest.
- **Entrypoint + timer systemd** (`5618396`): `backend/scripts/retention_sweep.py`
  (bootstrap sys.path supaya `python scripts/…` jalan tanpa install paket) + unit
  `deploy/systemd/isentinel-retention.{service,timer}` (03:00 harian, `Persistent=true`).
  **Pemasangan di server menunggu user (sudo).**
- **Halaman Retensi & Storage** (`9e485e7`): route `/config/storage`, nav admin-only,
  kartu disk/retensi/path, tabel per jenis, kartu sweep terakhir, tombol Dry run +
  Jalankan sekarang; i18n ID/EN. Bukti: `docs/evidence/fase-5/storage-page.png`,
  `storage-dryrun.png` — data cocok `df -h` (915G, sisa 132G); dry run UI terbukti
  `2117 → 2117` file.
- **Rate-limit login** (`6da6af3`): 429 + `Retry-After` setelah `login_max_attempts`
  gagal per (username, ip); reset saat login sukses; state per-proses (uvicorn satu
  worker); fixture autouse reset `_FAILURES` mencegah kebocoran antar-test —
  full suite **215 passed** saat itu.
- **Sisa keamanan pass** (`1171d5e`): PATCH attendance ternyata sudah admin-gated
  (2 test penegasan); keputusan CORS (sengaja tak ada, same-origin) + rotasi JWT
  (prosedur operasional) tercatat di `docs/plans/00-master.md`.
- **Harness resiliensi** (`cf09af8`, `df2e3b0`, `85b14b1`): `deploy/loadtest/resilience.sh`
  — polling status node dengan deadline, bukan sleep tetap (LWT retained datang
  segera setelah kill -9; sleep tetap 20/30 s sempat menghasilkan FAIL palsu).
  Bukti: `docs/evidence/fase-5/resilience.txt` — 5 PASS / 0 FAIL di gspe-ai3.

### Verifikasi

- Backend: **217 passed** (204 sebelum Fase 5 + 6 retensi + 3 storage + 2 ratelimit + 2 security)
- Frontend: **39 passed** + `npm run build` sukses
- Alembic: 0005 → 0006 diterapkan di server (PostgreSQL) sebelum restart API
- Server `gspe-ai3`: main @ `85b14b1`, API + web aktif, node vision online

### Ditunda (keputusan user)

- Task 9-12 (pin GPU, generator stream sintetis, soak, dokumentasi operasional).
  D1 (GPU mana + durasi) dan D2 (izin `sudo apt install ffmpeg`) belum diambil.
- Pemasangan unit `isentinel-retention.{service,timer}` ke `/etc/systemd/system/`
  butuh `sudo` — perintah siap, menunggu user.

## [0.2.0] — 2026-09-15 · Fase 1: Vision Inti

Pipeline vision end-to-end: YOLO26s TensorRT (nms=False) + ByteTrack → MQTT → DB → dashboard/live/events. Terverifikasi 4 kamera NVR via go2rtc di server GPU.

### Commits (ringkas)

- `728de79`/`0449061` feat: event model, ingest idempotent, events API + ws hub
- `3454791` feat: mqtt events consumer (events + node lwt)
- `1098d86` feat: go2rtc stream sync + live url endpoint
- `9d5746e` feat: vision pipeline stages (source, detector iface, byte tracker)
- `b09c6cc`/`d3c5e7d` feat: vision node runner (mqtt transport, disk queue, graceful)
- `0d60702` feat: yolo26s tensorrt export script + gpu smoke test
- `cef8afa` feat: internal heartbeat ingest + node staleness + vision deploy files
- `3dced18` feat: dashboard tiles, live view (snapshot), events live list
- `f25c664` fix: g100 dark theme via css custom properties
- `ea892ee`/`e5a8302` fix: ts_event wall-clock (monotonic offset)
- `1bdb19b`/`9c25396`/`17f3d10` fix: ingest node-by-name + iso parsing + relationship
- `2a65d4c` feat: consumer marks node online from heartbeat topic

### Highlights

- **vision/** paket terpisah (tanpa FastAPI): pipeline source→detector→tracker→emit, DiskQueue store-and-forward, LWT+heartbeat MQTT
- **YOLO26s TRT FP16 nms=False**: 1.7 ms/frame di 4090, 762 MB GPU
- **Backend**: consumer MQTT (events/heartbeat/LWT), idempotent ingest, WS broadcast, go2rtc sync
- **Frontend**: dashboard tile hidup, live view snapshot grid (fokus+fullscreen), events list realtime

## [0.5.5] — 2026-09-15 · Zero-secret: dua file config ter-track

Ditemukan saat menjawab pertanyaan "apakah semua fitur berjalan?". Keduanya kelas yang sama
dengan temuan `.git/config` sebelumnya: **file template dan file runtime memakai nama yang sama**.

### Perbaikan

- `c391359` fix(security): `deploy/go2rtc/go2rtc.yaml` ter-track padahal dipakai go2rtc
  sebagai config runtime dan stream di dalamnya memuat kredensial RTSP kamera. Di server
  file itu 51 URL `rtsp://` (25 kamera × main+sub) dengan mode **664 (world-readable)**,
  dan karena ter-track, `git add -A` di server akan meng-commit semuanya.
  → `go2rtc.yaml` jadi `go2rtc.example.yaml` (template, tetap tracked) + `.gitignore`
  menambah `deploy/go2rtc/go2rtc.yaml`. Path runtime tidak berubah, unit systemd tidak disentuh.
- `e9a764b` fix(security): `vision.env` tidak ter-ignore — pola `.env` (nama persis) dan
  `.env.*` tidak menangkapnya. Tambah `*.env` + negasi `!*.env.example`.
- `c4bd09d` fix(ui): kamera `enabled=false` tidak lagi tampil di Live View

### Diverifikasi tidak bocor

- `git log -S gspe123456` / `-S gspe-intercon` / `-S 'admin:gspe'` → **0 commit**
- `git grep` kredensial di file ter-track → kosong
- Yang berisi kredensial hanya working copy server, tidak pernah ter-commit
- Setelah perbaikan: `git status` di server bersih, `git ls-files deploy/go2rtc/` hanya
  menyisakan `go2rtc.example.yaml`, config runtime mode **640**

### Catatan

Kredensial kamera ikut tercecer ke transcript sesi ini saat diagnosis (isi `go2rtc.yaml`
server ikut ter-dump oleh batch command). Kalau transcript ini tersimpan di tempat bersama,
kredensial kamera di jaringan CCTV perlu dianggap perlu dirotasi.

## [0.5.4] — 2026-09-15 · Live view benar-benar jalan dari klien LAN

`7c89eb1` fix(backend): `GET /api/v1/cameras/{id}/snapshot` mem-proxy frame go2rtc lewat API.

Urutan kejadiannya penting untuk dicatat:

1. Sebelum sesi ini: `snapshot` = `http://localhost:1984/...` (host dari header `Host`
   yang dihancurkan proxy Vite) → tiap tile gagal cepat, live view mati.
2. `fd42e31` memperbaiki host ke `GO2RTC_PUBLIC_HOST` → malah LEBIH BURUK: tiap tile
   menggantung 5 detik, karena port 1984 diblokir firewall server.
3. Diukur dari klien: `5173`/`8000`/`1883` TERBUKA, `1984`/`8554` TIMEOUT (connect DROP).
   `ss -lntp` menunjukkan go2rtc bind `*:1984` — jadi murni firewall.
4. Diperbaiki dengan proxy, bukan dengan membuka port.

Alasan memilih proxy: API go2rtc **tidak punya autentikasi**. Membuka 1984 ke LAN berarti
siapa pun di jaringan bisa membaca semua stream kamera. Proxy memakai port 8000 yang sudah
terbuka dan sudah di belakang `get_current_user`, jadi permukaan serangan tidak bertambah.

- `snapshot` kini path same-origin `/api/v1/cameras/{id}/snapshot` (butuh login, 401 tanpa sesi,
  502 bila go2rtc tak terjangkau — bukan 500)
- `webrtc`/`mse`/`hls` tetap URL go2rtc langsung; WebRTC nanti butuh 1984 dibuka atau
  di-proxy juga. `GO2RTC_PUBLIC_HOST` tetap dipakai untuk ketiga field itu.

### Bukti

- Di klien: 25 tile, gambar pertama `640x360 host=192.168.2.133:5173`, rata-rata kecerahan 106
  (bukan frame hitam). Satu kamera go2rtc 502 → tile-nya otomatis jadi OFFLINE
  (`tileOffline=1`), 24 lainnya render — degradasi rapi, bukan gagal total
- `curl` di server: `/snapshot` tanpa login → **401**, dengan login → **200 image/jpeg 44623 bytes**
- `pytest backend/tests` **203 passed** (+2) · `pytest vision/tests` **79 passed, 2 skipped** ·
  `npx vitest run` **37 passed** · `npm run build` sukses

## [0.5.3] — 2026-09-15 · Responsif: nol overflow horizontal di 390px

Audit 9 halaman di viewport 390px menemukan 4 halaman bisa di-scroll ke samping.
Semua diperbaiki; sekarang 9/9 `docOverflow=0`, termasuk `window.scrollX` setelah
`scrollTo(500,0)` — bukan cuma angka `scrollWidth`.

| Halaman | Sebelum | Sesudah | Penyebab |
|---|---|---|---|
| /events | 132px | **0** | 3 dropdown filter tidak wrap; `<dl>` detail memakai grid `auto 1fr` dengan UUID tanpa titik putus; grid master-detail menyusutkan panel detail ke ~30px tapi isinya (thumbnail 72px, `<video>`) punya `min-width:auto` |
| /attendance | 115px | **0** | baris tab + tombol Import/Export tidak wrap |
| /config/gates | 23px | **0** | overflow tabel tembus ke halaman walau `.cds--data-table-content` sudah `overflow-x:auto` |
| /live | 0 (tapi chip menimpa judul) | **0** | `.app-page__head` flex tanpa wrap, anak pertama `flex:1` boleh menyusut sampai 0 |
| 4 lainnya | 0 | 0 | — |

### Perbaikan

- `a0ab278` fix(ui): `.app-page__head` `flex-wrap` + basis 280px — aksi turun ke baris
  sendiri di layar sempit, tidak menimpa judul. Kena /live, /events, /enrollment, /config/cameras
- `f30dfa9` fix(ui): filter /events wrap (basis 200px / maks 240px) + baris tab /attendance wrap
- `ce081ee` fix(ui): `overflow-wrap:anywhere` pada `<dl>` detail event — min-content kolom
  `1fr` jadi satu karakter, tidak lagi selebar UUID
- `15505a4` fix(ui): scroller di `.cds--data-table-container` — diverifikasi dengan uji
  sembunyikan-elemen di browser (menyembunyikan container → overflow 0; menambah
  `overflow:hidden` di wrapper dalam tetap 23)
- `2e5abf4` fix(ui): `/events` ditumpuk satu kolom di bawah 900px; desktop tetap master-detail

### Bukti

- Pengukuran per halaman di 390px: `/dashboard /live /events /attendance /enrollment
  /config/cameras /config/zones /config/gates` → semua `overflow=0 scrollX=0`
- Screenshot mobile + desktop: `docs/evidence/ui-polish/after/`
- `pytest backend/tests` **201 passed** · `pytest vision/tests` **79 passed, 2 skipped**
- `npx vitest run` **37 passed** · `npm run build` sukses · `npx oxlint` 0 error

## [0.5.2] — 2026-09-15 · Penutup polish + bug live view LAN

Menutup dua elemen mockup yang belum dikerjakan, plus satu bug nyata yang
membuat Live View mati untuk semua klien LAN.

### Perbaikan

- `fd42e31` fix(backend): host go2rtc untuk browser tidak lagi diturunkan dari header
  `Host`. Proxy Vite dev mengirim `Host: localhost:8000` ke API → klien menerima
  `http://localhost:1984/api/frame.jpeg`, yaitu mesin klien sendiri. Live View mati
  total di luar server. Setting baru `GO2RTC_PUBLIC_HOST` (kosong = perilaku lama).
  Fix `9fcfbee` sebelumnya mengganti host ke host request, tapi sumbernya sudah rusak.
- `4413a7e` chore(.gitignore): `.env` tidak mengabaikan `.env.bak.*` / `.env.local`

### Fitur (elemen mockup yang tersisa)

- `9ca496c` feat(ui): Live View — chip "3/2/4 kolom" + filter "Semua lokasi" (mockup 02),
  pilihan kolom persist; dipaksa turun di layar sempit (≤1055px → 2, ≤671px → 1).
  Grid disamakan mockup: gap 1px di atas `#393939` + border luar.
- `9ca496c` feat(ui): /config/zones — daftar zona di bawah editor dengan swatch tipe,
  badge tipe + AKTIF/NONAKTIF, klik baris = pilih zona (mockup 06).

### Bukti

- `curl` lewat proxy Vite (jalur browser) sebelum/sesudah:
  `"snapshot":"http://localhost:1984/..."` → `"snapshot":"http://192.168.2.133:1984/..."`
- `pytest backend/tests` **201 passed** · `pytest vision/tests` **79 passed, 2 skipped**
- `npx vitest run` **37 passed** · `npm run build` sukses · `npx oxlint` 0 error
- Screenshot Live View (toolbar kolom + grid 3 kolom): `docs/evidence/ui-polish/after/`

### Keamanan (temuan sesi ini, sudah ditindak)

- PAT GitHub tersimpan plaintext di `.git/config` (remote URL) → sudah dicabut dari URL;
  autentikasi lewat Git Credential Manager. **Token-nya sendiri masih perlu di-revoke user.**
- `temp/data/` (gitignored, tidak pernah masuk history) berisi PAT, kredensial kamera uji,
  dan catatan login SSH plaintext → dipindahkan ke `~/.isentinel/secrets/` di luar pohon proyek.
- Tidak ada rahasia di file ter-track maupun di git history (diverifikasi `git grep` +
  `git log -S`). `.env` server mode 600.

## [0.5.1] — 2026-09-15 · UI/UX Polish

Semua 9 halaman dibuat proper terhadap mockup 01–06. Murni frontend — tidak ada perubahan
perilaku backend. Tiga bug fondasi yang sejak Fase 0 membuat tiap halaman salah tampil
diperbaiki di akarnya (offset konten, token tema, pemuatan font).

### Perbaikan

- `6c6545f` fix(ui): konten tertimpa sidebar fixed di semua halaman; sidebar rail collapse 48px
  (ikon saja, tanpa hover-expand, persist localStorage); markup `<ul>` valid; IBM Plex Sans akhirnya
  termuat; layout halaman diseragamkan (`.app-page`)
- `f9b4f9e` fix(ui): token g100 di-emit Carbon, bukan 31 token tulis-tangan — select "Arah" di
  /config/gates tidak lagi berlatar putih dengan teks putih
- `e2fe1d2` fix(ui): state no-signal untuk tile live view (ikon + OFFLINE + timestamp + badge
  LIVE/OFFLINE) dan fallback snapshot editor zona (tidak ada lagi ikon gambar rusak)
- `40b9548` fix(ui): brand header tidak lagi pecah dua baris di viewport < 480px
- `b5df1c9` fix(ui): /events, /live, /dashboard menampilkan error saat request gagal, bukan empty
  state yang menyesatkan; CamerasPage disamakan memakai `lowContrast`

### Bukti

- Screenshot sebelum/sesudah 9 halaman + rail/mobile/EN: `docs/evidence/ui-polish/`
- `npx vitest run` 36 passed · `npm run build` sukses · `pytest backend/tests` 199 passed ·
  `pytest vision/tests` 79 passed, 2 skipped · `npx oxlint` 0 error

## [Unreleased]

### R5a — Detection & Model

- Task 5: Live View debugger menerima payload deteksi `kind` (`person`/`face`) dan `label`; toggle menjadi **Tampilkan deteksi**, dengan bbox person oranye dan wajah biru.
- Task 6: `detector_setting` singleton dan API admin menyimpan override global FPS/confidence/motion; `config_push` mendahulukan DB daripada `.env` dan menerbitkan ulang konfigurasi node.

- `9fcfbee` fix: live endpoint rewrites go2rtc host to request host
- `3ec0d3a` feat: zone editor (click-to-draw polygon) + events master-detail inbox
- feat: loitering analyzer (dwell per zone)
- feat: running analyzer (calibrated m/s)
- feat: alert model + zone analyzer params + camera calibration
- feat: alerting service (rate-limit, telegram foundation)
- feat: alerts api + inbox badge + telegram status chip
- fix: ws guard drops alert frames by kind
- feat: attendance + enrollment + gates UI (AttendancePage tabs/summary/override, EnrollmentPage face gallery+shifts, GatesPage absensi zones + conflict; api/attendance.ts + api/employees.ts)
- fix: api client keeps FormData content-type (multipart CSV import + face upload)
- feat: gate crop from mainstream frame (face resolution) — `Recorder.fetch_frame` fetches `/api/frame.jpeg?src=cam_N_main`, `CameraWorker._attach_crop` crops attendance face from the full-res main stream with substream fallback

## [0.1.0] — 2026-09-10 · Fase 0: Skeleton

Backend, frontend, dan infrastruktur dasar I-Sentinel: auth, kamera + probe RTSP, UI shell Carbon dark, deploy configs. Terverifikasi end-to-end di server dev (login → wizard probe kamera nyata → kamera online).

### Commits

- `14e1294` chore: gitignore tensorrt engine artifacts
- `6e7a885` docs: sinkronkan checklist fase 0 + revisi kriteria fase 1
- `b72b592` docs: fase 1 detail plan (9 task)
- `12c8eca` docs: detektor dipilih YOLO26s nms=False (benchmark task tetap di fase 1)
- `d315f4e` docs: fase 0 selesai - bukti bring-up server
- `cbcec9b` fix: probe returns path without credentials (zero-secret)
- `94b95c9` fix: explicit setuptools packages (flat-layout ambiguity app+alembic)
- `1bd50bb` docs: fase 0 progress checkpoint di roadmap
- `8b7ebf4` fix: final review wave (logout endpoint, probe persistence, nav route, cookie_secure, jwt guard)
- `7af1f41` fix: alembic run path in bootstrap + soft env file in unit
- `c4a2e95` chore: deploy configs (go2rtc, mosquitto, systemd) + bootstrap script
- `05d3750` feat: cameras page with probe wizard
- `3699c88` fix: logout redirect, route-aware placeholder, api client opt merge
- `6a97216` feat: frontend scaffold (carbon g100, i18n id/en, app shell, login)
- `53e10e9` feat: rtsp probe service (ffprobe + vendor path candidates)
- `866bc87` feat: nodes + cameras CRUD API
- `35fb4e9` fix: user API validation (password length, role enum) + bootstrap cleanup
- `d7157a0` feat: auth API + user management + first-run admin bootstrap
- `27602c0` feat: password hashing + JWT auth helpers
- `51bf9f5` feat: fase0 models (user, node, camera, setting) + initial migration
- `8d87aa6` feat: backend core (settings, db, alembic, health endpoint)
- `f39cddb` chore: monorepo scaffolding (backend, vision stub, frontend placeholder)
- `4d7bd05` docs: roadmap dengan checkpoint per fase
- `1540e91` docs: master plan + fase 0 detail plan + milestone briefs (fase 1-5, edge)
- `6e4e363` docs: specify face match threshold default
- `f493b95` docs: I-Sentinel design spec + approved UI mockups

### Highlights

- **Backend**: FastAPI + SQLAlchemy 2 + Alembic; JWT httpOnly cookie auth, role admin/viewer; CRUD kamera/nodes; probe RTSP (ffprobe, path vendor Hikvision/Dahua/generic) dengan hasil persist; ingest event internal idempotent-ready.
- **Frontend**: React + TS + @carbon/react theme g100 dark, bilingual ID/EN, sidebar collapsible; login; halaman kamera + wizard probe; tanpa emoji (Carbon icons).
- **Deploy**: systemd units (api/web), go2rtc + mosquitto configs, bootstrap script; zero-secret (kredensial kamera via env, path RTSP saja di DB).
- **Keputusan model AI**: detektor YOLO26s TensorRT FP16 `nms=False` (spec §2.7); benchmark validasi di Fase 1.

## [0.3.0] — 2026-09-15 · Fase 2: Zona, Events, Clips, Web Inbox

Zona digambar di UI → vision-node eksekusi intrusion → event dengan clip mainstream + snapshot diputar di web inbox. 24 kamera NVR terdaftar.

### Commits (ringkas)

- `2bdaf71` feat: zone model + api (polygon validation, schedule)
- `88947ef` feat: mqtt config push (retained per node)
- `e41b8d5`/`c3bda0d` feat: intrusion analyzer + config apply (hot reload)
- `1fc3ed5`/`b20d138` feat: event recorder (clip via go2rtc mp4 + snapshot, blob upload)
- `d4b50c1` feat: blob storage + media streaming api + media topic consumer
- `9fcfbee` fix: live endpoint rewrites go2rtc host to request host
- `3ec0d3a`/`604afa8` feat: zone editor (click-to-draw polygon) + events master-detail inbox
- `0f979a0`/`75b75aa`/`3973e00` fix: config push zone key id, _config_q order, detector model path resolution
- `0a31dd8` fix: blob endpoint accepts node name (vision contract)
- `e03acfa` feat: person_detect events opt-in (debug), zones are the real signal

### Highlights

- **Zona**: model + editor polygon (klik-titik min 3, tutup start-point, drag handle, koordinat norm 0–1) + validasi absensi/direction
- **Config push MQTT retained** per node — hot-reload worker di vision tanpa restart
- **Intrusion analyzer** (ray-casting, jadwal, re-entry) + registry analyzer untuk fitur berikutnya
- **Recorder**: snapshot dari ring JPEG, clip mp4 via go2rtc, upload blob background + retry
- **Media API** auth + traversal guard + range request (video seek)
- **Web inbox** master-detail dengan player clip + snapshot + unduh

## [0.4.0] — 2026-09-15 · Fase 3: Loitering, Running, Alerting Foundation

Analyzer loitering + running (kalibrasi per kamera), alerting foundation: alert model, rate-limit, Telegram graceful-fail. Integrasi chatID menyusul (low priority).

### Commits (ringkas)

- `d0b6f16`/`18fae0f` feat: loitering analyzer (dwell per zone) + zone filter fix
- `9918933`/`8c6b163` feat: running analyzer (calibrated m/s) + anisotropic fix
- `dd9a72b` feat: alert model + zone analyzer params + camera calibration
- `cd353c9` feat: alerting service (rate-limit, telegram foundation)
- `2e05633`/`a69ad96` feat: alerts api + inbox badge + telegram status chip

### Highlights

- **LoiteringAnalyzer**: dwell akumulatif per track di polygon, reset saat keluar/hilang, gap >10s reset
- **RunningAnalyzer**: m/s via meters_per_pixel per kamera (xy anisotropik benar), EMA, cooldown 5s, skip tanpa kalibrasi
- **Alerting**: severity gate, toggle per zona, rate-limit window (camera:zone:type), retry 3×, status sent|failed|rate_limited|not_configured
- **Telegram**: sendMessage foundation, token env-only, tanpa token/chat → not_configured tanpa network call
- **UI**: badge status alert di event detail, chip status Telegram di inbox header

## [0.5.0] — 2026-09-15 · Fase 4: Absensi Wajah

Siklus absensi penuh: enrollment wajah → gate attendance → rekap dengan shift & status → export/import CSV. InsightFace buffalo_l di server, vision hanya crop.

### Commits (ringkas)

- `8acd420`/`c2aa341` feat+fix: attendance domain models (employee, shift, embedding, attendance) + FK guards + index parity
- `acd68e3` feat: face service (insightface wrapper, gallery, cosine match)
- `8892af4`/`092a6fb` feat+fix: face enrollment api (min 3 pose, pdp purge, gallery wiring) + upload cap
- `f3dc67a`/`1f4b1ec` feat+fix: face gate analyzer (crop + upload) + visit semantics
- `e2ef747`/`fe9dc99` feat+fix: attendance logic (match, aggregate, override, csv, close-days)
- `79532e2`/`ded189e` feat+fix: attendance + enrollment + gates UI + admin gating
- `41695a1` feat: gate crop from mainstream frame (face resolution)

### Highlights

- **Face pipeline server-side**: SCRFD+ArcFace, gallery <100 in-memory cosine, threshold knob; tanpa model → `not_configured` graceful
- **Enrollment**: upload image min 3 pose, quality gate, max 5; hapus biometrik per karyawan (PDP)
- **Attendance**: zona absensi + arah; agregasi harian ontime/late/waiting/no_exit/absent; close-days; override admin dengan catatan audit
- **CSV**: export (tanpa biometrik, anti-injection) + import upsert idempotent
- **Vision**: face_gate crop dari MAINSTREAM (resolusi wajah) + upload blob; error isolation

[Unreleased]: https://github.com/LyKhan77/I-Sentinel/compare/v0.7.0...HEAD
[0.5.5]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.4...v0.5.5
[0.5.4]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.3...v0.5.4
[0.5.3]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/LyKhan77/I-Sentinel/commits/v0.1.0
