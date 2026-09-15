# I-Sentinel — Fase 4: Absensi Wajah Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Siklus absensi penuh: enrollment wajah (upload image, min 3 pose) → orang lewat gate → wajah dikenali → attendance entry/exit → rekap harian dengan shift & status (ontime/late/waiting/no_exit/absent) → export/import CSV. Bukti: orang test masuk+keluar gate → rekap benar; CSV cocok; orang tak dikenal tidak jadi absensi.

**Architecture:** Visi TIDAK memakai InsightFace (tetap ringan untuk edge nanti): analyzer `face_gate` di vision mendeteksi orang di zona `absensi`, memotong crop tubuh-atas (best-shot = bbox terbesar dalam window), upload crop via blob API, lalu publish event `attendance` dengan `payload{direction, crop_path}`. Server: face service (InsightFace SCRFD+ArcFace) memproses crop → match gallery (<100, cosine ≥0.40) → `attendance_event` → agregasi `attendance_day`. UI mockup 04 + tab Gate Absensi mockup 06.

**Tech Stack:** InsightFace + onnxruntime-gpu (server, GPU marker untuk test nyata), existing stack lain. Model buffalo_l (det+rec) dikelola via script download.

**Spec:** `docs/plans/2026-09-08-isentinel-design.md` §5 · Master: `docs/plans/00-master.md` · Brief: `docs/plans/05-fase-4-absensi.md`

## Global Constraints

- Lihat master plan §Global Constraints — semua berlaku.
- **Biometrik = data sensitif (PDP)**: embedding + foto hanya di server; tombol hapus biometrik per karyawan menghapus face_embedding + file foto (riwayat absensi tetap); tidak ada embedding/foto wajah di log; export absensi TIDAK menyertakan biometrik.
- Kredensial & token tidak berubah (zero-secret).
- Face matching tanpa InsightFace terpasang → status `not_configured` (graceful, pola Telegram) — bukan crash; test CPU memakai vektor dummy (tanpa model).
- `meters_per_pixel`, threshold, tolerance: semua knob config, bukan hardcode.
- Vision tetap tanpa dep baru berat (crop = numpy slicing + cv2 imencode yang sudah ada).

---

### Task 1: Model absensi + migration 0005 + employees/shifts API

**Files:**
- Create: `backend/app/models/{employee,shift,face_embedding,attendance}.py`, `backend/alembic/versions/0005_attendance.py`, `backend/app/schemas/employee.py`, `backend/app/api/employees.py`, `backend/app/api/shifts.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`
- Test: `backend/tests/test_employees_api.py`

**Interfaces:**
- Produces:
  - `Employee(id, name, employee_code unique, active bool default True, shift_id FK shift nullable, created_at)`; relasi `shift`, `embeddings`.
  - `Shift(id, name unique, start_time str "HH:MM", end_time str "HH:MM", tolerance_min int default 15, workdays JSON [1..7], created_at)`.
  - `FaceEmbedding(id, employee_id FK ondelete CASCADE, vector JSON float[512], source_image_path str, quality float, created_at)`. Index employee_id.
  - `AttendanceEvent(id, employee_id FK, camera_id FK, zone_id int null, direction str entry|exit, ts_event tz, match_score float, snapshot_path str null, event_id uuid str null unique, created_at)`.
  - `AttendanceDay(id, employee_id FK, date date, first_entry tz null, last_exit tz null, duration_min int null, status str ontime|late|waiting|no_exit|absent, late_minutes int null, override_note str null, updated_at, unique(employee_id, date))`.
  - API: GET/POST/PATCH/DELETE `/api/v1/employees` (admin mutate; DELETE → 409 bila punya attendance ROWS (event ATAU day) — nonaktifkan via active=false); GET/POST/PATCH/DELETE `/api/v1/shifts` (admin; DELETE dipakai employee → 409).
  - Attendance gate = Zone type="absensi" + direction (sudah ada) — TIDAK ada model gate baru.

- [ ] **Step 1: Failing test** — employees CRUD (kode unik → 409 dup), shift CRUD, unique constraints DB (FK pragma ON di conftest), attendance FK guards.
- [ ] **Step 2: Run — verify fail** (`cd backend && .venv/Scripts/python.exe -m pytest tests/test_employees_api.py -v`)
- [ ] **Step 3: Implement** + migration 0005 hand-written (down_revision 0004). Index names HARUS sama di model & migration (index=True / __table_args__).
- [ ] **Step 4: Run — pass** + full suite.
- [ ] **Step 5: Commit** — `feat: attendance domain models (employee, shift, embedding, attendance) + api`

---

### Task 2: Face service (InsightFace wrapper, gallery, match) — CPU-testable

**Files:**
- Create: `backend/app/services/face.py`, `backend/scripts/download_face_models.py`
- Modify: `backend/app/core/config.py` (+`face_model_dir`, `face_match_threshold: float = 0.40`, `face_min_quality: float = 0.5`)
- Test: `backend/tests/test_face_service.py`

**Interfaces:**
- Produces:
  - `FaceEngine` — lazy import insightface; `available() -> bool`; `embed(image) -> list[FaceResult(vector, det_score, bbox, quality)]` (SCRFD → ArcFace normed 512-d; quality = det_score × min(1, face_px/96)); model tidak ada → available False + log sekali.
  - `FaceGallery` — in-memory employee_id → list[vec]; `load(db)`, `refresh(db)`, `match(vector) -> (employee_id, score) | None` (vektor L2-norm → dot product; threshold settings); `size()`.
  - `match_crop(db, image_path) -> MatchResult(employee_id|None, score, quality, reason)` — engine unavailable → reason "not_configured".
  - `enroll_embedding(db, employee, image_path) -> FaceEmbedding` — kualitas < min / tidak ada wajah → ValueError.
  - `download_face_models.py` — unduh buffalo_l ke face_model_dir (server, bring-up).
- Gallery refresh dipanggil: startup, setelah enroll, setelah delete/purge.

- [ ] **Step 1: Failing test (CPU, dummy engine via monkeypatch)** — (a) match exact → employee_id + score ~1.0; (b) cosine < threshold → None; (c) quality rendah → ditolak; (d) engine unavailable → not_configured; (e) enroll simpan row + gallery refresh; (f) threshold dari settings.
- [ ] **Step 2: verify fail** → **Step 3: implement** → **Step 4: pass** + suite
- [ ] **Step 5: Commit** — `feat: face service (insightface wrapper, gallery, cosine match)`

---

### Task 3: Face enrollment API (upload foto, min 3/max 5, hapus biometrik)

**Files:**
- Create: `backend/app/api/enrollment.py`
- Modify: `backend/app/api/employees.py` (delete hooks), `backend/app/services/face.py` (gallery refresh hooks), `backend/app/main.py`
- Test: `backend/tests/test_enrollment_api.py`

**Interfaces:**
- Produces:
  - `POST /api/v1/employees/{id}/photos` (admin, multipart) — simpan `{storage_root}/faces/{employee_id}/<uuid>.jpg`, enroll_embedding; response {embedding_id, quality}; 422 kualitas gagal; max 5 → 409.
  - `GET /api/v1/employees/{id}/photos` — list (id, quality, created_at, path relatif — disajikan via /api/v1/media juga).
  - `DELETE /api/v1/employees/{id}/photos/{embedding_id}` — row + file + gallery refresh.
  - `DELETE /api/v1/employees/{id}/biometrics` — semua embedding + folder (PDP); riwayat absensi tetap.
  - `GET /api/v1/employees/{id}/enrollment-status` → {photos, active: photos>=3}.
- [ ] **Step 1: Failing test** — 3 upload → active; ke-6 → 409; hapus 1 → file gone; purge → semua gone + gallery kosong untuk employee itu.
- [ ] **Step 2: verify fail** → **Step 3: implement** → **Step 4: pass** + suite
- [ ] **Step 5: Commit** — `feat: face enrollment api (min 3 pose, pdp purge)`

---

### Task 4: Vision gate analyzer (crop best-shot + upload + event)

**Files:**
- Create: `vision/vision/analyzers/face_gate.py`
- Modify: `vision/vision/analyzers/__init__.py`, `vision/vision/node.py` (zona `absensi` lolos filter + FaceGateAnalyzer; emit_crop callback di-inject worker), `vision/vision/recorder.py` (fungsi publik `upload_bytes(jpeg, kind) -> path|None` reuse `_upload_one`)
- Test: `vision/tests/test_face_gate.py`

**Interfaces:**
- Produces: `FaceGateAnalyzer(zone)` — direction = zone["direction"]; track centroid di polygon → emit partial {"type": "attendance", "severity": "info", "zone_id", "payload": {"direction", "track_id", "crop_ref": True}}, 1 event per kunjungan (`_done` set sampai keluar polygon), cooldown 10s per track; node mengganti crop_ref dengan crop_path hasil crop (bbox expand 20%, upper 60%) + upload blocking (gate low-frequency); uploader None → event tetap terbit tanpa crop_path (graceful); upload gagal → tanpa crop_path + log.
- Node: filter `_cameras_from_config` tambah `or z.get("type")=="absensi"`.

- [ ] **Step 1: Failing test** — masuk zona → 1 partial direction entry; keluar-masuk → 2; uploader mock → payload crop_path terisi; uploader None → tetap terbit.
- [ ] **Step 2: verify fail** → **Step 3: implement** → **Step 4: pass** + suite
- [ ] **Step 5: Commit** — `feat: face gate analyzer (crop best-shot + upload)`

---

### Task 5: Attendance logic (match → event → day aggregate) + override + daily close

**Files:**
- Create: `backend/app/services/attendance.py`, `backend/app/api/attendance.py`
- Modify: `backend/app/services/events_consumer.py` (hook type attendance), `backend/app/main.py`, `backend/app/core/config.py` (+`no_exit_grace_min: int = 60`)
- Test: `backend/tests/test_attendance_logic.py`, `backend/tests/test_attendance_api.py`

**Interfaces:**
- Produces:
  - `handle_face_event(db, event)` — payload.crop_path ada → face.match_crop → match: AttendanceEvent + `recompute_day`; no match → log + payload employee_id null (event tetap); crop_path null → skip + log.
  - `recompute_day(db, employee_id, day) -> AttendanceDay` — first_entry=min(entry), last_exit=max(exit); shift null → ontime tanpa late; status: ada exit → late bila first_entry > start+tolerance (late_minutes) else ontime; belum exit & belum lewat end+grace → waiting; lewat → no_exit.
  - `close_days(db, day)` — semua karyawan aktif workday: recompute; tanpa entry → absent.
  - API: `GET /api/v1/attendance?date=&from=&to=&employee_id=`; `GET /api/v1/attendance/rekap.csv?from=&to=` (tanpa biometrik); `POST /api/v1/attendance/import` (CSV upsert by (code,date), override_note="import"); `PATCH /api/v1/attendance/{day_id}` (admin, note wajib); `POST /internal/maintenance/close-days` (api-key, untuk cron; GET attendance juga lazy recompute kemarin).
- [ ] **Step 1: Failing test** — skenario (a)-(h) dari brief: ontime, late, waiting, no_exit, absent via close_days, tanpa shift, handle_face_event match/unknown.
- [ ] **Step 2: verify fail** → **Step 3: implement** → **Step 4: pass** + suite
- [ ] **Step 5: Commit** — `feat: attendance logic (match, aggregate, override, csv, close-days)`

---

### Task 6: Frontend — halaman Attendance + Enrollment + tab Gate Absensi

**Files:**
- Create: `frontend/src/features/attendance/AttendancePage.tsx`, `frontend/src/features/enrollment/EnrollmentPage.tsx`, `frontend/src/api/{attendance,employees}.ts`, `frontend/src/features/config/GatesPage.tsx`
- Modify: `frontend/src/main.tsx` (routes), i18n
- Test: `frontend/src/__tests__/attendance.test.tsx`, `frontend/src/__tests__/enrollment.test.tsx`

**Interfaces (mockup 04/05/06):**
- Attendance: tab Harian/Rentang/Per karyawan; summary tiles; tabel (avatar+nik, shift, entry, exit, durasi, badge TEPAT WAKTU/TELAT n MNT/MENUNGGU/TIDAK HADIR/NO EXIT); timeline entry-exit vs jadwal; Export CSV + Import; admin override modal (entry/exit/status + catatan).
- Enrollment: list karyawan + dot wajah + jumlah foto; detail galeri (upload, hapus per foto, skor kualitas), tombol "Hapus data biometrik"; form karyawan + shift.
- Gate Absensi: tabel kamera ↔ arah entry/exit, validasi konflik satu arah, toggle snapshot.
- [ ] **Step 1: Failing tests** — attendance rows + badge; override submit → PATCH; enrollment 3 foto → aktif; gate conflict warning.
- [ ] **Step 2: verify fail** → **Step 3: implement** → **Step 4: vitest + build green**
- [ ] **Step 5: Commit** — `feat: attendance + enrollment + gates UI`

---

### Task 7: Bring-up verifikasi di server (controller)

- [ ] Deploy + migration 0005 + install insightface + onnxruntime-gpu di /home/gspe-ai3/isentinel-venv + download_face_models.py
- [ ] Shift (07:00-16:00 tol 15) + karyawan test + enroll 3 foto via API
- [ ] Zona absensi di kamera gate (arah entry) — set salah satu kamera NVR sebagai gate
- [ ] Demo E2E: orang terdaftar lewat gate → event attendance + attendance_event + rekap; orang tak dikenal → tidak ada attendance_event
- [ ] Export CSV verifikasi manual; import roundtrip
- [ ] Catat bukti di plan + ROADMAP → merge + changelog 0.5.0

---

## Fase 4 — Definition of Done

1. Semua checkbox `[x]` dengan bukti (query DB, CSV, screenshot).
2. Test: backend + vision (CPU) + vitest + build hijau; test GPU face (`@pytest.mark.gpu`) hijau di server.
3. Demo: entry+exit rekap benar, unknown face tidak jadi absensi, CSV cocok, purge biometrik bekerja.
4. Merge `feat/fase-4-absensi` → `main`, tag `v0.5.0`, changelog, server sync.

## Risiko & catatan

- InsightFace buffalo_l (~300MB) unduh sekali di server; onnxruntime CPU fallback tetap jalan (lambat).
- Kualitas crop gate → quality gate menolak; threshold tuning per gate tersedia.
- Embedding JSON untuk <100; pgvector bila >5k (tercatat, YAGNI).
- UI polish global ditunda atas permintaan user — tidak masuk fase ini.
