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

Zona attendance digambar di **area kepala** pada frame utama, bukan lantai. Buat
zona cukup lebar agar wajah yang berjalan berada di dalamnya **≥1 detik**
(sekitar 5 frame pada `ai_fps=5`). Pemicu tetap pusat bbox wajah di polygon;
deteksi/tracking memakai seluruh frame, tanpa ROI crop. Arah `entry`/`exit`
tetap wajib, termasuk saat **Catat absensi OFF**; zona tanpa arah diabaikan worker.

**Catat absensi** dan **Kirim wajah tidak dikenal** adalah flag behavior attendance
(`record`, `telegram_unknown`, default true). OFF pada pencatatan hanya menerbitkan
evidence `detected` di Inbox/Telegram, tidak membuat riwayat atau rekap absensi.
Dedup per karyawan+zona memakai cooldown default 5 menit; Unknown tidak di-dedup
oleh jalur ini. Saklar Telegram induk tetap menentukan pengiriman; Unknown OFF
hanya menahan alert Unknown, bukan event Inbox.

Telegram membedakan CHECK IN/OUT, SUDAH CHECK IN (jam check in pertama dan exit sejak
itu bila terlihat), serta TERDETEKSI — MASUK/KELUAR. Cooldown tetap diam. SUDAH CHECK IN hanya muncul
saat karyawan tidak terlihat ≥ cooldown (default 5 menit) lalu muncul lagi; orang yang menetap di area
kamera tidak memicu pesan berulang.
Tautan **Lihat event** membuka evidence lengkap.

### Checklist kamera gate

- Shutter **≥1/250** untuk mengurangi blur saat berjalan.
- Gunakan WDR/BLC bila pintu membelakangi cahaya.
- Pasang setinggi mata hingga sedikit di atasnya, dengan sudut wajah tidak menyamping.
- Tempatkan zona **2–4 m sebelum pintu**, dengan waktu wajah di zona ≥1 detik.
- Bila skor cocok kurang, lakukan enrollment dari kamera gate sendiri dengan foto jelas.

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

Gunakan `face_stats` (width_px, det_score, yaw, blur, frames), label debugger, dan
corong heartbeat untuk menentukan penyebab sebelum menyetel gerbang. Perubahan
angka hanya setelah uji penerimaan server; siklus kode ini tidak mengubah default
`FaceSettings` atau ambang cosine.

### Membaca corong di monitoring

`GET /api/v1/monitoring` (login biasa) → `cameras[].ai.funnel`. Data direset per
jendela heartbeat; heartbeat node lama tanpa corong menghasilkan null.

| Field/gejala | Arti dan langkah |
|---|---|
| `faces` | Wajah yang dilacak per frame, bukan jumlah orang unik |
| `rejects.zone` dominan | Periksa posisi polygon terhadap pusat bbox wajah |
| `rejects.small` dominan | Dekatkan zona atau evaluasi `det_size` lebih besar pada konfigurasi engine; bukan knob UI baru |
| `rejects.score` dominan | Perbaiki pencahayaan dan visibilitas wajah sebelum melonggarkan gerbang |
| `rejects.yaw` / `rejects.blur` dominan | Perbaiki sudut kamera / shutter |
| `tracks_emitted` | Track yang menerbitkan event |
| `tracks_silent` tinggi | Track masuk zona tanpa embedding lolos; periksa gerbang yang terlalu ketat |
| `ttfg_median_s` | Median waktu masuk zona hingga embedding bagus pertama; bukan latensi end-to-end |

`fps` dan `motion_skip_pct` berada di objek `ai` yang sama. Motion gate tetap
update setiap frame; wajah terlihat mempertahankan pemrosesan frame diam, dan
gate kembali melewati frame saat wajah hilang. Wajah latar/poster/cermin dapat
menaikkan beban GPU; pantau sebelum tuning.

### Protokol uji penerimaan server (belum dijalankan)

1. Setelah review dan deploy berizin, gunakan kamera ideal dan **10 karyawan × 5 lintasan**.
2. Minta jalan normal tanpa menoleh atau berhenti menatap CCTV.
3. Ukur dari wajah muncul hingga event tercatat: target **≥95% tercatat benar**,
   **≤2 detik**, dan **nol salah-orang**. Catat hasil dan corong di CHANGELOG.
4. Ulangi protokol setiap perubahan ambang; jangan menyimpulkan keberhasilan dari tes fake worker.
5. Deploy memerlukan rebuild `api` dan `vision`, lalu `docker compose up -d`,
   bukan hanya restart. Tanpa migrasi; flag zona lama tetap memakai default.
   Kode ini **BELUM diuji di server nyata**. Fase 3b dua fase hanya diputuskan dari data uji.

## Troubleshooting

| Gejala | Kemungkinan | Langkah |
|---|---|---|
| "Tidak hadir" tidak pernah muncul | Job tidak jalan (API start gagal / exception berulang) | Cek log `attendance close failed`; cek thread hidup: `py-spy dump --pid <api>` bila perlu; restart API |
| Hari ini "Tidak hadir" sebelum jam selesai shift | Bukan bug — batas = shift selesai + grace | Tunggu lewat batas atau cek `NO_EXIT_GRACE_MIN` |
| Baris dikoreksi berubah sendiri | Ada event absensi baru hari itu setelah koreksi | Input ulang koreksi (event baru memicu recompute — batasan yang diketahui) |
| Waktu tampil tidak WIB | TZ host server bukan WIB | Set TZ host (semua perbandingan memakai tz lokal server); `LOCAL_TZ` dibaca saat start |
