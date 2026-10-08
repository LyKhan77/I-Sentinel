# Spec — Peringatan "Exit awal" pada rekap attendance

Status: **Draft, pendekatan disetujui di chat 2026-10-08 (opsi B)**, menunggu review spec tertulis.
Branch: `feat/exit-early-warning` (dari `main` @ `67cd400`).
Konteks: `WORKFLOW.md` §12 (Absensi), `docs/runbooks/attendance.md`, pertanyaan lanjutan dari `docs/superpowers/specs/2026-10-07-face-gate-refine-design.md`.

---

## 1. Latar

Exit boleh berulang dalam sehari, dan `recompute_day` mengambil `last_exit = max(semua exit)`. Akibatnya:
- Exit tengah hari (makan siang) mengubah baris dari `waiting` menjadi `ontime`/`late`, dengan durasi sampai jam makan siang.
- Bila exit sore tidak terlihat (kamera exit terlewat, atau pintu lain), `last_exit` tetap exit tengah hari dan status tidak pernah menjadi `no_exit`: baris tampak lengkap padahal exit akhirnya hilang.
- Sistem tidak bisa membedakan "pulang awal" dari "exit sore tidak terlihat"; hanya admin yang bisa memutuskan.

Data server development (2026-10-08): dari 28 baris rekap, 2 baris `late` (semua baris selesai) punya `last_exit` lebih dari 60 menit sebelum shift selesai.

Keputusan user: **peringatan tanpa mengubah status** (opsi B). Pencatatan semua sesi dan jam kerja bersih (opsi C), status baru `early_exit` (opsi D), dan dokumentasi saja (opsi A) tidak dipilih.

## 2. Temuan kode

| # | Temuan | Lokasi | Dampak |
|---|---|---|---|
| 1 | `recompute_day` memakai `first_entry = min`, `last_exit = max` dan `compute_status` memberi `ontime`/`late` begitu `last_exit` ada | `backend/app/services/attendance.py:47-108` | Sumber masalah; tidak diubah |
| 2 | `effective_status` adalah pola turunan saat baca (tanpa kolom) untuk `waiting`→`no_exit` | `attendance.py:67-73` | Pola yang ditiru: peringatan dihitung saat baca, tanpa migrasi |
| 3 | `_row_dict` dipakai oleh daftar harian/rentang/per karyawan dan respons `PATCH` | `backend/app/api/attendance.py:60-74` | Satu tempat menambah field untuk semua endpoint |
| 4 | `CSV_COLUMNS` diekspor; impor membaca per nama kolom lewat `csv.DictReader` dan mengabaikan kolom tak dikenal; impor mengisi `override_note="import"` | `api/attendance.py:24-25,135-180` | Kolom baru di akhir aman untuk impor lama |
| 5 | Shift lintas tengah malam ditolak validator | `backend/app/schemas/employee.py:43` | `shift.end_time` selalu pada tanggal baris yang sama |
| 6 | Koreksi admin (`PATCH` dengan catatan) mengisi `override_note` | `api/attendance.py:183-215` | Baris yang sudah diputuskan admin tidak perlu diberi peringatan |
| 7 | Halaman Attendance menampilkan jam exit di sel sendiri dan `StatusBadge` di sel status; format durasi `at.duration.hm` = `{h}j {m}m` | `frontend/src/features/attendance/AttendancePage.tsx:469-475`, `frontend/src/app/i18n.tsx:657` | Chip ditaruh di sel exit, format jam dipakai ulang |

## 3. Keputusan user

| Topik | Keputusan |
|---|---|
| Pendekatan | Peringatan "Exit awal" turunan, status tidak berubah |
| Tempat | Daftar rekap (chip) dan kolom CSV; tanpa migrasi |

## 4. Tujuan, kriteria sukses, non-tujuan

**Kriteria sukses** (diuji):
1. Baris `ontime`/`late` dengan shift 07:00–16:00, `last_exit` 12:03, dibaca setelah 16:00 pada hari itu atau hari berikutnya → `exit_early_min == 237`.
2. `exit_early_min` bernilai `null` bila: selisih ≤ 60 menit (tepat 60 → `null`, 61 → 61); waktu baca sebelum shift selesai hari itu; `override_note` terisi (termasuk `"import"`); status `waiting`, `no_exit`, `no_entry`, atau `absent`; karyawan tanpa shift; `last_exit` kosong; `last_exit` setelah shift selesai.
3. Semua endpoint rekap (harian, rentang, per karyawan, `PATCH`) memuat field `exit_early_min`; `PATCH` dengan catatan membuatnya `null`.
4. CSV ekspor punya kolom terakhir `exit_early_min` (kosong bila `null`); impor CSV hasil ekspor dan CSV lama (tanpa kolom itu) berjalan seperti sebelumnya; kolom itu diabaikan saat impor.
5. UI: chip kuning di sel exit bertuliskan "Exit 3j 57m sebelum shift selesai" hanya bila `exit_early_min` terisi.
6. Status, `AttendanceCloser`, tile ringkasan, filter, dan Telegram tidak berubah.

**Non-tujuan:** status baru, pencatatan semua sesi dan jam kerja bersih, filter atau tile "exit awal", setelan ambang di UI/env, perubahan Telegram.

## 5. Desain

**Backend (`backend/app/services/attendance.py`):**
- Konstanta `EXIT_EARLY_MIN = 60`.
- `exit_early_min(row, shift, now: datetime | None = None) -> int | None`. `row` memiliki `date`, `last_exit`, `status`, `override_note`. Mengembalikan menit antara `last_exit` dan `shift.end_time` pada `row.date` bila semua syarat berikut terpenuhi, selain itu `None`: `shift` ada; `last_exit` ada; `row.status in ("ontime", "late")`; `override_note` kosong setelah `strip`; `now >= shift.end_time` pada `row.date` (lokal); selisih `round((end − last_exit)/60 detik) > EXIT_EARLY_MIN`.

**API (`backend/app/api/attendance.py`):** `_row_dict` menambah `"exit_early_min": attendance.exit_early_min(day, emp.shift if emp else None, now)`. `CSV_COLUMNS` ditambah `"exit_early_min"` di akhir; `export_csv` menulis nilainya (kosong bila `None`). Impor tidak diubah.

**Frontend:** tipe `AttendanceRow.exit_early_min: number | null`; di sel exit, di bawah jam, chip kecil (gaya inline seperti `StatusBadge`, warna amber) dengan `data-testid={`exit-early-${r.id}`}` hanya bila `exit_early_min != null`; teks dari kunci i18n baru `at.exitEarly` (`id`: `Exit {d} sebelum shift selesai`, `en`: `Exit {d} before shift end`) dengan `{d}` = format `at.duration.hm`.

## 6. Tes

Mengikuti berkas yang ada (`backend/tests/test_attendance_logic.py`, `test_attendance_api.py`, `frontend/src/__tests__/attendance.test.tsx`). Tiap tes harus gagal pada bug yang masuk akal (mis. ambang `>=` vs `>`, kondisi sebelum shift selesai, baris terkoreksi). Rincian di plan.

## 7. Dokumen

`WORKFLOW.md` §12, `ARCHITECTURE.md` (field API dan kolom CSV), `docs/runbooks/attendance.md` (arti peringatan dan cara menindaklanjuti lewat Koreksi), `CHANGELOG.md` per commit, `ROADMAP.md`.

## 8. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| Pulang awal yang sah ikut diberi peringatan | Peringatan, bukan status; admin menandai lewat Koreksi (catatan menghilangkan peringatan) |
| Karyawan yang memang keluar-masuk di jam kerja (shift pendek, jeda panjang) ambang 60 menit tidak pas | Konstanta tunggal; diubah lewat satu baris bila perlu; setelan UI di luar scope |
| Pembaca CSV pihak ketiga bergantung pada jumlah kolom | Kolom baru hanya di akhir; impor internal membaca per nama |

Rollback: revert commit; tanpa migrasi.

## 9. Keputusan yang saya ambil sendiri (koreksi saat review)

- Ambang 60 menit sebagai konstanta (selaras `NO_EXIT_GRACE_MIN`); tidak ada setelan karena env `Settings` tidak diteruskan compose di Docker.
- Peringatan disembunyikan untuk baris ber-`override_note`, termasuk hasil impor (`"import"`): nilai itu sudah diputuskan manusia.
- Peringatan hanya setelah shift selesai pada hari itu, supaya exit makan siang di hari berjalan tidak dianggap anomali.
- Tidak ada filter atau tile ringkasan "exit awal" di siklus ini.
