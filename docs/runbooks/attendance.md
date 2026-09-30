# Runbook — Attendance (absensi)

Halaman **Attendance** (`/attendance`) menampilkan rekap harian (tab Harian / Rentang
tanggal / Per karyawan) dan mendukung koreksi manual oleh admin.

## Status dan batas hari

| Status | Kondisi | Durasi |
|---|---|---|
| `ontime` / `late` | entry + exit terdeteksi | exit − entry |
| `waiting` (**Di dalam**) | entry tanpa exit, belum lewat batas (atau karyawan tanpa shift) | `null` — UI menghitung live untuk hari ini |
| `no_exit` (**Tanpa exit — perlu koreksi**) | entry tanpa exit setelah batas | `null` |
| `no_entry` (**Tanpa entry — perlu koreksi**) | hanya exit terdeteksi | `null` |
| `absent` (**Tidak hadir**) | karyawan aktif ber-shift, hari kerja, tanpa deteksi, setelah batas | `null` |

- **Batas** = `tanggal + shift.end_time + NO_EXIT_GRACE_MIN` (default 60 menit, tz server/WIB).
- Karyawan **tanpa shift** tidak pernah otomatis `absent`/`no_exit` — entry tanpa exit
  tetap "Di dalam".
- List API dan CSV menampilkan **status efektif**: `waiting` yang sudah lewat batas
  langsung tampil `no_exit` walau job belum jalan; baris ber-`override_note` tidak diubah.

## Penutupan hari otomatis (`AttendanceCloser`)

- Thread latar di proses API: `close_due` tiap **15 menit** (`CLOSE_INTERVAL_S = 900`),
  **run pertama segera saat start** (catch-up **7 hari ke belakang**, `CLOSE_DAYS_BACK`).
- Untuk tiap tanggal `[hari ini − 7 hari, hari ini]` dan tiap karyawan **aktif** dengan
  shift yang menjadwalkan hari itu: bila sudah lewat batas — buat baris bila belum ada
  (hasil `absent` bila tanpa event), atau hitung ulang `waiting` → `no_exit`.
- **Baris yang dikoreksi manual (`override_note` non-kosong) tidak pernah disentuh** oleh
  job ini, oleh `effective_status`, maupun oleh `close_days`.
- Exception (mis. DB sibuk) dicatat di log (`attendance close failed`); thread tetap jalan
  dan mencoba lagi interval berikutnya. Stop rapi saat API shutdown.

**Dampak deploy pertama:** saat API start setelah deploy, catch-up membuat baris
`absent` untuk hari kerja tertinggal sampai 7 hari ke belakang (untuk karyawan aktif
ber-shift yang belum punya baris) dan menutup `waiting` yang sudah lewat batas. Ini
idempoten — start ulang tidak menduplikasi baris.

### Operasional

- **Log:** `journalctl -u isentinel-api -f | grep -i "attendance close"`.
- **Jalankan manual satu hari** (internal): `POST /internal/maintenance/close-days`
  header `Authorization: Bearer $NODE_API_KEY`, body `{"date": "YYYY-MM-DD"}` —
  default kemarin bila body kosong. `close_days` juga melewati baris ber-`override_note`.
- **Restart API** (tanpa passwordless sudo): `kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs)` —
  unit `Restart=always` menjalankan ulang; catch-up 7 hari berjalan otomatis.

## Koreksi manual

1. Buka `/attendance`, klik baris (admin) atau tombol **Koreksi** pada baris
   "Tanpa exit/entry — perlu koreksi".
2. Isi status, jam masuk/keluar bila perlu, dan **catatan (wajib)** → Simpan.
3. `PATCH /api/v1/attendance/{id}` hanya menerima status
   `{ontime, late, waiting, no_exit, no_entry, absent}`; tanpa catatan → 422.
4. Baris hasil koreksi (dan baris hasil import CSV — `override_note='import'`) tidak
   ditimpa job penutupan. Event absensi **baru** untuk hari itu tetap menghitung ulang
   baris (perilaku lama; koreksi yang perlu dipertahankan harus diinput ulang setelahnya).

## Import/export CSV

- Export (`/api/v1/attendance/rekap.csv`): status **efektif**, urutan kronologis menaik.
- Import: upsert per `(employee_code, date)`; `first_entry` kosong + `last_exit` terisi
  → status `no_entry`; `override_note` di-set `import` sehingga baris tidak ditimpa job.

## Gerbang wajah (face-first)

### Zona attendance

Zona attendance digambar di **area kepala** (polygon kecil di
sekitar kepala/atas badan pada frame utama), bukan seluruh area pintu. Gunakan
editor zona; arah gate `entry`/`exit`. Zona tanpa arah
diabaikan worker (tidak ada fallback person).

### Membaca label gerbang di debugger

Live View → klik tile kamera attendance → modal debugger. Kotak biru (`face`)
dengan label:

- `di luar zona` — wajah terdeteksi di luar polygon zone;
- `wajah terlalu kecil` — lebar wajah < `face_min_width_px`;
- `skor rendah` — skor deteksi SCRFD < `face_min_det_score`;
- `menyamping` — yaw > `face_max_yaw`;
- `buram` — blur < `face_blur_min`.

Label berupa angka (mis. `0.82`) = lolos gerbang; angkanya skor kualitas frame itu, dan
worker sedang mengumpulkan frame bagus (default 3) sebelum menerbitkan satu event.

### Kalibrasi `face_stats`

Perlu ≥10 lintasan nyata lewat gerbang. Buka debugger, catat distribusi label
`buram` (nilai blur) dan `wajah terlalu kecil` (width_px) dari log/overlay, lalu
setel `face_blur_min` dan `face_min_width_px` di Konfigurasi → Deteksi & Model →
Advanced → "Wajah attendance" agar wajah bagus lolos dan noise dibuang. Nilai

## Troubleshooting

| Gejala | Kemungkinan | Langkah |
|---|---|---|
| "Tidak hadir" tidak pernah muncul | Job tidak jalan (API start gagal / exception berulang) | Cek log `attendance close failed`; cek thread hidup: `py-spy dump --pid <api>` bila perlu; restart API |
| Hari ini "Tidak hadir" sebelum jam selesai shift | Bukan bug — batas = shift selesai + grace | Tunggu lewat batas atau cek `NO_EXIT_GRACE_MIN` |
| Baris dikoreksi berubah sendiri | Ada event absensi baru hari itu setelah koreksi | Input ulang koreksi (event baru memicu recompute — batasan yang diketahui) |
| Waktu tampil tidak WIB | TZ host server bukan WIB | Set TZ host (semua perbandingan memakai tz lokal server); `LOCAL_TZ` dibaca saat start |
