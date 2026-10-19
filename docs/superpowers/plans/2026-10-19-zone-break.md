# Zone Break (Waktu Istirahat per Zona) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zona dengan jadwal "Jam tertentu" atau "Ikut shift" dapat punya jendela istirahat sendiri, dan semua tipe zona berhenti mengevaluasi selama jendela itu.

**Architecture:** Istirahat disimpan di dalam `zone.schedule` (JSON yang sudah ada) sebagai `breaks`. Backend memvalidasi dan menyalinnya ke config node; node mengeceknya lewat fungsi baru `break_active()` yang dipakai bersama oleh `schedule_active()` (analyzer jadwal penuh) dan `FaceGateWorker` (hanya istirahat). Tanpa migrasi dan tanpa perubahan pada Shift.

**Tech Stack:** FastAPI + Pydantic v2 + pytest (backend), Python vision node + pytest, React 19 + Carbon + Vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-10-19-zone-break-design.md` (baca dulu; plan ini mengikutinya)

## Global Constraints

- Bentuk data: `{"days","start","end","breaks":[{"start","end"}]}` atau `{"shift_id":N,"breaks":[...]}`. `breaks` opsional; tidak ada atau `[]` = tanpa istirahat. Bentuk `{"breaks": ...}` tanpa `days`/`shift_id` ditolak.
- Tiap istirahat: dict persis `{start, end}`, format `HH:MM` (aturan waktu yang sama dengan `start`/`end` zona), `start < end` (bandingan string), maksimal 5 per zona.
- Jendela istirahat setengah terbuka: `start <= HH:MM < end` pada waktu dinding lokal (`wall_time`). Tidak ada validasi silang terhadap jam kerja atau shift.
- Tanpa migrasi Alembic, tanpa perubahan model/API/UI Shift, tanpa perubahan perhitungan absensi.
- Gate absensi hanya memanggil `break_active()`, tidak `schedule_active()`; jam kerja tidak ditegakkan di gate.
- Node lama mengabaikan `breaks` (jangan memecah kontrak config node).
- Frontend: semua teks lewat `src/app/i18n.tsx` (Indonesia dan Inggris), komponen Carbon, tidak ada overflow horizontal di 390 px.
- Tes: backend `pytest tests -q -m "not gpu and not llm"` dari `backend/`; vision `pytest tests -q -m "not gpu"` dari `vision/`; frontend `npx vitest run`, `npm run lint`, `npm run build` dari `frontend/`.
- Commit Conventional Commits per tugas. **Tanpa atribusi AI** di commit, kode, atau dokumen (AGENTS.md §9). Jangan `git push`.
- Tes jam memakai timestamp epoch asli (`datetime(2024, 1, 15, 12, 30).timestamp()` = Senin 12:30; nilai ≥ `MONOTONIC_MAX` dipakai apa adanya oleh `wall_time`).

## Review Focus

1. Dua zona gate pada satu kamera, hanya satu yang istirahat: zona lain tetap mencatat (Task 4).
2. Kamera yang sama menjalankan identitas intrusion (collector): deteksi wajah tidak boleh dilewati saat gate istirahat (Task 4).
3. Mengganti shift, berpindah Jam tertentu ↔ Ikut shift, atau mengubah hari/jam tidak boleh menjatuhkan `breaks`; zona dengan dua istirahat dari server tidak kehilangan yang kedua saat form disimpan (Task 5).
4. Zona "Ikut shift" yang shift-nya sudah dihapus tetap mengirim `schedule = None` tanpa error walau punya `breaks` (Task 1).
5. Batas jendela: tepat `start` (mati), tepat `end` (aktif), dua istirahat, `breaks: []` (Task 2).

---

### Task 1: Backend — validasi `breaks` dan config push

**Files:**
- Modify: `backend/app/schemas/zone.py` (`_validate_schedule`, sekitar baris 82-100)
- Modify: `backend/app/services/config_push.py` (`resolve_schedule`, baris 18-26)
- Test: `backend/tests/test_zones_api.py`, `backend/tests/test_config_push.py`

**Interfaces:**
- Produces: `_validate_schedule(v)` menerima kunci `breaks` opsional pada dua bentuk jadwal dan menolak sisanya (berlaku lewat `ZoneIn` dan `ZonePatch`). `resolve_schedule(db, schedule) -> dict | None` menyalin `breaks` yang tidak kosong ke hasil Ikut shift dan meneruskan jadwal Jam tertentu apa adanya.

- [ ] **Step 1: Tulis tes yang gagal** di `test_zones_api.py` (pakai helper `_behavior_zone` dan pola `test_zone_schedule_follows_shift`):
  - `test_zone_schedule_accepts_breaks`: POST jadwal Jam tertentu dengan `breaks=[{"start":"12:00","end":"13:00"}]` dan jadwal `{"shift_id": sid, "breaks": [...]}` → 200 dan respons mengembalikan `schedule` sama persis.
  - `test_zone_schedule_breaks_invalid_422` (parametrize): `breaks` bukan list; 6 elemen; elemen berkunci asing; `start>=end` ("13:00"/"12:00" dan sama); "12:0"; "24:00"; nilai non-string; `{"shift_id": sid, "foo": 1}`; `{"breaks": [valid]}` tanpa `days`/`shift_id` → semua 422. Satu kasus lewat PATCH memastikan `ZonePatch` ikut menolak.
  Di `test_config_push.py` (pola tes shift baris ~410):
  - `test_config_push_shift_schedule_carries_breaks`: zona `{"shift_id": sh.id, "breaks": [{"start":"12:00","end":"13:00"}]}` → `zone["schedule"] == {"days":[1,2,3,4,5],"start":"08:00","end":"17:00","breaks":[{"start":"12:00","end":"13:00"}]}`; dengan `breaks: []` hasilnya tetap tanpa kunci `breaks`.
  - `test_config_push_hours_schedule_passes_breaks_through`: jadwal Jam tertentu berisi `breaks` diteruskan tanpa ubahan.
  - `test_config_push_missing_shift_with_breaks_sends_null`: shift 424242 + `breaks` → `schedule is None`, tanpa exception.
- [ ] **Step 2: Jalankan** `cd backend && pytest tests/test_zones_api.py tests/test_config_push.py -q -k "break"` → gagal.
- [ ] **Step 3: Implementasi** `_validate_schedule`: izinkan himpunan kunci `{shift_id}`, `{shift_id, breaks}`, `{days,start,end}`, `{days,start,end,breaks}`; ekstrak cek `HH:MM` yang sudah ada menjadi `_is_hhmm(t: str) -> bool` dan pakai ulang untuk `start`/`end`/istirahat; konstanta `BREAKS_MAX = 5`. Implementasi `resolve_schedule`: cabang `shift_id` menambahkan `"breaks"` hanya bila list-nya tidak kosong; shift hilang tetap `None` + peringatan log lama.
- [ ] **Step 4: Jalankan** `cd backend && pytest tests -q -m "not gpu and not llm"` → semua lulus.
- [ ] **Step 5: Commit** `feat(zones): validasi dan kirim istirahat jadwal zona ke node`

---

### Task 2: Vision — `break_active()` dan `schedule_active()`

**Files:**
- Modify: `vision/vision/analyzers/base.py`
- Test: `vision/tests/test_analyzer_base.py`, `vision/tests/test_intrusion.py`

**Interfaces:**
- Produces: `break_active(schedule: dict | None, ts: float) -> bool` — `True` bila ada elemen `schedule["breaks"]` dengan `start <= HH:MM < end` pada `wall_time(ts)`; `False` untuk `None`, tanpa kunci, atau `[]`; tidak memeriksa `days` maupun jam kerja. Harus memanggil `wall_time` lewat nama global modul agar tes bisa memintasnya (`monkeypatch.setattr(base, "wall_time", ...)`). `schedule_active(schedule, ts)` mengembalikan `False` bila `break_active` benar, selain itu perilaku lama.

- [ ] **Step 1: Tulis tes yang gagal** di `test_analyzer_base.py` dengan `WORK = {"days":[1],"start":"08:00","end":"17:00","breaks":[{"start":"12:00","end":"13:00"}]}` pada Senin 2024-01-15:
  - `test_schedule_active_break_boundaries`: 11:59 True, 12:00 False, 12:59 False, 13:00 True.
  - `test_schedule_active_two_breaks_and_empty`: istirahat kedua 15:00–15:15 menutup 15:10; `breaks: []` dan tanpa kunci berperilaku seperti jadwal lama.
  - `test_break_active_ignores_days_and_work_window`: jadwal `days:[2]`, jam kerja 08:00–09:00, break 12:00–13:00 pada Senin 12:30 → `break_active` True; `break_active(None, ts)` False.
  Di `test_intrusion.py`: `test_intrusion_silent_during_break` — zona dengan `schedule=WORK` diam pada 12:30 dan menerbitkan 1 event pada 14:00.
- [ ] **Step 2: Jalankan** `cd vision && pytest tests/test_analyzer_base.py tests/test_intrusion.py -q` → gagal.
- [ ] **Step 3: Implementasi** `break_active` dan sambungkan ke `schedule_active` setelah cek hari dan jam kerja; perbarui docstring (hapus klaim bahwa jadwal hanya hari+jam).
- [ ] **Step 4: Jalankan** `cd vision && pytest tests -q -m "not gpu"` → lulus.
- [ ] **Step 5: Commit** `feat(vision): break_active dan istirahat di schedule_active`

---

### Task 3: Vision — loitering dan running patuh jadwal penuh

**Files:**
- Modify: `vision/vision/analyzers/loitering.py`, `vision/vision/analyzers/running.py`
- Test: `vision/tests/test_loitering.py`, `vision/tests/test_running.py`

**Interfaces:**
- Consumes: `schedule_active(schedule, ts) -> bool` dari Task 2.
- Produces: `LoiteringAnalyzer(zone)` dan `RunningAnalyzer(zone, mpp)` membaca `zone.get("schedule")`; di luar jadwal `on_frame` mengembalikan `[]` dan membuang state per-track yang bisa membocorkan data pra-istirahat. Jadwal `None` = perilaku lama.

- [ ] **Step 1: Tulis tes yang gagal** (pakai helper `zone(**kw)`, `FakeTrack`, `_bbox_standing_at` di `test_loitering.py`; timestamp epoch asli):
  - `test_loitering_silent_outside_schedule_and_during_break`: track diam di dalam 20 dtk dengan `loiter_seconds=15` pada 07:00 (jadwal 08:00–17:00) → tanpa event; pada 12:30 dengan `breaks` 12–13 → tanpa event; pada 09:00 → 1 event (kontrol).
  - `test_loitering_dwell_does_not_carry_across_break`: 10 dtk di dalam sebelum 12:00, frame istirahat, lalu 10 dtk setelah 13:00 → tanpa event (20 dtk bila terbawa).
  - `test_running_silent_outside_schedule_and_during_break`: kecepatan di atas batas pada 12:30 dengan istirahat → tanpa event; pada 14:00 → event.
  - `test_running_speed_does_not_carry_across_break`: bangun EMA kecepatan ≥ 2× batas sebelum 12:00, dua frame lambat setelah 13:00 → tanpa event (tanpa pembuangan state, EMA lama masih di atas batas).
- [ ] **Step 2: Jalankan** `cd vision && pytest tests/test_loitering.py tests/test_running.py -q` → gagal.
- [ ] **Step 3: Implementasi** `self.schedule = zone.get("schedule")` dan penjaga di awal `on_frame` (urutan: cek jadwal sebelum cek `loiter_seconds`/`speed_limit_mps`). Saat off-window: loitering membuang `_dwell` dan `_last_ts` (mempertahankan `_emitted`, sama pola `intrusion`), running membuang `_last` dan `_speed`.
- [ ] **Step 4: Jalankan** `cd vision && pytest tests -q -m "not gpu"` → lulus.
- [ ] **Step 5: Commit** `feat(vision): loitering dan running patuh jadwal zona`

---

### Task 4: Vision — gate absensi patuh istirahat

**Files:**
- Modify: `vision/vision/face_worker.py` (`FaceGateWorker._process`, `_gate_unified`)
- Test: `vision/tests/test_face_worker.py` (referensi kolektor: `vision/tests/test_intrusion_face_workers.py`)

**Interfaces:**
- Consumes: `break_active(schedule, ts)` dari Task 2.
- Produces: per frame, zona yang sedang istirahat (`break_active(zone.get("schedule"), frame.ts)`) dikeluarkan dari daftar zona untuk `gate_code`/`_gate_unified`; state `_states` dan `_in_zone` milik track pada zona itu dibuang tanpa dikirim. Bila semua zona istirahat dan `self.collector is None`, deteksi wajah dilewati sepenuhnya. Jika `collector` ada, deteksi tetap jalan. Zona tanpa `breaks` dan jam kerja apa pun tidak berubah perilakunya.

- [ ] **Step 1: Tulis tes yang gagal** (tes mengendalikan jam dengan `monkeypatch.setattr("vision.analyzers.base.wall_time", ...)`; perlu sumber yang menghasilkan `Frame(ts, data)` eksplisit seperti `StalledSource` di file yang sama; `ZONE` diberi `schedule` lewat `{**ZONE, "schedule": ...}`):
  - `test_gate_in_break_emits_nothing_and_skips_detection`: 5 frame wajah bagus saat istirahat → `t.events == []`, `eng.embed_calls == 0`, dan `len(eng.per_frame) == 5` (deteksi tidak dipanggil). Kontrol: jam di luar istirahat → 1 event.
  - `test_gate_ignores_work_window`: jadwal `{"days":[1],"start":"08:00","end":"17:00"}` tanpa `breaks` pada Minggu 20:00 → tetap 1 event.
  - `test_gate_break_drops_pending_candidate`: 2 frame bagus sebelum istirahat, lalu frame istirahat dan frame kosong sesudahnya → tidak ada event sama sekali.
  - `test_gate_break_beats_test_mode`: zona dengan `delivery="test"` (lihat tes Mode uji di file ini) saat istirahat → `embed_calls == 0`.
  - `test_gate_two_zones_only_one_in_break`: dua zona dengan poligon berbeda pada satu kamera, A istirahat, B tidak; wajah di B → event B; wajah di A → tidak ada event.
  - `test_gate_break_keeps_identity_collector_detecting`: worker dengan `registry=IntrusionRegistry()` saat gate istirahat → `detect_faces` tetap dipanggil (`per_frame` habis) tetapi tidak ada event absensi.
- [ ] **Step 2: Jalankan** `cd vision && pytest tests/test_face_worker.py -q -k "gate"` → gagal.
- [ ] **Step 3: Implementasi** di `_process` (struktur diserahkan ke implementer asal syarat Interfaces terpenuhi). `run()` tetap menghitung `frames`/heartbeat seperti biasa.
- [ ] **Step 4: Jalankan** `cd vision && pytest tests -q -m "not gpu"` → lulus.
- [ ] **Step 5: Commit** `feat(vision): gate absensi berhenti saat jendela istirahat zona`

---

### Task 5: Frontend — editor istirahat di halaman Zona

**Files:**
- Modify: `frontend/src/api/zones.ts` (tipe `Schedule`, `ZoneSchedule`), `frontend/src/features/config/ZonesPage.tsx` (blok jadwal ~baris 456-515, tombol simpan ~718), `frontend/src/app/i18n.tsx` (blok `zones.*` Indonesia ~555 dan Inggris ~1564)
- Test: `frontend/src/__tests__/zones.test.tsx` (pola `selectZone`, `patchBody`, tes "jadwal Ikut shift mengirim shift_id")

**Interfaces:**
- Produces: `export type Break = { start: string; end: string }`; `Schedule` mendapat `breaks?: Break[]` dan `ZoneSchedule` varian `{ shift_id: number; breaks?: Break[] }`. Kunci i18n baru: `zones.breaks` (Istirahat (opsional) / Break (optional)), `zones.breakAdd` (Tambah istirahat), `zones.breakStart`, `zones.breakEnd`, `zones.breakRemove` (Hapus istirahat), `zones.breakInvalid`.
- Perilaku: bagian Istirahat tampil hanya untuk Jam tertentu dan Ikut shift. Satu baris per `breaks` yang ada (dua `TextInput` + tombol hapus); tombol "Tambah istirahat" tampil hanya bila `breaks` kosong dan mengisi 12:00–13:00 *(keputusan saya)*. Baris tidak valid (kosong, bukan `HH:MM`, atau `start >= end`) memberi `invalid` + `breakInvalid` dan menonaktifkan `zone-save`. Payload tidak pernah memuat baris tidak valid; `breaks` kosong tidak dikirim. Semua penulisan ulang `schedule` (ganti shift, ganti mode, hari/jam) membawa `breaks`; 24/7 menyetel `null`.

- [ ] **Step 1: Tulis tes yang gagal** di `zones.test.tsx`:
  - `jadwal Jam tertentu mengirim istirahat`: dari 24/7 pilih Jam tertentu, klik Tambah istirahat, simpan → `patchBody(fetchMock).schedule.breaks` sama dengan `[{ start: '12:00', end: '13:00' }]`.
  - `jadwal Ikut shift mengirim shift_id dan istirahat`: seperti tes shift yang ada, plus istirahat → `schedule` sama dengan `{ shift_id: 3, breaks: [{ start: '12:00', end: '13:00' }] }`.
  - `berpindah mode mempertahankan istirahat`: Jam tertentu + istirahat → pilih Ikut shift → `schedule.breaks` tetap.
  - `memilih 24/7 menghapus jadwal dan istirahat`: simpan → `schedule` sama dengan `null`.
  - `istirahat tidak valid memblokir simpan`: ubah selesai menjadi sebelum mulai → tombol `zone-save` disabled dan teks `breakInvalid` tampil.
  - `zona dengan dua istirahat tetap utuh saat disimpan`: zona fixture berjadwal dua istirahat, ubah field lain, simpan → `schedule.breaks` keduanya sama persis.
- [ ] **Step 2: Jalankan** `cd frontend && npx vitest run src/__tests__/zones.test.tsx` → gagal.
- [ ] **Step 3: Implementasi** tipe, kunci i18n (kedua bahasa), dan UI di `ZonesPage.tsx`; ganti tiga tempat yang menulis ulang `schedule` (pemilih mode, `onChange` shift, tag hari/jam yang sudah menyebar `...selected.schedule`) agar membawa `breaks`.
- [ ] **Step 4: Jalankan** `cd frontend && npx vitest run && npm run lint && npm run build` → semua lulus.
- [ ] **Step 5: Commit** `feat(frontend): editor istirahat jadwal zona`

---

### Task 6: Dokumentasi, runbook rollout, verifikasi akhir

**Files:**
- Modify: `WORKFLOW.md` (§6 jadwal zona; catatan gate hanya patuh istirahat dan jam kerja tidak berlaku di gate; Mode uji tunduk pada istirahat; cara 24/7 + istirahat = Jam tertentu 00:00–23:59; batas: karyawan yang tiba saat gate istirahat tidak tercatat), `ARCHITECTURE.md` (semantik jadwal, bentuk `schedule.breaks`, analyzer yang patuh jadwal), `ROADMAP.md`, `CHANGELOG.md` (konteks, file, bukti tes, dampak, rollback; tanpa nama karyawan atau ID event), `README.md` bila memuat daftar fitur jadwal
- Create: `docs/runbooks/zone-break-rollout.md`

**Interfaces:** tidak ada.

- [ ] **Step 1: Tulis runbook** `zone-break-rollout.md`: kueri `SELECT id, name, type, schedule FROM zone WHERE schedule IS NOT NULL` dan cara meninjau zona gate/loitering/running ber-jadwal bersama user sebelum deploy; urutan API → node; langkah rollback (hapus kunci `breaks` via editor atau SQL bila perlu setelah rollback API); verifikasi live di sekitar batas istirahat (belum diuji di kamera nyata).
- [ ] **Step 2: Perbarui dokumen** daftar Files di atas; perbaiki catatan lama yang menyebut jadwal hanya berlaku untuk sebagian analyzer.
- [ ] **Step 3: Verifikasi akhir** dan tempel hasilnya di `CHANGELOG.md`: `cd backend && pytest tests -q -m "not gpu and not llm"`, `cd vision && pytest tests -q -m "not gpu"`, `cd frontend && npx vitest run && npm run lint && npm run build`. Semua harus lulus.
- [ ] **Step 4: Commit** `docs(zones): istirahat jadwal zona, runbook rollout, changelog`. Berhenti di commit; jangan push (merge, deploy, dan uji server dikerjakan di sesi perencanaan).
