# Spec — Enrollment & Shift refining

Status: **DISETUJUI di chat (2026-09-23)**, menunggu review spec tertulis.
Branch: `feat/enrollment-refining` (dari `main` @ `ea8cd3c`, sudah memuat R5a + R5b).
Checkpoint: `.cooper/context/enrollment-refining.md`.

---

## 1. Latar

Permintaan user: *"pada fitur Enrollment perlu refining. CRUD untuk Shift belum proper. CRUD
Enrollment Employee juga belum lengkap, hanya ada Delete Biometric data yang tidak tahu arahnya
ke semua enrollment atau per employee. Employee ID tidak bisa diisi. coba analisis dan improve
agar flow dan UX nya better."*

Temuan analisis kode (bukan dugaan):

| # | Temuan | Lokasi |
|---|---|---|
| 1 | Backend shift sudah CRUD penuh (delete → 409 bila dipakai); UI hanya list + create (nama/mulai/selesai). `tolerance_min` dan `workdays` tak bisa diatur → selalu 15 mnt, Sen–Jum. Jam diketik bebas; 409/422 tampil sebagai "gagal simpan". | `backend/app/api/shifts.py`, `EnrollmentPage.tsx:187,370` |
| 2 | Kartu SHIFT (data global) ada di dalam panel detail karyawan → terlihat milik karyawan terpilih. | `EnrollmentPage.tsx:370` |
| 3 | NIK di panel edit `readOnly disabled`, padahal PATCH menerima `employee_code` + cek duplikat. | `EnrollmentPage.tsx:353`, `api/employees.py:57` |
| 4 | Tak ada hapus karyawan di UI; backend punya (409 bila ada riwayat absensi). | `api/employees.py:72` |
| 5 | Nonaktifkan tanpa konfirmasi; status nonaktif tak tampil di daftar; tak ada filter. | `EnrollmentPage.tsx:161,230` |
| 6 | Tanpa validasi isi: nama/NIK kosong lolos sampai DB. | `schemas/employee.py` `EmployeeIn` |
| 7 | "Hapus data biometrik" sebenarnya **per karyawan** (`DELETE /employees/{id}/biometrics`), tapi tombolnya di dasar panel, tepat di bawah kartu SHIFT global, tanpa nama → terbaca "hapus semua". | `EnrollmentPage.tsx:400` |
| 8 | Galeri wajah memuat embedding **semua** karyawan termasuk nonaktif → karyawan nonaktif tetap dikenali di gate dan tercatat absen. | `services/face.py` `FaceGallery.load` |
| 9 | Daftar memanggil `enrollment-status` sekali per karyawan (N+1). | `EnrollmentPage.tsx:65` |
| 10 | Grid daftar/detail `minmax(0,1.2fr) minmax(320px,1fr)` inline → meluap di 390 px. | `EnrollmentPage.tsx:228` |
| 11 | `compute_status` menghitung jam selesai pada tanggal masuk → shift lintas tengah malam belum didukung. | `services/attendance.py:50` |

## 2. Keputusan user (QnA 2026-09-23)

| Topik | Keputusan |
|---|---|
| Lokasi manajemen shift | Tab **Shift** di halaman Enrollment (Karyawan \| Shift) |
| Hapus karyawan ber-riwayat absensi | **Tolak** (409 tetap), UI menjelaskan dan menawarkan Nonaktifkan |
| Karyawan nonaktif di face gate | **Dikeluarkan dari matching** (galeri hanya karyawan aktif) |
| Konfirmasi hapus foto wajah | Modal danger menyebut **nama + jumlah foto**; tanpa ketik-ulang |
| Shift lintas tengah malam | **Ditolak** (selesai > mulai); follow-up terpisah |

## 3. Tujuan dan kriteria sukses

Admin bisa mengelola karyawan dan shift dari satu halaman tanpa menebak cakupan aksi.

Sukses:
- Shift: tambah, edit (nama, jam, toleransi, hari kerja), hapus — semua dari tab Shift; error
  duplikat, jam tak valid, dan "masih dipakai" tampil sebagai pesan spesifik.
- Karyawan: tambah, edit nama/**NIK**/shift, nonaktif/aktif (dengan konfirmasi), hapus
  (dengan konfirmasi; riwayat absensi → penjelasan + tawaran nonaktifkan).
- Hapus foto wajah jelas per karyawan: tombol di kartu Wajah, label dan modal menyebut nama.
- Karyawan nonaktif tidak lagi menghasilkan match di gate; mengaktifkan kembali memulihkannya
  tanpa enroll ulang.
- Halaman tanpa overflow horizontal di 390 px.
- Tidak ada regresi pada suite yang ada; tidak ada migrasi DB.

Di luar scope (follow-up): shift lintas tengah malam (#11); hitung ulang `attendance_day` lama
saat jam shift diedit — perubahan shift hanya berlaku untuk perhitungan berikutnya.

## 4. Backend

Tanpa migrasi; tanpa endpoint baru.

### 4.1 Validasi (`app/schemas/employee.py`)
- `EmployeeIn` / `EmployeePatch`: `name` di-trim, 1–128 karakter; `employee_code` di-trim,
  1–32 karakter (sesuai kolom). Patch: field tetap opsional, tapi bila dikirim wajib valid.
- `ShiftIn` / `ShiftPatch`: `name` di-trim, 1–64 karakter.
- `ShiftIn`: `model_validator` → `end_time > start_time` (string `HH:MM` sebanding
  leksikografis), else 422 `end_time must be after start_time`.
- `update_shift` (router): cek yang sama setelah menggabungkan nilai lama + perubahan → 422
  dengan pesan sama (PATCH yang hanya mengubah salah satu jam tetap tervalidasi).

### 4.2 `EmployeeOut` memuat status wajah
- `Employee` mendapat property `photo_count` (`self.embeddings.count()`) dan `face_ready`
  (`photo_count >= MIN_PHOTOS`). `MIN_PHOTOS` dipindah dari `api/enrollment.py` ke
  `app/models/employee.py` dan diimpor router (tanpa duplikasi angka 3).
- `EmployeeOut` menambah `photo_count: int` dan `face_ready: bool`.
- Endpoint `enrollment-status` tetap (kompatibel), UI tidak lagi memakainya untuk daftar.

### 4.3 Galeri hanya karyawan aktif (`app/services/face.py`)
- `FaceGallery.load`: query `FaceEmbedding` join `Employee` dengan `Employee.active == True`.
- `update_employee`: bila `active` ada di perubahan → `face.refresh_gallery(db)` setelah commit.
- Tidak ada perubahan lain pada pipeline wajah/matching R5b (threshold, quality gate, node).
- `find_duplicate` saat enroll memakai galeri yang sama → wajah karyawan nonaktif tidak lagi
  memicu peringatan duplikat. Diterima (peringatan hanya informatif).

### 4.4 Delete tetap
`DELETE /employees/{id}` (409 `employee has attendance records; deactivate instead`) dan
`DELETE /shifts/{id}` (409 `shift in use by employees`) tidak berubah.

## 5. Frontend

### 5.1 Struktur
`frontend/src/features/enrollment/`:
- `EnrollmentPage.tsx` → shell: judul + Carbon `Tabs` (Karyawan | Shift), memuat `me`.
- `EmployeesTab.tsx` → daftar + panel detail + modal karyawan.
- `ShiftsTab.tsx` → tabel + modal shift.

Kelas grid/kartu dipindah dari inline style ke `app/theme.scss` (token yang ada), satu kolom
pada `max-width: 671px` (breakpoint yang sudah dipakai).

### 5.2 API client (`src/api/employees.ts`)
- Tipe `Employee` menambah `photo_count`, `face_ready`.
- Error bertipe sederhana: fungsi melempar `Error` dengan pesan kode tetap —
  `createEmployee`/`updateEmployee` 409 → `'duplicate'`; `deleteEmployee` 409 →
  `'has_attendance'`; `createShift`/`updateShift` 409 → `'duplicate'`, 422 → `'invalid'`;
  `deleteShift` 409 → `'in_use'`.
- Tambah `updateShift(id, patch)` dan `deleteShift(id)`.

### 5.3 Tab Karyawan
- Toolbar: pencarian nama/NIK + `Select` status (Aktif — default, Nonaktif, Semua) + tombol
  **+ Karyawan** (admin).
- Baris: avatar inisial + titik status wajah, NIK, shift, badge wajah (dari `photo_count` /
  `face_ready`), tag **Nonaktif** bila `active=false`.
- Panel detail, tiga kartu:
  1. **Identitas** — Nama, **NIK (bisa diedit)**, Shift, tombol Simpan. Wajib isi; 409 →
     `invalidText` "NIK sudah dipakai" di field NIK.
  2. **Wajah** — grid foto + hapus per foto, Upload, hasil batch (seperti sekarang), dan tombol
     `danger--ghost` **"Hapus semua foto wajah"**, nonaktif bila `photo_count = 0`. Modal
     danger: *"Hapus semua {n} foto + embedding wajah "{name}"? Riwayat absensi tetap
     tersimpan."*
  3. **Status** — tombol Nonaktifkan/Aktifkan → modal konfirmasi (nonaktif: *"{name} tidak akan
     dikenali di gate absensi sampai diaktifkan lagi. Foto wajah dan riwayat tetap."*); tombol
     danger **Hapus karyawan** → modal konfirmasi; bila server membalas `has_attendance`, modal
     berganti isi: *"{name} sudah punya riwayat absensi dan tidak bisa dihapus. Nonaktifkan
     saja?"* dengan tombol primer Nonaktifkan.
- Modal tambah: nama + NIK wajib (tombol Simpan nonaktif selama kosong), shift opsional;
  409 → `invalidText` di NIK. Setelah sukses, karyawan baru terpilih.
- Non-admin: semua kontrol tulis tersembunyi/nonaktif (seperti sekarang).

### 5.4 Tab Shift
- Tabel Carbon (`Table` primitives, seperti AttendancePage): Nama · Jam (`07:00–16:00`) · Toleransi (`15 mnt`) · Hari kerja
  (`Sen–Jum` atau daftar singkat) · Aksi (Edit, Hapus; admin).
- Modal tambah/edit: Nama; Mulai/Selesai `TextInput type="time"`; Toleransi `NumberInput`
  0–120; Hari kerja 7 `Checkbox` (Sen..Min, ISO 1..7), minimal satu. Validasi klien: nama
  wajib, selesai > mulai, ≥1 hari — pesan inline; server 409 → "Nama shift sudah dipakai".
- Hapus → modal konfirmasi; `in_use` → notifikasi *"Shift masih dipakai karyawan. Pindahkan
  karyawan ke shift lain dulu."*
- Kartu shift di panel karyawan dihapus.

### 5.5 i18n
Semua string baru lewat `src/app/i18n.tsx` (ID + EN). `en.purge` berganti makna menjadi
"Hapus semua foto wajah"; kunci lama yang tak terpakai dihapus.

## 6. Pengujian dan verifikasi

TDD per perubahan. Tes baru mengikuti lapisan:
- `backend/tests/test_employees_api.py`: nama/NIK kosong/spasi → 422; trim tersimpan;
  `photo_count`/`face_ready` di list; toggle `active` → galeri ter-refresh.
- `backend/tests/test_employees_api.py` (tes shift sudah di sini): end ≤ start → 422 di POST;
  PATCH hanya `end_time` lebih awal dari start lama → 422.
- `backend/tests/test_face_service.py`: galeri tidak memuat embedding karyawan nonaktif;
  aktif kembali → termuat.
- `frontend/src/__tests__/enrollment.test.tsx` (+ `shifts.test.tsx`): NIK bisa diedit dan
  terkirim di PATCH; tombol hapus foto ada di kartu Wajah dan modal menyebut nama; filter status;
  hapus karyawan → `has_attendance` → tawaran Nonaktifkan memanggil PATCH `active=false`;
  CRUD shift lewat modal + pesan `in_use`.

Verifikasi sebelum tiap commit (baseline `main` `ea8cd3c`: backend 328, vision 177 (3
deselected), frontend 104, build exit 0, lint 22 warning lama — bandingkan set warning):
```bash
cd backend && .venv/bin/python -m pytest tests -q -m "not gpu"
backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"
cd frontend && npx vitest run && npm run build && npm run lint
```
UI: cek di app berjalan (desktop + 390 px via `temp/tools/cdp-viewport.mjs`), screenshot ke
`docs/evidence/`. Deploy ke `gspe-ai3` hanya dengan izin eksplisit user (tanpa migrasi; cukup
`git pull` + restart `isentinel-api`).

## 7. Dampak dan rollback

- Data server (Angly, Ikhsal, 2 shift) tidak diubah oleh perubahan ini. Karyawan yang saat ini
  nonaktif (bila ada) berhenti dikenali setelah deploy — sesuai keputusan.
- Rollback: revert commit branch; tidak ada migrasi.
- Dokumen: `CHANGELOG.md` per commit; `README.md`/`ROADMAP.md` bila alur enrollment berubah
  (tab Shift, nonaktif = tidak dikenali).
