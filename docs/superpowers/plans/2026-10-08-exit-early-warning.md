# Exit Early Warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rekap attendance menandai baris `ontime`/`late` yang `last_exit`-nya lebih dari 60 menit sebelum shift selesai, tanpa mengubah status.

**Architecture:** Peringatan dihitung saat baca (pola `effective_status`): fungsi murni `exit_early_min` di `services/attendance.py`, field `exit_early_min` di `_row_dict` dan kolom terakhir CSV, chip di sel exit halaman Attendance. Tanpa migrasi dan tanpa setelan baru.

**Tech Stack:** Python 3.11 (FastAPI, SQLAlchemy, pytest), React 19 + Carbon + Vitest.

**Spec:** `docs/superpowers/specs/2026-10-08-exit-early-warning-design.md` (baca dulu; plan memakai nomor bagian spec). Branch: `feat/exit-early-warning`.

## Global Constraints

- `EXIT_EARLY_MIN = 60`; selisih **lebih dari** 60 menit (tepat 60 → `None`, 61 → 61). Hasil dalam menit bulat (`round`).
- Status, `compute_status`, `recompute_day`, `AttendanceCloser`, tile ringkasan, filter, dan Telegram **tidak berubah**.
- `exit_early_min` hanya untuk status tersimpan `ontime`/`late`, `override_note` kosong (setelah `strip`), shift ada, `last_exit` ada, waktu baca ≥ `shift.end_time` pada `row.date` (lokal), dan `last_exit` sebelum shift selesai.
- CSV: kolom `exit_early_min` hanya di **akhir** `CSV_COLUMNS`; impor tidak diubah (membaca per nama kolom).
- Frontend: semua string lewat `src/app/i18n.tsx` (`id` dan `en`); Carbon + gaya inline seperti `StatusBadge`; tipe `exit_early_min?: number | null` (opsional supaya fixture tes lama tetap valid).
- Commit Conventional Commits, satu per task, **tanpa atribusi AI** (AGENTS.md §9; abaikan trailer `Co-Authored-By` bawaan). Jangan `push`.
- Tiap task menambah satu entri `CHANGELOG.md` (terbaru di atas; format entri yang ada) dalam commit yang sama.
- Jangan `uv sync`, `uv lock`, atau membuat ulang venv. Suite berurutan. Backend: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu and not llm"`; frontend: `cd frontend && env -u NODE_ENV npx vitest run`, `npm run build`, `npm run lint`.
- Deploy dan verifikasi server di luar plan ini. Keluaran uji mentah ke `temp/logs/exit-early-warning/`, bukan `temp/prompt/`.

## Pre-flight

- [ ] Ukur baseline berurutan dan simpan ke `temp/logs/exit-early-warning/baseline-*.txt`: backend (acuan perencana `896 passed, 1 deselected`), frontend vitest (`36 files / 483 passed`), build (exit 0), lint (acuan `24 warnings`; tidak ada baseline lint tersimpan, ukur sendiri). Tempel angka di CHANGELOG Task 1.

## Review Focus

1. Batas tepat 60 menit (`None`) dan 61 (`61`). (Task 1)
2. Waktu baca **sebelum** shift selesai pada hari yang sama: `None`; hari yang sudah lewat: dihitung. (Task 1)
3. Baris ber-`override_note` (termasuk `"import"`) dan status selain `ontime`/`late`: `None`. (Task 1)
4. Impor CSV hasil ekspor (kolom tambahan) dan CSV lama tanpa kolom itu tetap berjalan. (Task 1)
5. Fixture frontend lama tanpa field `exit_early_min`: tidak ada chip dan tidak error. (Task 2)

## File Structure

- Modify: `backend/app/services/attendance.py`, `backend/app/api/attendance.py`.
- Modify tests: `backend/tests/test_attendance_logic.py`, `backend/tests/test_attendance_api.py`, `frontend/src/__tests__/attendance.test.tsx`.
- Modify: `frontend/src/api/attendance.ts`, `frontend/src/features/attendance/AttendancePage.tsx`, `frontend/src/app/i18n.tsx`.
- Modify docs: `WORKFLOW.md` §12, `ARCHITECTURE.md`, `docs/runbooks/attendance.md`, `ROADMAP.md`, `CHANGELOG.md`.

---

### Task 1: Backend — `exit_early_min`, field API, kolom CSV

**Files:**
- Modify: `backend/app/services/attendance.py` (dekat `effective_status`, lines 67-73), `backend/app/api/attendance.py` (`CSV_COLUMNS` line 24, `_row_dict` lines 60-74, `export_csv` lines 119-127)
- Test: `backend/tests/test_attendance_logic.py`, `backend/tests/test_attendance_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `attendance.EXIT_EARLY_MIN: int = 60`.
- Produces: `attendance.exit_early_min(row, shift, now: datetime | None = None) -> int | None` — syarat dan perhitungan persis di Global Constraints (`end = _shift_dt(shift, row.date, shift.end_time)`; `now = _local(now) or datetime.now(LOCAL_TZ)`; hasil `gap = round((end - _local(row.last_exit)).total_seconds() / 60)`, dikembalikan bila `gap > EXIT_EARLY_MIN`).
- Produces: `_row_dict(...)["exit_early_min"]` (`int | None`); `CSV_COLUMNS[-1] == "exit_early_min"`; sel CSV kosong bila `None`.

- [ ] **Step 1: Tulis tes yang gagal**
  - `test_attendance_logic.py` — `SimpleNamespace` untuk `row` (`date`, `last_exit`, `status`, `override_note`) dan shift (`end_time="16:00"`), `now=_at(*MON, 17, 0)`:
    - `test_exit_early_min_reports_minutes_before_shift_end`: `last_exit=_at(*MON, 12, 3)`, status `late` → `237`.
    - `test_exit_early_min_boundary_is_strictly_more_than_60`: 15:00 → `None`; 14:59 → `61`.
    - `test_exit_early_min_waits_for_shift_end`: `now=_at(*MON, 14, 0)` → `None`; `now` hari berikutnya → `237`.
    - `test_exit_early_min_none_when_not_applicable`: parametrisasi: `override_note="x"` dan `"import"`; status `waiting`, `no_exit`, `no_entry`, `absent`; shift `None`; `last_exit=None`; `last_exit=_at(*MON, 16, 30)` → semua `None`.
  - `test_attendance_api.py` (pakai `_fixture_employee` + `_export` yang ada; `DAY` sudah lewat; fixture membuat exit 16:05 sehingga ubah `AttendanceDay.last_exit` ke 12:03 pada baris yang dibuat `recompute_day`):
    - `test_list_exposes_exit_early_min`: baris dengan `last_exit` 12:03 → `exit_early_min == 237`; baris default (16:05) → `None`.
    - `test_csv_export_has_exit_early_min_as_last_column`: header terakhir `exit_early_min`; nilai `237` untuk baris di atas dan kosong untuk baris lain.
    - `test_import_ignores_exit_early_min_column`: ekspor → ubah nilai kolom itu menjadi `999` → impor → baris tidak berubah dan `skipped == 0` (Review Focus 4); impor CSV lama (header tanpa kolom itu) tetap lulus (tes impor yang ada).
    - `test_patch_with_note_clears_exit_early_min`: `PATCH` catatan pada baris ber-`exit_early_min` → respons `exit_early_min is None` (Review Focus 3).
- [ ] **Step 2: Jalankan** `cd backend && .venv/bin/python -m pytest tests/test_attendance_logic.py tests/test_attendance_api.py -q` — Expected: FAIL (`exit_early_min` belum ada / `KeyError`), bukan galat impor.
- [ ] **Step 3: Implementasi** sesuai Interfaces.
- [ ] **Step 4: Jalankan** seluruh suite backend — Expected: PASS; jumlah naik hanya karena tes baru.
- [ ] **Step 5: CHANGELOG + commit** `feat(attendance): peringatan exit awal pada rekap (API dan CSV)`.

---

### Task 2: Frontend — chip "Exit awal"

**Files:**
- Modify: `frontend/src/api/attendance.ts` (`AttendanceRow`), `frontend/src/features/attendance/AttendancePage.tsx` (sel exit, lines 469-470), `frontend/src/app/i18n.tsx` (dekat `at.duration.hm`, `id` line 657 dan `en`)
- Test: `frontend/src/__tests__/attendance.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: field API `exit_early_min` (Task 1).
- Produces: `AttendanceRow.exit_early_min?: number | null`; chip `data-testid={`exit-early-${r.id}`}` di sel exit di bawah jam, hanya bila `r.exit_early_min != null`; teks = `t('at.exitEarly').replace('{d}', t('at.duration.hm').replace('{h}', String(Math.floor(n / 60))).replace('{m}', String(n % 60)))`; kunci i18n `at.exitEarly`: `id` `Exit {d} sebelum shift selesai`, `en` `Exit {d} before shift end`; warna amber `#f1c21b`, ukuran font 11 seperti `StatusBadge`.

- [ ] **Step 1: Tulis tes yang gagal** (ikuti pola `stubFetch`/`renderPage` yang ada; salin `ROWS[1]` dengan `{ ...ROWS[1], exit_early_min: 237 }`):
  - `chip Exit awal tampil dengan durasi bila exit_early_min terisi`: teks persis `Exit 3j 57m sebelum shift selesai` pada `exit-early-12`.
  - `chip Exit awal tidak tampil bila null atau tidak ada`: baris ROWS asli (tanpa field) dan baris dengan `exit_early_min: null` → `queryByTestId('exit-early-…')` kosong (Review Focus 5).
- [ ] **Step 2: Jalankan** `cd frontend && env -u NODE_ENV npx vitest run src/__tests__/attendance.test.tsx` — Expected: FAIL tes pertama (chip belum ada); tes kedua boleh lulus sejak awal (penjaga).
- [ ] **Step 3: Implementasi** sesuai Interfaces.
- [ ] **Step 4: Jalankan** `env -u NODE_ENV npx vitest run && npm run build && npm run lint` — Expected: PASS, build exit 0, lint tanpa warning baru dibanding baseline pre-flight.
- [ ] **Step 5: CHANGELOG + commit** `feat(attendance): chip Exit awal pada halaman Attendance`.

---

### Task 3: Dokumen dan verifikasi akhir

**Files:**
- Modify: `WORKFLOW.md` §12, `ARCHITECTURE.md`, `docs/runbooks/attendance.md`, `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: WORKFLOW §12:** tambahkan butir rekap: baris selesai yang exit terakhirnya lebih dari 60 menit sebelum shift selesai diberi chip **Exit awal**; status tidak berubah; admin memutuskan lewat **Koreksi** (catatan menghilangkan peringatan).
- [ ] **Step 2: ARCHITECTURE:** field API `exit_early_min` (semantik, syarat, ambang 60 menit) dan kolom terakhir CSV `exit_early_min`; tanpa migrasi.
- [ ] **Step 3: Runbook `attendance.md` (bagian Status/Koreksi):** arti peringatan (pulang awal **atau** exit sore tidak terlihat; sistem tidak bisa membedakan), cara menindaklanjuti (cek Inbox/event exit, lalu Koreksi bila perlu), dan bahwa exit berulang tetap membuat `last_exit` = exit terakhir.
- [ ] **Step 4: ROADMAP:** baris siklus `[~] kode selesai, belum di-deploy/diuji server` dengan angka tes nyata. Jangan `[x]`.
- [ ] **Step 5: Verifikasi akhir berurutan** (log mentah ke `temp/logs/exit-early-warning/`) dan tempel ringkasannya di CHANGELOG: backend `896 +` tes baru semua lulus; vitest `483 +` tes baru; build exit 0; lint 24 warning dengan pasangan sama; docker tests tidak tersentuh (`pytest docker/tests -q` tetap `76 passed`); `git diff --stat main...HEAD` hanya berkas di File Structure + spec/plan; `git diff main...HEAD -- vision docker backend/alembic` kosong.
- [ ] **Step 6: Commit** `docs: peringatan exit awal (alur rekap, API, runbook)`. Berhenti di commit lokal.

---

## Di luar plan ini

Status baru, pencatatan semua sesi dan jam kerja bersih, filter atau tile "exit awal", setelan ambang di UI/env, perubahan Telegram, deploy, dan verifikasi server.
