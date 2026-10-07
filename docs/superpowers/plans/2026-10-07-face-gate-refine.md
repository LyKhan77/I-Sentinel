# Face Gate Refine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Telegram menandai entry berulang sebagai evidence, zona attendance bisa deteksi-saja dan bisa menahan wajah Unknown, dan face worker berhenti membuang bukti saat wajah diam, dengan corong ukur untuk tuning.

**Architecture:** Semua flag baru hidup di JSON `behaviors` pada behavior `attendance` (tanpa migrasi). Keputusan alert tetap di `alerting.should_alert`, teks di `telegram.format_caption`, logika absensi di `attendance.handle_face_event`. Node mendapat satu kondisi motion gate dan counter corong yang dibawa heartbeat lewat jalur `cameras[]` yang sudah ada.

**Tech Stack:** Python 3.11 (FastAPI, SQLAlchemy, pytest), vision node (NumPy, pytest), React 19 + Carbon + Vitest.

**Spec:** `docs/superpowers/specs/2026-10-07-face-gate-refine-design.md` (baca dulu; plan ini memakai nomor bagian spec). Branch: `feat/face-gate-refine`.

## Global Constraints

- Flag baru: `telegram_unknown` (default `true`) dan `record` (default `true`); key hilang atau `behaviors` null = default. Divalidasi boolean di `_validate_behaviors`.
- `direction` zona tetap wajib; tidak ada migrasi; tidak ada perubahan ambang cosine atau gerbang kualitas.
- Cooldown memakai `settings.attendance_cooldown_min` (default 5). Urutan cek di `handle_face_event`: cooldown lebih dulu, lalu `already_in`.
- Teks Telegram: nilai di-escape lewat `val()`, caption tetap < 1024 karakter; label Indonesia, judul tebal.
- Semua string UI lewat `frontend/src/app/i18n.tsx` (kunci `id` dan `en`); komponen Carbon, tanpa CSS ad-hoc.
- Commit Conventional Commits, satu per task, **tanpa atribusi AI** (AGENTS.md §9; abaikan trailer `Co-Authored-By` bawaan). Jangan `push`.
- Tiap task menambah satu entri `CHANGELOG.md` (terbaru di atas, format entri yang ada: Konteks, Perubahan, Bukti = keluaran tes yang ditempel, Dampak, Rollback) dalam commit yang sama.
- Jangan `uv sync`, `uv lock`, atau membuat ulang venv (merusak instal editable `vision`). Jalankan suite **berurutan**, tidak paralel.
- Deploy, tuning angka, dan uji penerimaan server di luar plan ini (sesi perencanaan).

## Pre-flight (sebelum Task 1)

- [ ] Catat baseline dan tempel di entri CHANGELOG Task 1: dari `backend/`: `pytest tests -q -m "not gpu and not llm"`; dari `vision/`: `pytest tests -q -m "not gpu"`; dari `frontend/`: `npx vitest run`, `npm run build`, `npm run lint`.

## Review Focus

Kondisi yang tidak disebut spec tetapi paling mungkin menggigit; tiap baris punya tes di task pemiliknya.

1. Caption `already_in` dari event tanpa `first_entry_ts` (event lama/ulang render): baris tampil `-`, tidak error. (Task 2)
2. Exit yang terjadi **sebelum** entry pertama atau hari lain tidak dihitung sebagai "Exit sejak itu". (Task 2)
3. Zona pra-R5 (`behaviors` null) atau behavior tanpa key flag: `record` dan `telegram_unknown` bernilai `true`. (Task 3)
4. Zona OFF: dua karyawan berbeda di zona sama dalam jendela cooldown sama-sama `detected`; wajah Unknown tidak di-dedup dan tidak error saat `employee_id` None. (Task 5)
5. Motion gate: setelah wajah menghilang gate kembali melewati frame diam, dan heartbeat dari node lama (tanpa `funnel`) tidak merusak monitoring. (Task 7, 8)

---

### Task 1: Tautan Telegram berlabel "Lihat event"

**Files:**
- Modify: `backend/app/services/telegram.py:266`
- Modify: `backend/tests/test_telegram.py:85,112,232`
- Modify: `CHANGELOG.md`

**Interfaces:** Produces: baris tautan `🎥 Lihat event: {app_url}/events?event={id}` untuk semua tipe alert (emoji tetap).

- [ ] **Step 1: Ubah tiga assertion ke `Lihat event`** (baris 85 daftar baris caption, 112 `not any("Lihat event" in line ...)` untuk caption tanpa `app_url`, 232 daftar caption AI).
- [ ] **Step 2: Jalankan** `cd backend && pytest tests/test_telegram.py -q` — Expected: 3 FAILED (tes yang diubah).
- [ ] **Step 3: Ganti** string di `format_caption` dari `Lihat klip:` ke `Lihat event:`.
- [ ] **Step 4: Jalankan** `pytest tests/test_telegram.py tests/test_alert_ai.py tests/test_alert_dispatcher.py -q` — Expected: semua PASS.
- [ ] **Step 5: CHANGELOG + commit** `fix(telegram): tautan alert berlabel "Lihat event"`.

---

### Task 2: Evidence `already_in` ke Telegram

**Files:**
- Modify: `backend/app/services/attendance.py` (ganti `_entered_earlier_today` lines 127-134; cabang `already_in` lines 204-206)
- Modify: `backend/app/services/alerting.py` (`should_alert`, cabang attendance)
- Modify: `backend/app/services/telegram.py` (`format_caption`, rantai judul lines 243-251)
- Test: `backend/tests/test_attendance_logic.py`, `backend/tests/test_alerting.py`, `backend/tests/test_telegram.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `attendance._first_entry_today(db, employee_id: int, ts: datetime) -> datetime | None` = `ts_event` (via `_local`) entry paling awal pada tanggal lokal `ts` dengan nilai ≤ `ts`; mengganti `_entered_earlier_today` (satu-satunya pemanggil: `handle_face_event`; semantik `is not None` sama dengan bool lama).
- Produces: `attendance._exit_between(db, employee_id: int, start: datetime, end: datetime) -> datetime | None` = exit terakhir dengan `start < ts_event <= end`.
- Produces: payload event `already_in` berisi `first_entry_ts: str` (`_local(...).isoformat()`) dan `exit_ts: str` hanya bila ada exit.
- Produces: `should_alert` → `(True, "")` untuk `match_reason == "already_in"` setelah lolos `_telegram_on`, tanpa rate-limit generik.
- Produces: caption `already_in` (baris persis di Step 1c).

- [ ] **Step 1: Tulis tes yang gagal**
  - a. `test_attendance_logic.py` (pakai helper `_matched_vec`/`VEC`/`_raw_event`/`_att_event` seperti `test_second_entry_same_day_after_cooldown_is_not_recorded`):
    - `test_already_in_payload_carries_first_entry_without_exit`: entry 07:10 dicatat, entry 09:30 → `payload["first_entry_ts"] == _at(*MON, 7, 10).isoformat()` dan `"exit_ts" not in payload`.
    - `test_already_in_payload_carries_exit_seen_between`: entry 07:10, exit 08:00 dicatat lewat `handle_face_event`, entry 09:30 → `payload["exit_ts"] == _at(*MON, 8, 0).isoformat()`.
    - `test_already_in_ignores_exit_before_first_entry`: `_att_event(db, e.id, "exit", _at(*MON, 6, 0))`, entry 07:10, entry 09:30 → `"exit_ts" not in payload` (Review Focus 2).
  - b. `test_alerting.py`: ubah `test_attendance_matched_and_unknown_sent_others_skipped` — keluarkan `"already_in"` dari tuple skipped (sisa `cooldown, low_quality, no_face, None`); tambah `test_attendance_already_in_sent_and_not_rate_limited`: dua event `already_in` (NOW dan NOW+30 dtk, `employee_id` sama) lewat `alerting.handle` → keduanya `status == "queued"`, `type == "attendance"`.
  - c. `test_telegram.py`: `test_caption_attendance_already_in_shows_first_entry_and_exit_status` dengan `tz=WIB`, `app_url=None`, payload `{"match_reason": "already_in", "employee_name": "Budi Santoso", "first_entry_ts": "2026-09-25T07:10:00+07:00"}`:
    ```
    ["🔁 <b>ATTENDANCE — SUDAH CHECK IN</b>", "", "<b>Nama</b>: Budi Santoso",
     "<b>Check in pertama</b>: 07:10:00 WIB", "<b>Exit sejak itu</b>: belum terlihat",
     "<b>Kamera</b>: Receptionist", "<b>Zona</b>: Gerbang Lobi", "<b>Waktu</b>: 25 Sep 2026 11:42:07 WIB"]
    ```
    Varian dengan `"exit_ts": "2026-09-25T09:00:00+07:00"` → baris `<b>Exit sejak itu</b>: 09:00:00 WIB`. Tes kedua `test_caption_already_in_without_first_entry_ts_shows_dash`: tanpa `first_entry_ts` → `<b>Check in pertama</b>: -` (Review Focus 1).
- [ ] **Step 2: Jalankan** ketiga berkas tes — Expected: FAIL pada tes baru dan tes `test_alerting` yang diubah.
- [ ] **Step 3: Implementasi** helper di `attendance.py` (query `AttendanceEvent` per karyawan+arah, filter Python memakai `_local`, gaya komentar `ponytail:` yang ada); di cabang `already_in` isi payload sebelum `_save`. Di `alerting.should_alert` tambahkan `already_in` ke cabang yang mengembalikan `(True, "")`. Di `format_caption` tambah cabang `already_in` pada rantai judul (baris Nama, lalu `Check in pertama`, lalu `Exit sejak itu`, sebelum `Kamera`); format jam `astimezone(tz).strftime("%H:%M:%S %Z").strip()` dari `datetime.fromisoformat`, nilai tak terparse → `-`.
- [ ] **Step 4: Jalankan** `pytest tests/test_attendance_logic.py tests/test_alerting.py tests/test_telegram.py tests/test_attendance_api.py -q` — Expected: PASS.
- [ ] **Step 5: CHANGELOG + commit** `feat(telegram): entry berulang dikirim sebagai evidence "sudah check in"`.

---

### Task 3: Toggle `telegram_unknown` (backend)

**Files:**
- Modify: `backend/app/models/zone.py` (tambah metode)
- Modify: `backend/app/schemas/zone.py` (`_validate_behaviors`, loop flag boolean)
- Modify: `backend/app/services/alerting.py` (`should_alert`)
- Test: `backend/tests/test_alerting.py`, `backend/tests/test_zones_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `Zone.behavior_flag(self, kind: str, key: str, default: bool = True) -> bool` — `default` bila `behaviors` None/kosong, behavior `kind` tidak ada, atau key hilang; selain itu `bool(b[key])`. Dipakai Task 5.
- Produces: validator menolak `telegram_unknown` non-boolean dengan `ValueError` (422 di API).
- Produces: `should_alert` → `(False, "attendance_skipped")` bila `match_reason == "no_match"` dan `behavior_flag("attendance", "telegram_unknown", True)` false.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_alerting.py`: `test_unknown_face_suppressed_when_telegram_unknown_off` (behavior `{"kind":"attendance","trigger_seconds":0,"telegram":True,"telegram_unknown":False}` → no_match `(False, "attendance_skipped")`, matched tetap `(True, "")`); `test_unknown_face_sent_when_flag_missing_or_true` (flag hilang dan `True` → `(True, "")`); `test_behavior_flag_defaults` memanggil langsung: `Zone(behaviors=None)`, `Zone(behaviors=[])`, behavior attendance tanpa key, behavior lain saja → semua `True`; dengan `False` → `False` (Review Focus 3).
  - `test_zones_api.py`: ikuti tes validasi flag boolean `telegram` yang ada: `telegram_unknown: "no"` → 422, `True`/`False` → 200/201.
- [ ] **Step 2: Jalankan** `pytest tests/test_alerting.py tests/test_zones_api.py -q` — Expected: FAIL tes baru.
- [ ] **Step 3: Implementasi** metode model, tambah `"telegram_unknown"` ke tuple flag boolean di validator, dan satu kondisi di cabang `no_match` pada `should_alert` (dipasang setelah `_telegram_on` lolos).
- [ ] **Step 4: Jalankan** `pytest tests/test_alerting.py tests/test_zones_api.py tests/test_alert_dispatcher.py -q` — Expected: PASS.
- [ ] **Step 5: CHANGELOG + commit** `feat(alerting): opsi zona kirim wajah tidak dikenal ke Telegram`.

---

### Task 4: Toggle `telegram_unknown` (UI)

**Files:**
- Modify: `frontend/src/api/zones.ts` (tipe `Behavior`: `telegram_unknown?: boolean // kosong = true`)
- Modify: `frontend/src/features/config/ZonesPage.tsx` (setelah Toggle `zone-telegram-attendance`, lines 428-437)
- Modify: `frontend/src/app/i18n.tsx` (`zones.telegramUnknown`: id `Kirim wajah tidak dikenal`, en `Send unknown faces`)
- Test: `frontend/src/__tests__/zones.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:** Consumes: flag `telegram_unknown` (Task 3). Produces: `Toggle` id `zone-telegram-unknown`, tampil hanya bila Telegram efektif aktif (`behavior.telegram ?? selected.telegram`), `toggled = behavior.telegram_unknown ?? true`, `onToggle` menambah `telegram_unknown: v` ke behavior attendance via `patchSelected`.

- [ ] **Step 1: Tulis tes yang gagal** (pola `selectZone` seperti tes `zona absensi punya satu toggle Telegram...`): `zona absensi dengan Telegram aktif menampilkan toggle Unknown default aktif dan mematikannya mengirim telegram_unknown:false` (behavior `{kind:'attendance', trigger_seconds:0, telegram:true}`; `aria-checked` `'true'`; klik; simpan; `patchBody(...).behaviors` `toEqual([{ kind: 'attendance', trigger_seconds: 0, telegram: true, telegram_unknown: false }])`); `toggle Unknown tidak tampil saat Telegram mati` (`document.getElementById('zone-telegram-unknown')` `null`).
- [ ] **Step 2: Jalankan** `cd frontend && npx vitest run src/__tests__/zones.test.tsx` — Expected: FAIL tes baru.
- [ ] **Step 3: Implementasi** sesuai Interfaces.
- [ ] **Step 4: Jalankan** `npx vitest run src/__tests__/zones.test.tsx && npm run lint` — Expected: PASS, lint tanpa warning baru dibanding baseline.
- [ ] **Step 5: CHANGELOG + commit** `feat(zones): toggle kirim wajah tidak dikenal ke Telegram`.

---

### Task 5: "Catat absensi" OFF (backend)

**Files:**
- Modify: `backend/app/schemas/zone.py` (tambah `"record"` ke tuple flag boolean)
- Modify: `backend/app/services/attendance.py` (`handle_face_event` + dua helper)
- Modify: `backend/app/services/alerting.py` (`should_alert`)
- Modify: `backend/app/services/telegram.py` (`format_caption`)
- Test: `backend/tests/test_attendance_logic.py` (helper `_raw_event` mendapat parameter `zone_id=None`), `test_alerting.py`, `test_telegram.py`, `test_zones_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `Zone.behavior_flag` (Task 3).
- Produces: `attendance._record_on(db, zone_id: int | None) -> bool` — `True` bila zona None/tidak ada, selain itu `zone.behavior_flag("attendance", "record", True)`.
- Produces: `attendance._detected_recently(db, event, employee_id: int) -> bool` — ada `Event` lain (id berbeda) `type == "attendance"`, `zone_id` sama, `payload.employee_id == employee_id`, `payload.match_reason == "detected"`, dalam ±`settings.attendance_cooldown_min` dari `event.ts_event`. Prafilter DB `zone_id` + `ts_event` ±1 hari (selisih naive SQLite), jendela tepat di Python lewat `_local`.
- Produces: bila `record` OFF dan wajah cocok: label snapshot/crop jalan seperti biasa; tidak ada `AttendanceEvent`, tidak ada `recompute_day`; `match_reason` = `"cooldown"` bila `_detected_recently` else `"detected"`; return `None`. Dipasang tepat sebelum `_in_cooldown`.
- Produces: `should_alert` → `(True, "")` untuk `detected`. Caption: `👤 <b>TERDETEKSI — MASUK</b>` (entry) atau `KELUAR` (exit), baris `Nama`, lalu `Kamera`, `Zona`, `Waktu`; tanpa kata CHECK IN.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_attendance_logic.py` (buat `Zone` `type="attendance"`, `direction="entry"`, `behaviors=[{"kind":"attendance","trigger_seconds":0,"record":False}]`):
    - `test_record_off_detects_without_attendance_rows`: `handle_face_event` → `None`; `AttendanceEvent` count 0; `AttendanceDay` count 0; payload `match_reason == "detected"`, `employee_name == "Budi"`.
    - `test_record_off_dedups_per_employee_and_zone_within_window`: karyawan sama +3 mnt → `cooldown`; +6 mnt → `detected`; karyawan lain pada waktu yang sama → `detected`; karyawan sama di zona OFF lain → `detected` (Review Focus 4).
    - `test_record_off_unknown_face_is_not_deduped`: dua event `no_match` → keduanya `match_reason == "no_match"`, tanpa error (`employee_id` None).
    - `test_record_default_true_keeps_recording`: zona dengan behavior tanpa key `record` → `AttendanceEvent` tercatat.
  - `test_alerting.py`: `test_attendance_detected_sent_and_not_rate_limited` (dua event `detected` → `queued`).
  - `test_telegram.py`: `test_caption_attendance_detected_entry_and_exit` — judul persis `👤 <b>TERDETEKSI — MASUK</b>` / `KELUAR`, `Nama` ada, tidak ada `CHECK IN` di caption.
  - `test_zones_api.py`: `record: "no"` → 422; boolean diterima.
- [ ] **Step 2: Jalankan** keempat berkas tes — Expected: FAIL tes baru.
- [ ] **Step 3: Implementasi** sesuai Interfaces (pemuatan `Zone` lewat `db.get(Zone, zone_id)`; impor model di `attendance.py`).
- [ ] **Step 4: Jalankan** `pytest tests -q -m "not gpu and not llm"` — Expected: semua PASS (jumlah naik hanya karena tes baru).
- [ ] **Step 5: CHANGELOG + commit** `feat(attendance): opsi zona catat absensi (OFF = deteksi saja)`.

---

### Task 6: "Catat absensi" OFF (UI)

**Files:**
- Modify: `frontend/src/api/zones.ts` (`record?: boolean // kosong = true`)
- Modify: `frontend/src/features/config/ZonesPage.tsx` (blok `selected.type === 'attendance'`, sebelum Toggle Telegram)
- Modify: `frontend/src/app/i18n.tsx` (`zones.record`: id `Catat absensi` / en `Record attendance`; `zones.recordOffHint`: id `Hanya mendeteksi wajah: tidak ada rekap absensi. Event tetap masuk Inbox dan Telegram.` / en `Face detection only: no attendance record. Events still reach the Inbox and Telegram.`)
- Test: `frontend/src/__tests__/zones.test.tsx`, `frontend/src/__tests__/events.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:** Produces: `Toggle` id `zone-record-attendance` (`toggled = behavior.record ?? true`, menulis `record: v` ke behavior attendance); paragraf `data-testid="zone-record-off-hint"` hanya saat OFF. `EventsPage.faceMatch` **tidak diubah** (event `detected` dengan `employee_name` sudah tampil sebagai nama; spec §5.2 terpenuhi tanpa kode).

- [ ] **Step 1: Tulis tes yang gagal:** `zones.test.tsx`: default toggle `aria-checked='true'` dan hint tidak ada; klik → simpan → `behaviors` `toEqual([{ kind: 'attendance', trigger_seconds: 0, record: false }])` dan hint `zone-record-off-hint` tampil. `events.test.tsx` (ikuti tes `already_in` di sekitar baris 366): event `{match_reason: 'detected', employee_name: 'Budi'}` menampilkan `Budi` tanpa teks `events.face.cooldown`/`alreadyIn` (tes ini lulus sejak awal; fungsinya mengunci perilaku).
- [ ] **Step 2: Jalankan** `npx vitest run src/__tests__/zones.test.tsx src/__tests__/events.test.tsx` — Expected: FAIL hanya tes `zones` baru.
- [ ] **Step 3: Implementasi** sesuai Interfaces.
- [ ] **Step 4: Jalankan** `npx vitest run && npm run build && npm run lint` — Expected: PASS, build exit 0, lint tanpa warning baru.
- [ ] **Step 5: CHANGELOG + commit** `feat(zones): toggle Catat absensi pada zona attendance`.

---

### Task 7: Motion gate tidak memutus bukti saat wajah terlihat

**Files:**
- Modify: `vision/vision/face_worker.py` (`__init__`, loop `run` lines 110-115)
- Test: `vision/tests/test_face_worker.py`
- Modify: `CHANGELOG.md`

**Interfaces:** Produces: atribut `FaceGateWorker.motion_skipped: int` (mulai 0, naik tiap frame dilewati gate; dibaca `_camera_stats`, Task 8). Perilaku: frame tanpa gerak **tetap diproses** bila frame terproses sebelumnya berisi wajah (`self._faces_shown`); `motion_gate.update` tetap dipanggil tiap frame agar frame pembanding tidak basi.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_stationary_face_keeps_processing_after_motion_stops`: `FaceGateWorker(363, [ZONE], FakeFaces([[GOOD]] * 6), t, "test-node", FaceSettings(), motion={"enabled": True, "force_interval_s": 10}, max_age_s=0.5)`, `FrameSource.from_frames([FRAME] * 6, fps=10)` (frame identik = tanpa gerak) → satu event, `payload["face_stats"]["frames"] == 3`, `eng.embed_calls == 3`.
  - `test_motion_gate_still_skips_when_no_face_visible`: `FakeFaces([[]] * 6)` dengan gate yang sama → `w.motion_skipped == 5` (Review Focus 5).
- [ ] **Step 2: Jalankan** `cd vision && pytest tests/test_face_worker.py -q -m "not gpu"` — Expected: tes pertama FAIL (frames == 1), tes kedua FAIL (atribut belum ada).
- [ ] **Step 3: Implementasi** (satu kondisi: `moving = self.motion_gate.update(...)`; lewati hanya bila `not moving and not self._faces_shown`, dengan `motion_skipped += 1`; isi blok lewati tidak berubah).
- [ ] **Step 4: Jalankan** `pytest tests/test_face_worker.py tests/test_motion_gate.py tests/test_node.py -q -m "not gpu"` — Expected: PASS termasuk `test_motion_skipped_frames_clear_expired_overlay` yang ada (jika gagal, perbaiki implementasi, bukan tes).
- [ ] **Step 5: CHANGELOG + commit** `fix(vision): motion gate tidak memutus bukti wajah yang masih terlihat`.

---

### Task 8: Corong face worker di heartbeat dan monitoring

**Files:**
- Modify: `vision/vision/face_worker.py` (counter, `take_funnel`)
- Modify: `vision/vision/node.py` (`_camera_stats` lines 486-510)
- Modify: `backend/app/services/monitoring.py` (`_merge_workers`), `backend/app/schemas/monitoring.py` (`CameraAiOut`)
- Test: `vision/tests/test_face_worker.py`, `vision/tests/test_node.py`, `backend/tests/test_monitoring.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `FaceGateWorker.motion_skipped` (Task 7).
- Produces: `FaceGateWorker.take_funnel(self) -> dict` mengembalikan counter sejak panggilan terakhir lalu mereset: `{"faces": int, "rejects": {"zone": int, "small": int, "score": int, "yaw": int, "blur": int}, "tracks_emitted": int, "tracks_silent": int, "ttfg_median_s": float | None}`.
  - `faces` = jumlah wajah terdeteksi (per frame, setelah tracker); `rejects[kode]` = wajah per frame yang gagal gerbang dengan kode itu.
  - `tracks_emitted` naik di `_emit`.
  - `tracks_silent` = track berakhir yang pernah berada di dalam zona (kode ≠ `zone` minimal sekali) tetapi tanpa frame lolos.
  - `ttfg_median_s` = median selang dari frame pertama track berada di zona sampai frame lolos pertamanya, dibulatkan 2 desimal; `None` bila belum ada.
  - Tanpa lock (`ponytail:` komentar: selisih satu hitungan antar-thread diterima; tukar objek dict saat reset).
- Frame terproses dan frame dilewati gate (kriteria spec #9) dibawa field yang sudah ada di entri yang sama: `fps` dan `motion_skip_pct`; objek `funnel` tidak menduplikasinya.
- Produces: entri `cameras[]` worker `face` membawa kunci `funnel` (hasil `take_funnel`); `motion_skip_pct` kini dihitung untuk worker apa pun yang punya `motion_gate`. Worker `detect` tanpa kunci `funnel`.
- Produces: `CameraAiOut.funnel: dict | None = None`; `_merge_workers` menyertakan `funnel` dari entri pertama yang `funnel`-nya dict, selain itu `None`. Heartbeat node lama tetap valid (entri `cameras[]` berupa dict tak bertipe).

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_face_worker.py`: `test_funnel_counts_rejects_per_gate_code` (`run_worker([[face(width=40.0)]] * 5)` → `take_funnel()`: `faces == len(labels(t)) >= 3`, `rejects["small"] == faces`, `tracks_emitted == 0`; panggilan kedua semua nol); `test_funnel_silent_track_counts_only_tracks_that_entered_zone` (`[[face(width=40.0)]] * 3 + [[]] * 8` → `tracks_silent == 1`; `[[face(cx=100.0)]] * 3 + [[]] * 8` → `tracks_silent == 0`); `test_funnel_emitted_and_time_to_first_good_frame` (`[[face(score=0.55)]] * 2 + [[GOOD]] * 3` pada 10 fps → `tracks_emitted == 1`, `ttfg_median_s == pytest.approx(0.2, abs=0.01)`).
  - `test_node.py`: `test_camera_stats_face_entry_carries_funnel` (`_wired_node(tmp_path, [ATTENDANCE_ZONE])`, `node._workers = workers`) → `set(stats[0]["funnel"]) == {"faces", "rejects", "tracks_emitted", "tracks_silent", "ttfg_median_s"}`; entri `detect` pada node dengan `[ATTENDANCE_ZONE, BEHAVIOR_ZONE]` tidak punya kunci `funnel`; `test_camera_stats_face_motion_skip_pct` (seperti tes detect: `face.motion_gate = object()`, `face.frames`/`face.motion_skipped` 0 lalu 40/30 → `75.0`).
  - `test_monitoring.py`: `_merge_workers([{"worker": "face", "state": "ok", "fps": 4.0, "target_fps": 5.0, "funnel": {"faces": 3}}])["funnel"] == {"faces": 3}`; tanpa `funnel` → `None`.
- [ ] **Step 2: Jalankan** `vision`: `pytest tests/test_face_worker.py tests/test_node.py -q -m "not gpu"`; `backend`: `pytest tests/test_monitoring.py -q` — Expected: FAIL tes baru.
- [ ] **Step 3: Implementasi** sesuai Interfaces. Pada `_process`, catat `rejects[code]` dan waktu masuk zona per `tid` (dict `_in_zone: dict[int, float]`); catat ttfg saat embedding pertama track tersimpan; di `_expire`, hitung `tracks_silent` lalu buang `tid` dari `_in_zone`. Di `_camera_stats`, hapus syarat `kind == "detect"` pada perhitungan `skip`. Pastikan `_camera_row` di `monitoring.py` meneruskan hasil `_merge_workers` ke `CameraAiOut` (bila membangun field satu per satu, tambahkan `funnel`).
- [ ] **Step 4: Jalankan** `vision`: `pytest tests -q -m "not gpu"`; `backend`: `pytest tests -q -m "not gpu and not llm"` — Expected: PASS.
- [ ] **Step 5: CHANGELOG + commit** `feat(vision): corong face worker di heartbeat dan monitoring`.

---

### Task 9: Dokumen, runbook, dan verifikasi akhir

**Files:**
- Modify: `WORKFLOW.md` (§12 Absensi, bagian Telegram dan zona), `ARCHITECTURE.md` (kontrak payload `already_in`/`detected`, heartbeat `funnel`), `docs/runbooks/attendance.md`, `ROADMAP.md` (siklus baru), `CHANGELOG.md`

- [ ] **Step 1: WORKFLOW/ARCHITECTURE:** jelaskan tiga pesan attendance (`CHECK IN/OUT`, `SUDAH CHECK IN`, `TERDETEKSI`), flag zona `record` dan `telegram_unknown`, key payload `first_entry_ts`/`exit_ts`/`match_reason=detected`, dan kunci `funnel`.
- [ ] **Step 2: Runbook `attendance.md`:** (a) ukuran zona: wajah berjalan berada di dalam zona ≥1 detik (≈5 frame pada `ai_fps` 5); (b) checklist kamera: shutter ≥1/250, WDR/BLC bila pintu membelakangi cahaya, setinggi mata sampai sedikit di atasnya, zona 2–4 m sebelum pintu; (c) enrollment dari kamera gate bila skor kurang; (d) cara membaca `funnel` di `/api/v1/monitoring` (penolakan `small` dominan → naikkan `det_size`/dekatkan zona; `yaw`/`blur` dominan → sudut kamera/shutter; `tracks_silent` tinggi → gerbang terlalu ketat); (e) protokol uji penerimaan: 10 karyawan × 5 lintasan jalan normal tanpa menoleh; target ≥95% tercatat benar, ≤2 detik dari wajah muncul sampai event tercatat, nol salah-orang; ulangi setiap perubahan ambang.
- [ ] **Step 3: ROADMAP:** baris siklus baru "Face gate refine" berstatus `[~] kode selesai, belum di-deploy/diuji server`. Jangan menandai `[x]` tanpa bukti server.
- [ ] **Step 4: Verifikasi akhir berurutan** (tempel keluaran di CHANGELOG): `backend` `pytest tests -q -m "not gpu and not llm"`; `vision` `pytest tests -q -m "not gpu"`; `frontend` `npx vitest run`, `npm run build`, `npm run lint` — Expected: semua hijau; jumlah tes naik dari baseline hanya karena tes baru; lint tanpa warning baru.
- [ ] **Step 5: Commit** `docs: face gate refine (alur Telegram, zona deteksi-saja, runbook, corong)`. Berhenti di commit lokal; sesi perencanaan yang review, deploy, dan menjalankan uji penerimaan.

---

## Di luar plan ini

Fase 3b (commit dua fase), penyetelan angka gerbang, layar konfirmasi gate, fusi multi-kamera, dan identifikasi wajah pada intrusion critical. Fase 3b mendapat plan sendiri hanya bila data corong dan uji penerimaan menuntutnya (spec §5.4).
