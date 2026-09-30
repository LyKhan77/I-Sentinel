# Spec — Refining halaman Attendance (tanggal, status tanpa exit/entry, penutupan hari otomatis)

Status: **DISETUJUI di chat (2026-09-30)**, menunggu review spec tertulis.
Branch: `feat/attendance-refine` (dari `main` @ `c22eac5`).
Checkpoint: `.cooper/context/next-features.md`.

---

## 1. Latar

Usulan user: tabel Attendance "kurang bagus — tidak ada data date, hanya waktu"; pertanyaan: bagaimana status &
durasi bila karyawan entry tetapi exit tidak terdeteksi. Pemeriksaan kode menemukan masalah logika selain tampilan.

### Kondisi kode (`main` @ `c22eac5`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Kolom tabel: Karyawan, Shift, Entry, Exit, Durasi, Status — **tanpa tanggal**, padahal API mengirim `date`; tab Rentang / Per karyawan mencampur banyak hari. Urutan API `date ASC, employee_code`. | `frontend/src/features/attendance/AttendancePage.tsx:214`, `backend/app/api/attendance.py` `_query_days` |
| 2 | `compute_status(shift, first_entry, last_exit, now)`: tanpa entry → `absent` (**walau exit ada**); entry tanpa exit → `waiting` sampai `shift.end + no_exit_grace_min (60)` lalu `no_exit`; tanpa shift → `waiting` selamanya. | `backend/app/services/attendance.py:36-55` |
| 3 | Status **disimpan** saat `recompute_day` — hanya dipanggil saat ada event baru atau `close_days`. `close_days` hanya endpoint manual `/internal/maintenance/close-days` (default kemarin) — **tidak pernah dijadwalkan**. Akibat: entry tanpa exit tetap `waiting` ("MENUNGGU", durasi "berjalan…") berhari-hari; karyawan yang tidak datang tidak punya baris → "Tidak hadir" selalu 0. | `attendance.py:58-94, 208-217`, `api/attendance.py:216-225` |
| 4 | `recompute_day` menimpa waktu/status baris yang sudah dikoreksi manual (hanya `override_note` yang dipertahankan). | `attendance.py:58` |
| 5 | Shift tidak boleh lintas hari (`end_time > start_time` divalidasi). | `backend/app/schemas/employee.py:46` |
| 6 | Pola thread latar + stop rapi di lifespan: `NodeHealthMonitor`, `HistorySampler`; conftest mematikan interval monitor. | `services/node_health.py`, `services/monitoring_history.py`, `tests/conftest.py` |
| 7 | CSV export/import memakai `compute_status`; `VALID_STATUSES` untuk PATCH override. | `api/attendance.py` |

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Entry tanpa exit setelah batas → status **"Tanpa exit — perlu koreksi"**, durasi **tidak dihitung**; admin mengoreksi manual. |
| K2 | Karyawan aktif terjadwal kerja tanpa deteksi apa pun → baris **"Tidak hadir" otomatis** setelah batas. |
| K3 | Tab Rentang / Per karyawan: **tabel datar dengan kolom Tanggal**, urut terbaru. |

## 3. Desain

### 3.1 Status

| `status` | Kondisi | `duration_min` | Label (id) |
|---|---|---|---|
| `ontime` / `late` | entry + exit | exit − entry | Tepat waktu / Telat N mnt |
| `waiting` | entry, tanpa exit, `now < batas` (atau karyawan tanpa shift) | `null` (UI hitung live untuk hari ini) | **Di dalam** |
| `no_exit` | entry, tanpa exit, `now ≥ batas` | `null` | **Tanpa exit — perlu koreksi** |
| **`no_entry`** (baru) | tanpa entry, ada exit | `null` | **Tanpa entry — perlu koreksi** |
| `absent` | tanpa entry & exit, hari kerja shift, `now ≥ batas` | `null` | **Tidak hadir** |

- `batas = tanggal hari itu + shift.end_time + settings.no_exit_grace_min`.
- `no_entry`: `late_minutes = null` (tidak bisa dinilai telat).
- `compute_status` diubah: `first_entry is None and last_exit is not None` → `("no_entry", None, None)`.
- `VALID_STATUSES` + frontend `AttendanceStatus` menambah `no_entry`.

### 3.2 Status efektif saat dibaca

`attendance.effective_status(row, shift, now) -> str`: bila `row.status == "waiting"`, `row.override_note` kosong,
karyawan punya shift, dan `now ≥ batas(row.date)` → `"no_exit"`; selain itu `row.status`. Dipakai `_row_dict` (list
API) dan export CSV — tampilan benar walau job belum jalan. Baris yang dikoreksi tidak diubah.

### 3.3 Penutupan hari otomatis

- `attendance.close_due(db, now=None, days_back=7) -> dict` (`{"no_exit": n, "absent": n}`): untuk setiap tanggal
  `d` di `[today − days_back, today]` dan setiap karyawan **aktif ber-shift** dengan `d.isoweekday() in shift.workdays`
  dan `now ≥ batas(d)`:
  - baris `AttendanceDay(employee, d)` belum ada → `recompute_day(db, emp.id, d, now)` (hasil `absent` bila tanpa event,
    atau status dari event yang ada — mis. event tertunda);
  - baris ada, `status == "waiting"`, `override_note` kosong → `recompute_day` (→ `no_exit` / selesai bila exit baru);
  - baris dengan `override_note` → **tidak disentuh**.
  Tidak membuat baris untuk hari libur shift, karyawan nonaktif, atau karyawan tanpa shift.
- `AttendanceCloser` (thread, pola `NodeHealthMonitor`): tiap **15 menit** (`CLOSE_INTERVAL_S = 900`); run pertama
  **segera saat start** (catch-up 7 hari), lalu per interval; sesi DB sendiri; exception dicatat tanpa mematikan
  thread; stop rapi di lifespan. Conftest menonaktifkan (interval panjang + tanpa run awal di tes).
- `close_days(db, day)` tetap (endpoint manual) tetapi ikut aturan override: baris ber-`override_note` dilewati.
- `recompute_day` saat **event baru** tetap menghitung ulang (perilaku lama) — koreksi manual yang kemudian ditimpa
  event baru di luar scope (dicatat).

### 3.4 API

- `GET /api/v1/attendance`: urutan **`date DESC`, lalu nama karyawan**; `status` = status efektif (§3.2).
- Export CSV: status efektif; `duration_min` kosong untuk `no_exit` / `no_entry` / `absent` (sudah `null`).
- Import CSV & PATCH override: menerima `no_entry`.
- Tidak ada endpoint baru; tidak ada migrasi.

### 3.5 Frontend (`AttendancePage.tsx`)

- **Kolom Tanggal** (paling kiri) di tab Rentang dan Per karyawan: format lokal pendek, mis. **"Sen, 29 Sep"**
  (`toLocaleDateString(locale, {weekday: 'short', day: 'numeric', month: 'short'})`, tahun ditambahkan bila bukan
  tahun berjalan). Tab Harian: tanggal di judul tabel/filter, tanpa kolom.
- **Entry / Exit**: `HH:MM` (detik dibuang), judul kolom **"Entry (WIB)" / "Exit (WIB)"** — zona dari
  `Intl.DateTimeFormat().resolvedOptions()` tidak dipakai; tampilkan singkatan tetap `WIB` dari i18n (server WIB).
- **Durasi**: `8j 12m`; status `waiting` dan tanggal = hari ini → **"3j 10m · berjalan"** dihitung dari `first_entry`
  ke sekarang, diperbarui tiap 60 s; `waiting` bukan hari ini (tanpa shift) → "—"; `no_exit` / `no_entry` / `absent`
  → "—".
- **Status badge** (warna konsisten tema): ontime `#42be65`, late `#f1c21b`, waiting "Di dalam" `#4589ff`,
  no_exit & no_entry "perlu koreksi" `#ff832b`, absent `#fa4d56`.
- **Tombol "Koreksi"** di sel status untuk `no_exit` / `no_entry` (hanya admin) → membuka modal override yang sudah
  ada (baris lain tetap bisa diklik seperti sekarang).
- **Penanda dikoreksi**: ikon kecil (Carbon `Edit`/`UserActivity` 16) + tooltip/`title` berisi `override_note` untuk
  baris dengan catatan.
- **Tile ringkasan (tab Harian)**: Hadir (ontime+late, sub tepat waktu · telat), **Di dalam**, **Perlu koreksi**
  (no_exit + no_entry), **Tidak hadir**, Telat terlama (tile yang ada dipertahankan). Tile bisa **diklik sebagai
  filter** status (klik lagi = semua); filter aktif ditandai.
- **Filter status** juga tersedia di tab Rentang / Per karyawan (chip `lv-chip`: Semua, Hadir, Di dalam, Perlu
  koreksi, Tidak hadir).
- Modal override: pilihan status menambah `no_entry`.
- i18n id + en untuk semua label baru; 390 px tanpa overflow horizontal halaman (tabel dalam `TableContainer` bisa
  scroll).

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| Job gagal (DB error) | Dicatat; thread tetap; dicoba lagi 15 menit kemudian; tampilan tetap benar via status efektif |
| API restart | Catch-up 7 hari saat start |
| Karyawan tanpa shift | Tidak pernah `absent` / `no_exit`; entry tanpa exit tetap "Di dalam" (hari ini) / "—" durasi (hari lalu) |
| Baris dikoreksi manual | Tidak diubah job maupun status efektif |
| Event absensi datang terlambat (antrean node) | `recompute_day` saat event → status benar |
| Shift diubah setelah hari lewat | Batas dihitung dari shift saat evaluasi (diterima) |

## 5. Pengujian

- **Backend**: `compute_status` `no_entry`; `effective_status` (waiting lewat batas → no_exit; override → tetap;
  tanpa shift → tetap); `close_due` (absent dibuat hanya hari kerja & setelah batas; tidak untuk nonaktif/tanpa
  shift/libur; waiting → no_exit; override dilewati; catch-up 7 hari; idempoten dua kali jalan; hari ini sebelum
  batas tidak dibuat); `close_days` melewati override; list API urut `date DESC` + status efektif; CSV status
  efektif; PATCH/import menerima `no_entry`; thread start/stop + tahan error.
- **Frontend**: kolom Tanggal hanya di tab Rentang/Per karyawan dengan format "Sen, 29 Sep"; Entry/Exit `HH:MM`;
  durasi live hari ini (fake timers) dan "—" untuk perlu koreksi; label & warna status baru termasuk `no_entry`;
  tombol Koreksi hanya admin & hanya baris perlu koreksi; ikon dikoreksi + tooltip; tile Perlu koreksi dan filter
  klik tile / chip; 390 px.
- Baseline `main` `c22eac5`: backend 606, vision 233 (3 deselected), frontend 237, build 0.

## 6. Verifikasi lapangan (butuh izin user)

Deploy: pull + restart API (tanpa migrasi) + HMR. Cek: hari-hari lama yang "MENUNGGU" berubah "Tanpa exit — perlu
koreksi" setelah start; karyawan terjadwal yang tidak datang muncul "Tidak hadir"; tab Rentang menampilkan kolom
Tanggal; koreksi satu baris "Tanpa exit" → status/durasi sesuai input dan tidak ditimpa job.

## 7. Di luar scope

Shift lintas hari, izin/cuti/sakit/libur nasional, lembur, notifikasi "perlu koreksi", melindungi koreksi manual dari
event baru, pengaturan `no_exit_grace_min` dari UI.

## 8. Rollback

`git revert` merge + restart API + build frontend. Baris `absent` / `no_exit` yang dibuat job tetap ada (data
turunan; bisa dihapus lewat cleanup "Data absensi" bila perlu); nilai status `no_entry` akan tampil sebagai teks mentah
di UI lama.
