# Pemusatan Parameter Pengenalan Wajah — Plan Tahap 1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Semua parameter pengenalan wajah yang memengaruhi akurasi dibaca dari satu baris `detector_setting` (DB, bisa diubah di UI) oleh node dan API, tanpa mengubah keputusan absensi.

**Architecture:** Kolom baru di `detector_setting` (migrasi `0024`). API membaca ambang/margin lewat `FacePolicy` (`services/face_policy.py`, fallback ke `Settings`). Node menerima sub-blok `face.ident` yang menjadi `FaceSettings.ident` (`IdentSettings`), sehingga deteksi perubahan config yang sudah ada merestart worker wajah. UI mendapat kartu tiga grup.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, pydantic v2; Python vision node; React 19 + Carbon, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-09-face-params-unify-design.md` (§4 = tahap 1). Tahap 2 (saklar `unified`) mendapat plan terpisah setelah tahap 1 terdeploy.

## Global Constraints

- Nilai awal persis: `face_match_threshold` 0.40, `face_match_margin` 0.15, `face_max_pitch` 0.30, `face_best_k` 5, `face_ident_min_width_px` 60.0, `face_ident_window_s` 8.0.
- Rentang validasi PUT: threshold 0.1–0.99, margin 0–0.5, pitch 0.05–1, K 1–10, lebar identitas 16–1000, jendela 1–15 (harus di bawah `UNVERIFIED_AFTER_S` = 20).
- Tahap 1 tidak mengubah keputusan absensi: suite `backend/tests/test_attendance_*.py` lulus tanpa diubah.
- Baris `detector_setting` id=1 boleh tidak ada: GET, config push, dan pencocokan memakai `Settings` (nilai awal sama dengan di atas; `face_id_margin` bawaan jadi 0.15).
- Key hilang dari config push (backend lama) memakai nilai awal di node; node lama mengabaikan key tak dikenal.
- Teks UI lewat `src/app/i18n.tsx` (`id` dan `en`), komponen Carbon, 390 px tanpa overflow horizontal.
- Commit Conventional Commits berbahasa Indonesia, **tanpa atribusi AI** (AGENTS.md §9), jangan `push` sebelum semua task hijau. Suite dijalankan berurutan, bukan paralel. Tanpa secret di kode atau dokumen.
- Executor berhenti di `git push` dari `feat/face-params-unify`; deploy, uji lapangan, dan merge dikerjakan sesi perencanaan.

## Review Focus

- Baris `detector_setting` belum ada (instalasi baru): GET, `build_node_config`, dan `load(db)` memakai `Settings`, bukan error.
- Perubahan ambang di UI berlaku pada event berikutnya tanpa restart (tidak ada cache di API).
- Node dan backend beda versi: `face.ident` hilang → nilai awal; `ident` dengan key parsial → key lain tetap nilai awal.
- Nilai di luar rentang (jendela 20, K 0) ditolak 422 dan tidak mengubah baris.
- Mengubah hanya `face.ident` merestart worker wajah, tetapi tidak worker kamera tanpa worker wajah.

---

### Task 1: Kolom DB, model, schema, dan API setelan

**Files:**
- Create: `backend/alembic/versions/0024_face_policy.py`, `backend/tests/test_migration_0024.py`
- Modify: `backend/app/models/detector_setting.py`, `backend/app/schemas/detector_setting.py`, `backend/app/api/detector_settings.py`, `backend/app/core/config.py`, `backend/tests/test_detector_settings_api.py`

**Interfaces:**
- Produces: kolom `DetectorSetting.face_match_threshold`, `face_match_margin`, `face_max_pitch` (Float), `face_best_k` (Integer), `face_ident_min_width_px`, `face_ident_window_s` (Float); `Settings.face_max_pitch`, `face_best_k`, `face_ident_min_width_px`, `face_ident_window_s`; `Settings.face_id_threshold` dihapus; `Settings.face_id_margin` bawaan 0.15.

- [ ] **Step 1: Tes migrasi.** `test_migration_0024.py` meniru `test_migration_0023.py`: tabel `detector_setting` dengan baris id=1, `upgrade()` dua siklus. Assert: `revision == "0024"`, `down_revision == "0023"`; baris lama mendapat nilai awal Global Constraints; kolom `nullable is False`; setelah `downgrade()` kolom tabel kembali ke semula.
- [ ] **Step 2: Tes API di `test_detector_settings_api.py`:** perluas `VALUES` dengan enam key baru; `test_get_without_row_returns_env_defaults` meng-assert enam nilai awal; `test_new_face_fields_round_trip` (PUT lalu GET mengembalikan nilai); `test_new_face_fields_out_of_range_rejected` (parametrize: threshold 0.05, margin 0.6, pitch 0.01, K 11, lebar 10, jendela 16 → 422 dan GET tetap nilai lama). Jalankan, pastikan GAGAL.
- [ ] **Step 3: Implement** migrasi (`server_default` string/number per kolom, `downgrade` via `batch_alter_table`), enam `Mapped` kolom (python `default` = nilai awal), `Field(...)` di `DetectorSettingsIn/Out`, `_effective()` mengisi enam field dari `Settings`, dan `Settings` (hapus `face_id_threshold`, tambah empat field fallback, `face_id_margin = 0.15`).
- [ ] **Step 4:** `cd backend && pytest tests/test_migration_0024.py tests/test_detector_settings_api.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(backend): kolom kebijakan pengenalan wajah di detector_setting (0024)`.

### Task 2: `FacePolicy` dan pencocokan memakai DB

**Files:**
- Create: `backend/app/services/face_policy.py`, `backend/tests/test_face_policy.py`
- Modify: `backend/app/services/face.py`, `backend/app/services/attendance.py`, `backend/app/services/intrusion_face.py`, `docker/compose.yml`, `docker/tests/test_compose.py`, `backend/tests/test_attendance_api.py`, `backend/tests/test_intrusion_face_api.py`

**Interfaces:**
- Consumes: kolom Task 1.
- Produces: `@dataclass(frozen=True) class FacePolicy: match_threshold: float; match_margin: float`; `def from_settings() -> FacePolicy`; `def load(db) -> FacePolicy` (baris id=1, jika tidak ada `from_settings()`); `FaceGallery.match(vector, threshold: float | None = None)`; `match_vector(vector, quality=None, policy: FacePolicy | None = None)`; `match_strict(vector, quality=None, policy: FacePolicy | None = None)`; `policy=None` berarti `from_settings()`.

- [ ] **Step 1: Tes `test_face_policy.py`** (gagal dulu): `test_load_without_row_uses_settings` (monkeypatch `face_match_threshold` 0.42, `face_id_margin` 0.12 → `FacePolicy(0.42, 0.12)`); `test_load_row_overrides_settings` (baris 0.55 / 0.2); `test_match_vector_uses_policy_threshold` (galeri `[1,0,0,0]`, query cosine 0.38: `FacePolicy(0.35, 0.15)` → `matched`, `FacePolicy(0.40, 0.15)` → `no_match`); `test_match_strict_uses_policy_margin` (dua karyawan, selisih top-1/top-2 0.12: margin 0.10 → `matched`, 0.15 → `ambiguous`); `test_policy_change_applies_without_restart` (dua `load(db)` berurutan setelah mengubah baris → nilai baru).
- [ ] **Step 2: Tes pemanggil.** `test_attendance_api.py`: event dengan embedding cosine ≈ 0.45 → `matched` saat baris DB threshold 0.40 dan `match_reason == "no_match"` saat 0.99. `test_intrusion_face_api.py`: dua karyawan dengan margin 0.12 → `payload.face.status` `recognized` saat margin DB 0.10 dan `unknown`/`ambiguous` saat 0.15. Ikuti fixture berkas masing-masing.
- [ ] **Step 3: Implement** `face_policy.py`; `face.py` memakai `policy` (`match_crop(db, path)` memanggil `face_policy.load(db)`); `attendance.handle_face_event` dan `intrusion_face._identify_with_name` memanggil `face_policy.load(db)` sekali per panggilan dan meneruskannya. `docker/compose.yml`: hapus `FACE_ID_THRESHOLD`, bawaan `FACE_ID_MARGIN` `:-0.15`; ubah `test_api_and_retention_receive_face_id_thresholds_but_vision_does_not` (hanya `FACE_ID_MARGIN == "0.15"`, `FACE_ID_THRESHOLD` tidak ada di `api`, `retention`, maupun `vision`).
- [ ] **Step 4:** `pytest tests/test_face_policy.py tests/test_face_strict.py tests/test_face_service.py tests/test_attendance_api.py tests/test_attendance_logic.py tests/test_intrusion_face_api.py tests/test_face_alert_sync.py -q` dan `pytest docker/tests -q` → PASS, `test_attendance_*` tanpa perubahan selain tes baru di Step 2.
- [ ] **Step 5: Commit** `feat(backend): pencocokan wajah memakai kebijakan dari DB (FacePolicy)`.

### Task 3: Blok `face.ident` di config push dan node

**Files:**
- Modify: `backend/app/services/config_push.py`, `backend/tests/test_config_push.py`, `vision/vision/face_quality.py`, `vision/vision/intrusion_face.py`, `vision/tests/test_face_quality.py`, `vision/tests/test_intrusion_face.py`, `vision/tests/test_config_apply_per_camera.py`

**Interfaces:**
- Consumes: kolom Task 1.
- Produces: `cfg["face"]["ident"] = {"min_width_px", "max_pitch", "best_k", "window_s"}`; di `face_quality.py`: konstanta `IDENT_MIN_WIDTH_PX = 60.0`, `MAX_PITCH = 0.30`, `BEST_K = 5`, `IDENT_WINDOW_S = 8.0`, `@dataclass(frozen=True) class IdentSettings(min_width_px, max_pitch, best_k: int, window_s)` dengan `from_config(ident: dict | None)`, dan `FaceSettings.ident: IdentSettings` (nilai awal `IdentSettings()`, diisi `FaceSettings.from_config` dari `face.get("ident")`). Nama konstanta tetap dapat diimpor dari `vision.intrusion_face`.

- [ ] **Step 1: Tes backend.** Perbarui `test_build_node_config_face_defaults_keep_device_pins` (dict `face` kini memuat `"ident": {"min_width_px": 60.0, "max_pitch": 0.30, "best_k": 5, "window_s": 8.0}`); tambah `test_build_node_config_face_ident_from_row` (baris dengan nilai non-awal muncul di `ident`).
- [ ] **Step 2: Tes vision.** `test_face_quality.py`: `from_config` tanpa `ident` → `IdentSettings()`; `ident` parsial `{"best_k": 3}` → K 3 dan sisanya nilai awal; `best_k` bertipe `int`; `FaceSettings` dengan `ident` beda tidak sama (`!=`). `test_intrusion_face.py` (tiap tes gagal bila konstanta masih tertanam): kolektor dengan `window_s=3.0` mengeluarkan hasil pada `t0 + 3.0` dan tidak pada `t0 + 2.9`; `best_k=2` → `stats.frames_used == 2` setelah 4 frame lolos; `max_pitch=0.05` menolak wajah ber-pitch ringan yang diterima pada nilai awal; `min_width_px=100` menolak wajah 80 px dengan kode `small`. `test_config_apply_per_camera.py`: tiru `test_face_settings_change_restarts_only_cameras_with_a_face_worker`, hanya `face.ident.window_s` berubah → hanya kamera ber-worker wajah yang restart.
- [ ] **Step 3: Implement** `build_node_config` (`gs.face_* if gs else settings.face_*` untuk empat nilai `ident`); `face_quality.py` memuat konstanta, `IdentSettings`, `FaceSettings.ident`; `intrusion_face.py` mengimpor konstanta dari `face_quality`, dan `IdentCollector` memakai `settings.ident` (`min_width_px` di `replace(settings, min_width_px=..., blur_min=0.0)`, `best_k`, `window_s`, `max_pitch`) menggantikan konstanta modul.
- [ ] **Step 4:** `pytest backend/tests/test_config_push.py -q` lalu `cd vision && pytest tests -q -m "not gpu"` → PASS (berurutan).
- [ ] **Step 5: Commit** `feat(vision): parameter identitas dari config push (FaceSettings.ident)`.

### Task 4: Kartu UI "Pengenalan wajah"

**Files:**
- Modify: `frontend/src/api/detection.ts`, `frontend/src/features/config/DetectionPage.tsx`, `frontend/src/app/i18n.tsx`, `frontend/src/__tests__/detection.test.tsx`

**Interfaces:**
- Consumes: enam field REST dari Task 1 (`face_match_threshold`, `face_match_margin`, `face_max_pitch`, `face_best_k`, `face_ident_min_width_px`, `face_ident_window_s`).

- [ ] **Step 1: Tes `detection.test.tsx` (gagal dulu):** stub `settings` memuat enam field baru; setelah membuka Advanced, tiga heading grup terlihat ("Bersama", "Identitas", "Absensi (lama)"); mengubah `#face-match-threshold` ke `0.45` dan menyimpan → body `PUT` memuat `face_match_threshold: 0.45` dan kelima field baru lainnya dengan nilai stub; label dalam bahasa `en` untuk satu field baru tersedia.
- [ ] **Step 2: Implement.** Tipe `DetectorSettings` + enam field; `DetectionPage`: grup **Bersama** (skor deteksi, yaw, ambang kecocokan `#face-match-threshold`), **Identitas** (lebar `#face-ident-min-width`, pitch `#face-max-pitch`, K `#face-best-k`, margin `#face-match-margin`, jendela `#face-ident-window`), **Absensi (lama)** (lebar, blur, jumlah frame); `save()` mengirim semua field. Kunci i18n `id` dan `en`: `detection.faceGroupShared`, `detection.faceGroupIdent`, `detection.faceGroupAttendance`, `detection.faceMatchThreshold`, `detection.faceMatchMargin`, `detection.faceMaxPitch`, `detection.faceBestK`, `detection.faceIdentMinWidth`, `detection.faceIdentWindow`; ubah label `detection.faceMinFrames` agar tidak tertukar dengan K. Batas `min`/`max`/`step` sama dengan Global Constraints.
- [ ] **Step 3:** `cd frontend && npx vitest run src/__tests__/detection.test.tsx` → PASS, lalu `npx vitest run`, `npm run lint`, `npm run build`.
- [ ] **Step 4: Verifikasi tampilan.** Jalankan dev server, buka Konfigurasi → Deteksi & Model → Advanced pada 390 px dan 1280 px, simpan screenshot di `docs/evidence/` (gitignored, jangan di-commit); `document.documentElement.scrollWidth <= innerWidth` pada 390 px.
- [ ] **Step 5: Commit** `feat(frontend): kartu pengaturan pengenalan wajah dengan tiga grup`.

### Task 5: Dokumen, suite penuh, dan bukti

**Files:**
- Modify: `ARCHITECTURE.md`, `WORKFLOW.md` (§12 butir 2), `README.md` (paragraf Face ID intrusion), `docs/runbooks/intrusion-face-id.md`, `docs/runbooks/attendance.md`, `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: Dokumen.** `ARCHITECTURE.md`: blok `face` (termasuk `ident`) dan `FacePolicy`; `WORKFLOW.md`/`README.md`/`attendance.md`/`intrusion-face-id.md`: ambang dan margin kini di Konfigurasi → Deteksi & Model (bukan `FACE_ID_*` di `.env`; hapus petunjuk "recreate api" untuk ambang); `intrusion-face-id.md`: tabel letak parameter dan catatan nilai server `0.35 / 0.15` digantikan nilai DB 0.40 / 0.15. `attendance.md`: query pemantauan siap pakai (distribusi `payload->>'face_score'` dan hitungan `payload->>'match_reason'` per `camera_id` per hari dari tabel `event` untuk `type = 'attendance'`; verifikasi kolom pada DB lokal sebelum menulis).
- [ ] **Step 2: `ROADMAP.md`:** baris baru `FPU` (keselarasan parameter wajah) `[~]` dengan tahap 1 selesai dan tahap 2 menunggu bukti; **jangan** menutup `IFI`.
- [ ] **Step 3: Suite penuh berurutan,** tempel hasil ke `CHANGELOG.md`: `cd backend && pytest tests -q -m "not gpu and not llm"`; `cd vision && pytest tests -q -m "not gpu"`; `pytest docker/tests -q`; `cd frontend && npx vitest run && npm run lint && npm run build`. Kegagalan apa pun dilaporkan dengan nama tesnya.
- [ ] **Step 4: `CHANGELOG.md`:** satu entri per commit atau satu entri siklus (konteks, berkas, bukti, dampak termasuk ambang intrusion server 0,35 → 0,40, rollback `git revert` + `alembic downgrade -1`).
- [ ] **Step 5: Commit** `docs: parameter pengenalan wajah terpusat di DB (tahap 1)` lalu `git push -u origin feat/face-params-unify`, dan berhenti.
