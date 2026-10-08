# Face ID pada intrusion critical Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Setelah alert Telegram intrusion `critical` terkirim, caption diedit dengan identitas orang (dikenali / wajah tidak dikenali / wajah tidak terlihat jelas / tidak terverifikasi) tanpa menunda atau menyupresi alert, dan menyimpan crop wajah terbaik sebagai bukti untuk pemeriksaan manual.

**Architecture:** `CameraWorker` mengisi `IntrusionRegistry` dengan person track di zona critical ber-`face_id` dan mengikatnya ke `event_id` saat event intrusion terbit. `FaceGateWorker` (sudah ada di kamera 363) memakai hasil SCRFD yang sama untuk memetakan wajah ke bbox person, mengumpulkan embedding dan kandidat crop terbaik (diunggah ke `crops/`), lalu mengirim satu pesan `isentinel/events/face`. API mencocokkan dengan ambang ketat, menyimpan `payload.face`, dan mengedit caption Telegram (seluruh caption: baris AI + identitas). Fallback `unverified` bila pesan tak datang.

**Tech Stack:** Python ≥3.11, NumPy, paho-mqtt (vision); FastAPI, SQLAlchemy 2.0, Alembic, pytest (backend); React 19, TypeScript, Carbon, Vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-10-08-intrusion-face-id-design.md`. Baca spec dulu; plan ini mengacunya per bagian (§).

## Global Constraints

- Branch `feat/intrusion-face-id` dari `main` @ `7e5d39c`. Commit Conventional Commits per task, **tanpa atribusi AI** (AGENTS.md §9). Jangan `push`.
- Tanpa `uv sync`/`uv lock`/membuat ulang venv. Suite dijalankan **berurutan**, tidak bersamaan. Keluaran mentah ke `temp/logs/intrusion-face-id/` (bukan `temp/prompt/`).
- Vision tetap importable tanpa CUDA; `gate_code` dan `FaceSettings` tidak diubah. Hitungan penolakan identitas terpisah dari `_funnel` attendance (tes lama `test_face_worker.py:446-456` tidak boleh berubah).
- Argumen baru pada `CameraWorker`/`FaceGateWorker` hanya keyword opsional trailing (dipakai di 10+ tempat tes).
- Backend: SQL hanya di service, setelan hanya lewat `Settings`, DB dan WS tidak pernah memuat embedding. Frontend: string lewat `i18n.tsx` di kedua kamus (`id`, `en`), komponen Carbon.
- Nilai awal (spec §8): `REGISTRY_TTL_S = 3.0`, `HEAD_FRAC = 0.40`, `HEAD_PAD = 0.10`, `IDENT_WINDOW_S = 8.0`, `MAX_PITCH = 0.30`, `IDENT_MIN_QUALITY = 0.5`, `MIN_CROP_SCORE = 0.5`, `face_id_threshold = 0.50`, `face_id_margin = 0.10`, `UNVERIFIED_AFTER_S = 15.0`.
- Path crop disimpan di `payload.crop_path` (kunci yang sama dengan attendance); retensi crop intrusion memakai cutoff `snapshot_days`; crop tidak dikirim ke Telegram. Parameter pengenalan tidak dilonggarkan untuk kondisi gelap (spec §1, §9).
- Topik MQTT `isentinel/events/face`, QoS1. Migrasi terbaru sekarang `0022`; yang baru `0023`.
- Baseline (main, 2026-10-08): backend `904 passed, 1 deselected`; vitest `36 files / 487 passed`; build exit 0; lint 24 warning (16 pasangan file-rule); docker `76 passed`; vision `273 passed, 3 deselected`.

## Review Focus

1. Orang masuk zona critical, wajah tak pernah terlihat: event dan alert tetap, caption jadi `not_visible` (T1 kolektor, T6 pemetaan).
2. Dua orang berdekatan di zona: wajah dipetakan ke bbox terdekat, tidak tertukar (T1 `associate`).
3. Pesan susulan duplikat, event tak dikenal, atau tiba setelah `unverified` (T6).
4. Edit caption bersamaan dari worker AI dan identitas tidak saling menimpa (T5).
5. Saklar mati / zona bukan critical / kamera tanpa worker wajah: perilaku lama tidak berubah, SCRFD tidak jalan ekstra (T2, T3).
6. Embedding tidak pernah ada di DB maupun frame WS (T6).
7. Wajah terlihat tetapi di bawah gerbang kualitas: status `not_visible` dan crop kandidat terbaik tetap tersimpan untuk pemeriksaan manual; unggah crop gagal tidak menahan pesan (T1, T2, T6).
8. Crop intrusion tidak dihapus sebagai "orphan" oleh sapuan retensi dan kedaluwarsa mengikuti `snapshot_days`; perilaku attendance tidak berubah (T7).

## Struktur berkas

| Berkas | Tugas |
|---|---|
| `vision/vision/intrusion_face.py` (baru) | registry, `associate`, `pitch_dev`, `IdentCollector` (T1) |
| `vision/vision/node.py`, `face_worker.py`, `transport/mqtt.py` | kabel worker, `publish_face`, `identity_zones` (T2, T3) |
| `backend/app/services/face.py`, `core/config.py`, `docker/compose.yml` | `top2`, `match_strict`, setelan (T4) |
| `backend/alembic/versions/0023_alert_face_synced.py`, `models/alert.py`, `services/telegram.py`, `alert_ai.py`, `alert_dispatcher.py` | caption identitas dan sync (T5) |
| `backend/app/schemas/intrusion_face.py`, `services/intrusion_face.py` (baru), `events_consumer.py`, `schemas/zone.py` | pesan susulan, `crop_path`, `unverified` (T6) |
| `backend/app/services/retention.py` | retensi crop intrusion (T7) |
| `frontend/src/api/zones.ts`, `features/config/ZonesPage.tsx`, `features/events/EventsPage.tsx`, `app/i18n.tsx` | toggle, baris identitas, tab Crop (T8) |
| `ARCHITECTURE.md`, `WORKFLOW.md`, `ROADMAP.md`, `CHANGELOG.md`, `docs/runbooks/intrusion-face-id.md`, `README.md` | dokumen (T9) |

## Tugas 0 (sesi perencanaan bersama user, BUKAN untuk executor): pengukuran kelayakan

**SELESAI 2026-10-08** (dua probe pada kamera 363, `temp/logs/intrusion-face-id/probe.md`): 0 frame lolos gerbang penuh; user memutuskan **lanjut apa adanya** dengan crop wajah sebagai bukti manual (spec §9). Langkah di bawah dicatat sebagai riwayat dan tidak dikerjakan executor; skrip dapat diulang dengan `--camera <id>` untuk kamera lain.

- [ ] Tulis `temp/scripts/intrusion_face_probe.py` (tidak di-commit): terima `--url` dan `--seconds`; baca frame lewat `vision.pipeline.source.FrameSource` dari main-stream kamera 363; per frame jalankan `FaceEmbedder.detect_faces`, catat lebar, skor, `yaw_ratio`, pitch (rumus spec §5.2), dan blur; cetak CSV. URL main-stream = `main_stream_url(<source_url kamera 363>)` (`vision/vision/node.py:46-49`; `source_url` dibaca dari konfigurasi, jangan mencetak kredensial).
- [ ] Setelah persetujuan user: jalankan di container `vision` selama ±3 menit sementara user dan rekan melintas di area zona 15 (menghadap, menyamping, dari belakang, cepat); catat waktu tiap lintasan.
- [ ] Hitung persen lintasan menghadap kamera yang punya ≥1 frame lolos gerbang intrusion. Tulis hasil dan keputusan go/no-go (usulan: ≥80%, user menetapkan) ke `temp/logs/intrusion-face-id/probe.md`. No-go berarti berhenti dan bahas geometri kamera.

## Preflight (executor, sekali)

- [ ] Dari `backend/`: `rtk pytest tests -q -m "not gpu"`; dari `vision/`: `rtk pytest tests -q -m "not gpu"`; dari `frontend/`: `npx vitest run`, `npm run build`, `npm run lint`; dari root: `rtk pytest docker/tests -q`. Simpan keluaran ke `temp/logs/intrusion-face-id/preflight-*.txt`. Harus sama dengan baseline di atas; bila beda, berhenti dan laporkan.

---

### Task 1: Modul `intrusion_face` (registry, asosiasi, pitch, kolektor)

**Files:**
- Create: `vision/vision/intrusion_face.py`
- Test: `vision/tests/test_intrusion_face.py`

**Interfaces:**
- Consumes: `vision.face_quality` (`FaceSettings`, `gate_code`, `yaw_ratio`, `blur_score`, `quality`, `aggregate`), `vision.face.FaceDet`, `vision.analyzers.base.point_in_polygon`.
- Produces (konstanta di §Global Constraints, ditambah):
  - `@dataclass PersonEntry(zone_id: int, track_id: int, bbox: tuple[float, float, float, float], seen_ts: float, event_id: str | None = None, bound_ts: float | None = None)`.
  - `IntrusionRegistry` (thread-safe, `threading.Lock`): `touch(zone_id, track_id, bbox, ts) -> None`; `bind(zone_id, track_id, event_id, ts) -> None` (membuat entri bila belum ada); `entries() -> list[PersonEntry]` (salinan); `active(now: float) -> bool` (ada entri dengan `now - seen_ts <= REGISTRY_TTL_S`); `prune(now) -> None` (buang entri **belum terikat** yang basi); `release(zone_id, track_id) -> None`.
  - `associate(face_center: tuple[float, float], entries: list[PersonEntry]) -> PersonEntry | None` (spec §5.2: area kepala = `HEAD_FRAC` atas bbox, diperlebar `HEAD_PAD` ke kiri/kanan/atas; pilih pusat kepala terdekat).
  - `pitch_dev(kps: np.ndarray) -> float` = `abs((nose_y − eye_y) / (mouth_y − eye_y) − 0.5)` dengan `eye_y`/`mouth_y` rata-rata dua titik; penyebut ≤ 0 mengembalikan `1.0`.
  - `jpeg_crop(frame: np.ndarray, box: tuple[int, int, int, int]) -> bytes | None` (JPEG kualitas 90 dari region `box`; `cv2` diimpor di dalam fungsi; `None` bila encode gagal).
  - `IdentCollector(registry, face, settings: FaceSettings, camera_id: int, node_id: str, encode=jpeg_crop)` dengan `observe(faces: list[FaceDet], frame_data, frame_w: int, frame_h: int, now: float) -> None` dan `drain(now: float) -> list[dict]`.
  - Pesan dari `drain`: `{"event_id", "camera_id", "node_id", "track_id", "embedding": list[float] | None, "quality": float | None, "crop_path": None, "stats": {"faces": int, "rejects": {"small", "score", "yaw", "pitch", "blur", "quality"}, "frames_used": int}, "_crop": bytes | None}`. `_crop` adalah kunci privat (JPEG kandidat terbaik) yang **harus di-`pop` oleh pemanggil** sebelum publikasi; `crop_path` diisi pemanggil setelah unggah (Task 2).

Aturan `observe`: untuk tiap wajah, pusat dinormalisasi lalu `associate` ke entri segar; tanpa entri, wajah diabaikan. Hitung `stats.faces`; tolak berurutan: `gate_code` dengan `zones=[{"id": zone_id, "polygon": [[0,0],[1,0],[1,1],[0,1]]}]` (cek poligon selalu lolos; kodenya `small`/`score`/`yaw`), blur (`align` lalu `blur_score < settings.blur_min`), `pitch_dev > MAX_PITCH` (`pitch`), `quality(score, lebar_px, yaw_ratio) < IDENT_MIN_QUALITY` (`quality`). Wajah lolos di-`embed` dan disimpan (vektor, bobot = kualitas). Aturan `drain` per entri **terikat**: siap bila `len(vektor) >= settings.min_frames`, atau `now - bound_ts >= IDENT_WINDOW_S`, atau `now - seen_ts > REGISTRY_TTL_S` (orang hilang). Pesan siap dibangun (`embedding = aggregate(...)` atau `None`, `quality` = maksimum), entri dan state-nya dilepas. Entri belum terikat yang basi dibuang tanpa pesan (lewat `prune`).

Kandidat crop (spec §5.2): untuk **setiap** wajah terasosiasi dengan `score >= MIN_CROP_SCORE`, apa pun hasil gerbang di atas, hitung peringkat `lebar_px * score`; hanya bila lebih baik dari kandidat sebelumnya entri itu, panggil `encode(frame_data, crop_box(bbox, frame_w, frame_h))` dan simpan hasilnya (satu kandidat per kunci). `drain` menyertakan kandidat itu sebagai `_crop` (None bila tidak ada).

- [ ] **Step 1: Tes gagal** di `vision/tests/test_intrusion_face.py` (fake `FaceDet`/engine meniru `test_face_worker.py:15-60`; `FRONTAL = [[40,60],[80,60],[60,85],[45,110],[75,110]]`):
  - `test_registry_fresh_within_ttl_then_expires`: `touch` pada ts 10.0 → `active(12.9)` True, `active(13.1)` False.
  - `test_registry_bind_creates_missing_entry_and_prune_keeps_bound`: `bind` entri baru → `entries()` berisi `event_id`; `prune(99.0)` membuang entri belum terikat basi tetapi mempertahankan yang terikat.
  - `test_associate_picks_nearest_head_with_two_overlapping_people`: bbox A `(0.20,0.20,0.40,0.90)`, B `(0.35,0.25,0.55,0.95)`; pusat wajah di kepala A → A, di kepala B → B.
  - `test_associate_none_for_face_below_head_region`: pusat wajah di torso → `None`.
  - `test_pitch_dev_frontal_zero_and_looking_down_positive_and_degenerate`: `FRONTAL` → `0.0`; hidung di y=100 → `0.3` (±1e-6); mulut di atas mata → `>= 1.0`.
  - `test_collector_emits_after_min_frames_with_embedding_and_releases_entry`: 3 frame lolos pada entri terikat → `drain` 1 pesan (`embedding` tidak None, `frames_used == 3`, `stats.faces == 3`), `entries()` kosong sesudahnya.
  - `test_collector_waits_for_bind_before_emitting`: 3 frame lolos, belum terikat → `drain` kosong; setelah `bind` → 1 pesan.
  - `test_collector_window_expiry_emits_null_embedding_with_reject_counts`: terikat, wajah selalu `small` → `drain(bound_ts + IDENT_WINDOW_S)` memberi `embedding is None`, `stats.rejects.small >= 1`, `frames_used == 0`.
  - `test_collector_person_gone_after_bind_emits_partial` dan `test_collector_unbound_gone_entry_dropped_without_message`.
  - `test_collector_rejects_by_pitch_and_by_quality`: wajah dengan hidung turun → `rejects.pitch`; wajah dengan skor 0.62, lebar 80 px, yaw 0.3 → `rejects.quality`.
  - `test_collector_ignores_face_outside_any_head_region`: tidak ada penghitungan `faces`.
  - `test_collector_keeps_best_associated_face_crop_even_when_gate_rejects`: `encode` palsu mencatat box dan mengembalikan `b"jpg-<lebar>"`; tiga wajah `small` (lebar 40, 70, 60, skor 0.8) → pesan memuat `_crop == b"jpg-70"` dan `encode` dipanggil dua kali saja (40 lalu 70; 60 tidak lebih baik).
  - `test_collector_no_crop_when_score_below_min_crop_score_or_not_associated`: skor 0.4 dan wajah di luar area kepala → `_crop is None`, `encode` tidak dipanggil.
- [ ] **Step 2:** `cd vision && rtk pytest tests/test_intrusion_face.py -q` → FAIL (`ModuleNotFoundError: vision.intrusion_face`).
- [ ] **Step 3:** Implementasikan modul sesuai Interfaces; murni dan tanpa import CUDA.
- [ ] **Step 4:** `rtk pytest tests/test_intrusion_face.py -q` → semua PASS. Mutasi sementara (`HEAD_FRAC` → 1.0 membuat tes torso merah; `>= IDENT_WINDOW_S` → `>` membuat tes jendela merah), lalu kembalikan.
- [ ] **Step 5:** `git add vision/vision/intrusion_face.py vision/tests/test_intrusion_face.py && git commit -m "feat(vision): registry person dan kolektor identitas untuk intrusion critical"`

### Task 2: Kabel worker dan transport

**Files:**
- Modify: `vision/vision/node.py:99-198` (`CameraWorker`), `vision/vision/face_worker.py:62-128,153-192` (`FaceGateWorker`), `vision/vision/transport/mqtt.py:14-15,78-82`
- Test: `vision/tests/test_intrusion_face_workers.py` (baru), `vision/tests/test_transport.py`

**Interfaces:**
- Consumes: `IntrusionRegistry`, `IdentCollector` (Task 1); `analyzers.base.ground_point`, `point_in_polygon`.
- Produces:
  - `FACE_TOPIC = "isentinel/events/face"` dan `MqttTransport.publish_face(self, payload: dict) -> None` (→ `_publish(FACE_TOPIC, payload)`, antrean disk seperti event).
  - `CameraWorker(..., registry: IntrusionRegistry | None = None, ident_zones: list[dict] = ())`.
  - `FaceGateWorker(..., registry: IntrusionRegistry | None = None)`.

Perilaku: `CameraWorker.run`, setelah `tracks = tracker.update(...)` (`node.py:152`) dan sebelum analyzer dipanggil: untuk tiap zona di `ident_zones` dan tiap track dengan `misses == 0` yang titik kakinya (`ground_point`) dalam polygon: `registry.touch(zone["id"], tr.id, tr.bbox, frame.ts)`. Setelah `_merge_event` (`node.py:187`), bila `ev["type"] == "intrusion"` dan `ev["zone_id"]` ada di `ident_zones`: `registry.bind(ev["zone_id"], ev["payload"]["track_id"], ev["event_id"], frame.ts)`. `FaceGateWorker`: bila `registry` ada, buat `IdentCollector(registry, face, settings, camera_id, node_id)`; klausa bypass `face_worker.py:115` menjadi `if not moving and not self._faces_shown and not (registry and registry.active(frame.ts))`; di `_process`, setelah `faces = self.face.detect_faces(...)` panggil `collector.observe(faces, frame.data, w, h, frame.ts)`; di akhir tiap iterasi `run` (termasuk jalur idle dan motion-skip) panggil `registry.prune(now)` lalu `transport.publish_face(msg)` untuk tiap `collector.drain(now)` (`now = frame.ts`, atau `time.monotonic()` di jalur idle). Tanpa `registry`, jalur kode identik dengan sekarang.

Pengiriman pesan susulan: tiap pesan dari `drain` ditangani thread daemon pendek `ident-ship-<camera_id>` (loop frame tidak menunggu): `crop = msg.pop("_crop", None)`; bila `crop` dan `recorder` ada, `msg["crop_path"] = recorder.upload_bytes(crop, "crop", timeout=3.0, retries=1)` (gagal atau tanpa recorder = `None`); lalu `transport.publish_face(msg)`. Worker menyimpan thread-nya dan men-`join` yang belum selesai (maks 5 dtk total) di `finally` akhir `run`.

- [ ] **Step 1: Tes gagal**:
  - `test_face_worker_bypasses_motion_gate_while_registry_active`: salin pola `test_face_worker.py:423-431` (frame nol, `motion={"enabled": True, "force_interval_s": 10}`); tanpa registry `motion_skipped == 5`; dengan registry berisi entri segar `motion_skipped == 0`.
  - `test_face_worker_publishes_one_face_result_after_bind`: registry berisi entri terikat `event_id="ev-1"`, 3 frame dengan wajah di kepala entri → `transport.faces` berisi satu pesan `event_id == "ev-1"`, `embedding is not None`; `FakeTransport` lokal punya `publish_face`.
  - `test_face_worker_without_registry_never_needs_publish_face`: `FakeTransport` tanpa `publish_face` (seperti `test_face_worker.py:54-62`), jalankan `run_worker` biasa → tanpa `AttributeError`, event attendance sama seperti sebelumnya.
  - `test_camera_worker_touches_ident_zone_tracks_and_binds_on_intrusion_event`: detector palsu (gaya `tests/test_node.py:119`) mengembalikan satu person di dalam polygon persegi dengan `trigger_seconds: 0` → entri registry terikat ke `event_id` event intrusion yang dipublikasikan; `test_camera_worker_ignores_tracks_outside_ident_zone`: registry kosong.
  - `test_publish_face_uses_face_topic_qos1_and_queues_when_disconnected` di `test_transport.py` (gaya tes `publish_event`/`publish_media` yang ada).
  - `test_face_worker_uploads_crop_and_publishes_crop_path` (recorder palsu: `upload_bytes(data, kind, ...)` mencatat `kind == "crop"` dan mengembalikan `"crops/2026/10/08/x.jpg"`; pesan yang dipublikasikan berisi `crop_path` itu dan tidak memuat kunci `_crop`), `test_face_worker_publishes_even_when_crop_upload_fails` (upload mengembalikan `None` → pesan terkirim dengan `crop_path is None`), dan `test_face_worker_without_recorder_publishes_crop_path_none`.
- [ ] **Step 2:** `rtk pytest tests/test_intrusion_face_workers.py tests/test_transport.py -q` → FAIL.
- [ ] **Step 3:** Implementasikan sesuai Perilaku dan Interfaces.
- [ ] **Step 4:** Tes baru PASS; lalu `rtk pytest tests -q -m "not gpu"` (vision) → `273 + tes baru passed, 3 deselected`, tanpa perubahan pada tes lama.
- [ ] **Step 5:** `git add vision && git commit -m "feat(vision): worker mengisi registry person dan mengirim hasil wajah intrusion"`

### Task 3: `identity_zones` dan `_start_camera`

**Files:**
- Modify: `vision/vision/node.py:205-209` (di samping `attendance_zones`), `:447-480` (`_start_camera`)
- Test: `vision/tests/test_node_intrusion_face.py` (baru, gaya `test_config_apply_per_camera.py:12-120`)

**Interfaces:**
- Consumes: Task 1, Task 2.
- Produces: `identity_zones(cam: CameraCfg) -> list[dict]`: zona dengan `severity == "critical"` yang `behaviors_of(z)` memuat behavior `kind == "intrusion"` dengan `face_id is True`.

Perilaku `_start_camera`: `ident = identity_zones(cam) if self.face is not None else []`. Bila `ident` ada tetapi `gates` kosong: `logger.warning` sekali dan `ident = []`. Bila `ident` ada: `registry = IntrusionRegistry()` dibagi ke `CameraWorker(registry=registry, ident_zones=ident)` dan `FaceGateWorker(registry=registry)`. Tanpa `ident`: kedua worker dibuat persis seperti sekarang.

- [ ] **Step 1: Tes gagal**: `test_identity_zones_requires_critical_intrusion_with_face_id_true` (parametrize: severity `warning`, `face_id` absen/`False`/`"true"`, behavior `loitering` → kosong); `test_start_camera_shares_one_registry_between_detect_and_face_workers`; `test_start_camera_without_face_id_creates_no_registry`; `test_start_camera_face_id_without_attendance_zone_warns_and_skips` (`caplog` berisi peringatan, tanpa registry); `test_face_id_toggle_restarts_only_that_camera` (dua kamera, ubah `face_id` di satu; lainnya `unchanged`, pola `test_config_apply_per_camera.py:200-220`).
- [ ] **Step 2:** `rtk pytest tests/test_node_intrusion_face.py -q` → FAIL.
- [ ] **Step 3:** Implementasikan.
- [ ] **Step 4:** Tes baru PASS; suite vision penuh hijau.
- [ ] **Step 5:** `git add vision && git commit -m "feat(vision): aktifkan registry identitas per kamera untuk zona critical ber-face_id"`

### Task 4: Pencocokan ketat dan setelan

**Files:**
- Modify: `backend/app/services/face.py:30-35,140-178,191-202`, `backend/app/core/config.py:46-57`, `docker/compose.yml:11-27`
- Test: `backend/tests/test_face_service.py` (fixture autouse `_fresh_gallery`, monkeypatch `settings`), `docker/tests/test_compose.py`

**Interfaces:**
- Produces: `MatchResult` mendapat field `margin: float | None = None` (default; pemanggil lama tak berubah); `FaceGallery.top2(self, vector: list[float]) -> list[tuple[int, float]]` (skor terbaik per karyawan, maksimum dua karyawan berbeda, terbaik dulu); `match_strict(vector: Sequence[float], quality: float | None = None) -> MatchResult` dengan alasan `low_quality` (`quality < settings.face_min_quality`), `no_match` (galeri kosong atau `top1 < face_id_threshold`), `ambiguous` (`top1 − top2 < face_id_margin`; tanpa runner-up dianggap `top2 = 0.0`), `matched`; `Settings.face_id_threshold: float = 0.50`, `Settings.face_id_margin: float = 0.10`; compose: `FACE_ID_THRESHOLD: ${FACE_ID_THRESHOLD:-0.50}` dan `FACE_ID_MARGIN: ${FACE_ID_MARGIN:-0.10}` di anchor `x-api-environment`.

- [ ] **Step 1: Tes gagal**: `test_top2_returns_two_distinct_employees_best_first`; `test_match_strict_matched_returns_employee_score_and_margin`; `test_match_strict_ambiguous_when_two_employees_are_close` (dua karyawan vektor hampir sama → `reason == "ambiguous"`, `employee_id is None`); `test_match_strict_no_match_below_threshold`; `test_match_strict_low_quality_before_matching`; `test_match_strict_single_employee_not_penalised_by_margin`; `test_match_strict_empty_gallery_is_no_match`; di `test_compose.py`: `test_api_and_retention_receive_face_id_thresholds_but_vision_does_not`.
- [ ] **Step 2:** `cd backend && rtk pytest tests/test_face_service.py -q` dan `cd .. && rtk pytest docker/tests/test_compose.py -q` → FAIL.
- [ ] **Step 3:** Implementasikan (satu pass `top2`, mengikuti precedent `find_duplicate` yang membaca `_by_employee`).
- [ ] **Step 4:** Tes PASS; `rtk pytest tests -q -m "not gpu"` (backend) hijau.
- [ ] **Step 5:** `git add backend docker && git commit -m "feat(face): pencocokan ketat top-2 dan setelan ambang identitas intrusion"`

### Task 5: Caption identitas, kolom `face_synced`, sync edit

**Files:**
- Create: `backend/alembic/versions/0023_alert_face_synced.py`
- Modify: `backend/app/models/alert.py:21`, `backend/app/services/telegram.py:229-297`, `alert_ai.py:22-81`, `alert_dispatcher.py:157-185`
- Test: `backend/tests/test_migration_0023.py` (tiru `test_migration_0022.py`), `test_telegram.py`, `test_alert_ai.py`, `test_alert_dispatcher.py`

**Interfaces:**
- Produces: `Alert.face_synced: bool` (`nullable=False`, `server_default=false()`); `alert_ai.sync_face_caption(db: Session, event_id: int) -> bool`; `alert_ai._edit_lock: threading.Lock` (modul); `format_caption` menambah baris `("Identitas", teks)` setelah baris Level bila `event.type == "intrusion"` dan `payload["face"]` dict ber-`status` — teks: `recognized` → `Dikenali: <name>`, `unknown` → `Wajah terlihat, tidak dikenali`, `not_visible` → `Wajah tidak terlihat jelas`, `unverified` → `Identitas tidak terverifikasi`; status asing diabaikan.

`sync_face_caption`: guard sama dengan `sync_ai_caption` (`alert_ai.py:54-62`) **kecuali** syarat teks AI; klaim atomik `UPDATE alert SET face_synced=true WHERE id=? AND face_synced=false` lalu `commit` sebelum I/O; `build_caption(db, alert, ai_text(db, event_id))` (merender AI bila ada dan identitas dari `payload.face`); `_release`-nya mengembalikan `face_synced=false`. Kedua fungsi sync (AI dan wajah) menjalankan klaim + render + `telegram.edit_caption` di dalam `with _edit_lock:` (tanpa menahan transaksi DB). Dispatcher: tepat sebelum `build_caption` (`alert_dispatcher.py:170`) hitung `has_face = bool((event.payload or {}).get("face"))`; setelah kirim: `alert.face_synced = has_face and status == "sent"`; sebelum sync pasca-kirim `db.refresh(event)`, lalu panggil `sync_ai_caption` dan `sync_face_caption`. Alert dengan `message_photo is not True`: `logger.info("identity_skipped_text_only ...")` dan return False (tanpa memanggil Telegram).

- [ ] **Step 1: Tes gagal**: migrasi (kolom ada, baris lama `face_synced == 0`, `NOT NULL`, upgrade-downgrade-upgrade); `test_format_caption_identity_row_for_each_status` (empat teks persis, tidak ada baris untuk tipe `attendance`, nama di-escape HTML, panjang ≤ 1024 UTF-16); `test_sync_face_caption_edits_with_identity_and_ai_lines` (fixture `ready`, `payload.face` recognized, caption memuat keduanya); `test_sync_face_caption_works_without_ai_text`; `test_sync_face_caption_claims_once_and_releases_on_failure`; `test_sync_face_caption_skips_text_only_alert_without_telegram_call` (`caplog` memuat `identity_skipped_text_only`); `test_ai_edit_after_face_edit_renders_both_lines`; `test_concurrent_edits_are_serialised`: dua thread, fake `edit_caption` thread A menahan lewat `threading.Event` → thread B tidak memanggil fake sebelum A dilepas, lalu caption B memuat AI dan identitas, `_edit_lock.locked()` False di akhir; dispatcher: `test_initial_caption_with_face_marks_face_synced_and_skips_second_edit` dan `test_face_written_after_caption_built_is_edited_after_send` (memerlukan `db.refresh(event)`).
- [ ] **Step 2:** `rtk pytest tests/test_migration_0023.py tests/test_telegram.py tests/test_alert_ai.py tests/test_alert_dispatcher.py -q` → FAIL.
- [ ] **Step 3:** Implementasikan sesuai Interfaces. `alembic upgrade head` lokal harus sukses di DB kosong.
- [ ] **Step 4:** Tes PASS (termasuk `not db.in_transaction()` selama I/O Telegram, fixture `test_alert_ai.py:34`); suite backend hijau.
- [ ] **Step 5:** `git add backend && git commit -m "feat(alert): edit caption identitas bersama baris AI dengan klaim face_synced"`

### Task 6: Pesan susulan, `unverified`, saklar zona

**Files:**
- Create: `backend/app/schemas/intrusion_face.py`, `backend/app/services/intrusion_face.py`
- Modify: `backend/app/services/events_consumer.py:19-23,57-89,188-194`, `backend/app/schemas/zone.py:24`
- Test: `backend/tests/test_intrusion_face_api.py` (baru; gaya `test_media.py:98-157`), `test_zones_api.py`, `test_config_push.py`

**Interfaces:**
- Consumes: `face.match_strict` (Task 4), `alert_ai.sync_face_caption` (Task 5), `hub.broadcast`.
- Produces:
  - `FaceResultIn(BaseModel)`: `event_id: str`, `camera_id: int | None`, `node_id: str | None`, `track_id: int | None`, `embedding: list[float] | None`, `quality: float | None`, `crop_path: str | None`, `stats: dict | None`.
  - `UNVERIFIED_AFTER_S: float = 15.0`; `wants_identity(db: Session, ev: Event) -> bool` (`ev.type == "intrusion"`, `ev.severity == "critical"`, zona ada dan `zone.behavior_flag("intrusion", "face_id", default=False)`); `identify(db: Session, data: FaceResultIn) -> dict` (kamus `payload.face`: `status`, `reason`, `employee_id`, `name`, `score`, `margin`; kunci kosong dihilangkan); `handle_face_result(db: Session, data: dict) -> None` (tidak pernah melempar); `schedule_unverified(event_id: str, *, delay: float = UNVERIFIED_AFTER_S, session_factory=SessionLocal) -> threading.Timer` (daemon, sudah `start()`); `finalize_unverified(event_id: str, session_factory=SessionLocal) -> bool`.
  - `FACE_TOPIC = "isentinel/events/face"` di `events_consumer.py`, `(FACE_TOPIC, 1)` di `_subscriptions`.

Aturan `handle_face_result`: `pop("embedding")` **sebelum** validasi/penyimpanan; event tak ditemukan → `logger.warning` dan return; abaikan bila `payload.face` sudah sama (status + `employee_id`); pemetaan: embedding `None` → `not_visible` dengan `reason` = kunci `stats.rejects` terbesar, atau `no_face` bila `stats.faces == 0`; `match_strict` `low_quality` → `not_visible` (`reason: low_quality`); `no_match`/`ambiguous` → `unknown`; `matched` → `recognized` (`name` dari `Employee.name`, fallback `f"karyawan #{id}"`). Simpan `ev.payload = {**(ev.payload or {}), "face": face}` (ditambah `"crop_path": data.crop_path` hanya bila berupa string `crops/...` tanpa `..` dan event belum punya `crop_path`; path lain diabaikan tanpa menggagalkan status), `UPDATE alert SET face_synced=false WHERE event_id=ev.id`, `commit`, broadcast `{"kind": "face", "event_id": ev.id, "status": status}` (bentuk mengikuti frame `kind: "ai"` di `ai_worker.py:103-106`, dibungkus try/except seperti kode yang ada), lalu `sync_face_caption`. `finalize_unverified` tidak melakukan apa pun bila `payload.face` sudah ada. Di cabang EVENTS, setelah langkah `maybe_enqueue_caption`: `if wants_identity(db, ev): schedule_unverified(ev.event_id)` dalam try/except + `db.rollback()` seperti langkah lain.

- [ ] **Step 1: Tes gagal**: `test_consumer_subscribes_face_topic`; `test_face_result_pops_embedding_and_never_persists_or_broadcasts_it` (payload event, frame WS, dan log tidak memuat vektor); `test_face_result_recognized_unknown_ambiguous_not_visible_mapping` (parametrize, termasuk `reason` dominan dari `stats.rejects` dan `no_face`); `test_face_result_unknown_event_does_not_crash`; `test_duplicate_face_result_does_not_edit_twice`; `test_real_result_overrides_unverified_and_resets_face_synced`; `test_face_result_stores_valid_crop_path_and_ignores_unsafe_ones` (parametrize `"../x.jpg"`, `"crops/../x.jpg"`, `"snapshots/a.jpg"`, `"/etc/passwd"`: status tetap tersimpan, `payload.crop_path` tidak ada); `test_face_result_broadcasts_kind_face_frame`; `test_finalize_unverified_sets_status_once_and_noops_when_face_present`; `test_schedule_unverified_only_for_critical_intrusion_with_face_id` (monkeypatch `schedule_unverified`; zona `warning`, saklar mati, tipe lain → tidak dipanggil); `test_zone_api_rejects_non_bool_face_id` (422) di `test_zones_api.py`; `test_config_push_passes_face_id_raw` di `test_config_push.py`.
- [ ] **Step 2:** `rtk pytest tests/test_intrusion_face_api.py tests/test_zones_api.py tests/test_config_push.py -q` → FAIL.
- [ ] **Step 3:** Implementasikan. Tambah `"face_id"` ke tuple flag boolean `schemas/zone.py:24`.
- [ ] **Step 4:** Tes PASS; suite backend penuh hijau.
- [ ] **Step 5:** `git add backend && git commit -m "feat(events): terima hasil wajah intrusion, pencocokan ketat, dan fallback unverified"`

### Task 7: Retensi crop intrusion

**Files:**
- Modify: `backend/app/services/retention.py` (`_expire_crops` ±141-165, daftar `parts` dan `_media_free_after` di `sweep` ±213-226, himpunan `referenced` ±240-245)
- Test: berkas tes retensi yang ada di `backend/tests/` (cari dengan `grep -ln "sweep(" backend/tests`; tiru fixture-nya)

**Interfaces:**
- Consumes: `storage_settings.get(db)` (`snapshot_days`, `attendance_days`), `cutoff_for(now, days)`.
- Produces: `_expire_crops(db, root, cutoff, dry_run, event_type="attendance") -> tuple[int, int, list]` (default menjaga pemanggilan lama). `sweep` memanggilnya juga dengan `event_type="intrusion"` dan `cutoffs["snapshot"]`.

Perilaku: filter `Event.type == event_type`; sisanya sama (hapus file, `payload.crop_path = None`, `media_expired = True`); `_null_attendance_copies` hanya untuk `attendance`. `parts` bertambah satu elemen dan tuple jenis pada `_media_free_after` ditambah satu `"crop"` agar sejajar. Pada himpunan `referenced` filter `Event.type == "attendance"` menjadi `Event.type.in_(("attendance", "intrusion"))` (tanpa ini sapuan orphan menghapus crop intrusion mengikuti `attendance_days` sementara path-nya tertinggal di DB).

- [ ] **Step 1: Tes gagal**: `test_sweep_expires_old_intrusion_crop_with_snapshot_cutoff` (event intrusion lebih tua dari `snapshot_days` dengan `payload.crop_path` dan file → file terhapus, `crop_path` jadi `None`, `media_expired` True; crop attendance seumur itu tetapi lebih muda dari `attendance_days` tetap ada); `test_sweep_does_not_treat_referenced_intrusion_crop_as_orphan` (event intrusion baru, file crop dengan `mtime` lebih tua dari cutoff attendance → file tetap ada); `test_sweep_dry_run_leaves_intrusion_crop_untouched`; tes retensi attendance yang ada tetap hijau tanpa diubah.
- [ ] **Step 2:** `cd backend && rtk pytest <berkas tes retensi> -q` → FAIL (RED yang benar: file crop intrusion terhapus sebagai orphan, atau tidak dihapus saat kedaluwarsa).
- [ ] **Step 3:** Implementasikan sesuai Perilaku.
- [ ] **Step 4:** Tes baru PASS; suite backend penuh hijau.
- [ ] **Step 5:** `git add backend && git commit -m "feat(retention): crop wajah intrusion kedaluwarsa mengikuti snapshot_days dan tidak dianggap orphan"`

### Task 8: Frontend

**Files:**
- Modify: `frontend/src/api/zones.ts:18`, `frontend/src/features/config/ZonesPage.tsx:551`, `frontend/src/features/events/EventsPage.tsx:199-219,653-659`, `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/zones.test.tsx`, `frontend/src/__tests__/events.test.tsx`

**Interfaces:**
- Produces: `Behavior.face_id?: boolean`; `Toggle` `id="zone-face-id-intrusion"` (hanya `kind === 'intrusion'`, `toggled={b.face_id ?? false}`, `onToggle={(v) => setBehavior(kind, { face_id: v })}`) dengan paragraf bantuan `zones.faceIdHint`; baris detail `data-testid="event-identity"` untuk event yang punya `payload.face` (status + nama + skor); tab Crop tampil untuk event apa pun yang punya `payload.crop_path` (filter tab di `EventsPage.tsx` ±566 menjadi `tb.id === 'crop' ? isAttendance || cropPath != null : ...`; kunci i18n `events.tab.crop`/`events.crop`/`events.cropUnavailable` dipakai ulang, perilaku attendance tidak berubah); cabang WS `kind === 'face'` → `refresh('merge')`; kunci i18n (kedua kamus): `zones.faceId`, `zones.faceIdHint`, `events.identity`, `events.identity.recognized` (dengan `{name}`), `events.identity.unknown`, `events.identity.notVisible`, `events.identity.unverified`.

- [ ] **Step 1: Tes gagal**: `zones.test.tsx` (pola `:484-496`): `intrusion face_id toggle defaults off and saves face_id true` (`aria-checked` awal `false`; setelah klik dan simpan, `patchBody(f).behaviors` memuat `face_id: true` pada behavior intrusion) dan `face_id toggle is not rendered for loitering`; `events.test.tsx`: `detail shows identity row for each payload.face status` (empat teks), `no identity row without payload.face`, `ws face frame triggers a refresh` (pola `FakeWS` `:407-448`; jumlah panggilan fetch daftar bertambah), `intrusion event with payload.crop_path shows the crop tab and image` (`event-crop` berisi `<img>` dengan `src` `/api/v1/media/<crop_path>`), dan `intrusion event without crop_path has no crop tab`; tes crop attendance yang ada tetap hijau tanpa diubah.
- [ ] **Step 2:** `cd frontend && npx vitest run src/__tests__/zones.test.tsx src/__tests__/events.test.tsx` → FAIL.
- [ ] **Step 3:** Implementasikan; tanpa CSS baru.
- [ ] **Step 4:** Tes PASS; berurutan: `npx vitest run`, `npm run build`, `npm run lint` (24 warning, pasangan file-rule sama baseline).
- [ ] **Step 5:** `git add frontend && git commit -m "feat(web): toggle face_id zona intrusion dan baris identitas di detail event"`

### Task 9: Dokumen dan verifikasi akhir

**Files:**
- Modify: `ARCHITECTURE.md` (tabel topik `:170-176`, alur vision/API), `WORKFLOW.md`, `ROADMAP.md`, `CHANGELOG.md`, `README.md` (daftar fitur), `docs/runbooks/` — Create: `docs/runbooks/intrusion-face-id.md`

- [ ] **Step 1:** `ARCHITECTURE.md`: baris topik `isentinel/events/face`, ringkasan alur node→API→caption, catatan "kamera critical butuh zona attendance (worker wajah)". `WORKFLOW.md`: alur per fitur (empat hasil identitas, `unverified`). `docs/runbooks/intrusion-face-id.md`: cara menyalakan (zona critical + `face_id`, hanya atas persetujuan untuk menulis ke server), cara membaca hasil di Inbox, prosedur kalibrasi (spec §9; ambang lewat `FACE_ID_THRESHOLD`/`FACE_ID_MARGIN` di `docker/.env` lalu **recreate** `api`), pemecahan masalah `unverified`/`not_visible`, crop wajah sebagai bukti manual dan retensinya (`snapshot_days`), prasyarat GPU container `vision` (spec §11), rollback. `README.md`: satu baris fitur. `ROADMAP.md`: baris `IFI` berstatus `[~]` ("kode selesai, BELUM diuji di server nyata; menunggu Tugas 0 dan uji lapangan").
- [ ] **Step 2:** Jalankan semua suite berurutan dan simpan keluaran ke `temp/logs/intrusion-face-id/final-*.txt`: backend, lalu vision, lalu docker, lalu `npx vitest run`, `npm run build`, `npm run lint`. Angka harus baseline + tes baru; tes lama tidak diubah (`git diff main -- vision/tests/test_face_worker.py backend/tests/test_alert_ai.py` hanya menambah).
- [ ] **Step 3:** `CHANGELOG.md`: satu entri dengan konteks, berkas, bukti (tempel angka dari Step 2), dampak, rollback, dan "BELUM diuji di server". Periksa `.gitignore` (probe di `temp/` sudah diabaikan).
- [ ] **Step 4:** `git add -A docs ARCHITECTURE.md WORKFLOW.md ROADMAP.md CHANGELOG.md README.md && git commit -m "docs: face ID pada intrusion critical (alur, runbook, roadmap, changelog)"`
- [ ] **Step 5:** Tulis `temp/prompt/intrusion-face-id-report.md` (daftar commit, angka suite, penyimpangan dari plan, temuan) lalu berhenti tanpa `push`.
