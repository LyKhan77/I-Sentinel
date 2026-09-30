# Cleanup data absensi (rekap & riwayat) — Implementation Plan

**Goal:** Tambah mode `attendance_data` ke card "Bersihkan event" (Storage) supaya admin bisa
menghapus permanen `attendance_event`, `attendance_day` (termasuk `override_note`), event Inbox
absensi terkait, dan file medianya untuk karyawan terpilih (atau semua) pada rentang tanggal, dengan
pratinjau wajib dan konfirmasi mengetik `HAPUS`.

**Spec:** `docs/superpowers/specs/2026-09-30-attendance-data-cleanup-design.md`

**Branch:** `feat/attendance-data-cleanup` (stack di atas `feat/inbox-alert-realtime` @ `c7598d2`).

## Constraints

- Tanpa AI attribution di commit/kode/docs (`AGENTS.md` §9).
- Tanpa dependensi baru, tanpa migrasi DB.
- Reuse helper `retention.py` yang ada (`_range_query`, `_chunks`, `_delete_events`, `_safe_join`,
  `_remove_files`, `_media_fields`) — pola sama dengan `cleanup_attendance_media`.
- `date_to` mode ini ≤ kemarin (bukan hari ini) — shift hari ini masih bisa berjalan.
- Audit log: ID karyawan saja, tidak pernah nama.
- Baris dihapus dalam satu transaksi (alert → event → attendance_event → attendance_day) sebelum
  file dihapus dari disk.
- `dry_run` tidak boleh mengubah apa pun.
- Baseline branch ini (`feat/inbox-alert-realtime` @ `c7598d2`): backend 597 passed, frontend 232
  passed, build 0, lint 0 error baru.
- Eksekutor berhenti setelah commit lokal (tidak push/merge/deploy sesuai instruksi tugas).

## Tasks

1. **Backend schema + validasi** — `CleanupIn` (`employee_ids`, `all_employees`, mode literal baru) +
   validator 422 sesuai brief. Test: `test_storage_api.py` / `test_storage_cleanup.py`.
2. **Backend service** — `retention.cleanup_attendance_data(...)` + dispatch di `retention.cleanup`.
   Test baru: `backend/tests/test_attendance_data_cleanup.py`.
3. **Backend API + audit log** — `POST /storage/cleanup` meneruskan `employee_ids`/`all_employees`,
   log baris `attendance data cleanup by %s: ...` (ID saja). Test: viewer 403, log tanpa nama.
4. **Frontend api client** — `api/storage.ts` (`CleanupMode`, `CleanupFilter`, `CleanupResult`).
5. **Frontend UI** — `EventCleanupCard.tsx` mode ketiga: employee `MultiSelect` + checkbox "Semua
   karyawan", tanggal `max` = kemarin, tabel per-karyawan, modal konfirmasi ketik `HAPUS`.
6. **i18n** — kunci baru id+en di `i18n.tsx`.
7. **Docs** — `docs/runbooks/storage-retention.md`, `README.md` Storage, `CHANGELOG.md`.

Setiap task: TDD (test gagal dulu → implementasi → test lulus) lalu commit Conventional Commits
Indonesia terpisah.

## Review focus

1. Karyawan lain di rentang yang sama — barisnya tidak boleh ikut terhapus.
2. Batas tanggal lokal (23:59 `date_to` terhapus, 00:00 hari berikutnya tetap).
3. `all_employees=true` menghapus event wajah-tak-dikenal juga; dengan filter karyawan, tidak.
4. File yang dirujuk baris DI LUAR seleksi tetap ada di disk.
5. `dry_run=true` tidak mengubah jumlah baris/file sama sekali.
6. Log audit memuat ID + angka, tidak memuat nama karyawan (cek `caplog`).
