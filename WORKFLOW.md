# WORKFLOW — Alur per Fitur

Alur kerja setiap fitur I-Sentinel: siapa yang memakai, langkah di UI, dan apa yang terjadi di
sistem. Komponen dan kontrak teknis ada di `ARCHITECTURE.md`; detail aturan per halaman di
`README.md`; prosedur operasional di `docs/runbooks/`; cara kerja pengembangan di
`docs/DEVELOPMENT.md`.

Urutan penyiapan sistem baru: **§1 Login → §3 Kamera → §5 Deteksi & node → §6 Zona → §10 Telegram →
§11 Enrollment & shift**. Setelah itu fitur lain berjalan otomatis.

Role: **admin** = semua konfigurasi, enrollment, koreksi, cleanup. **viewer** = read-only semua menu
(akun TV sebaiknya viewer khusus).

---

## 1. Login & sesi

**Pengguna:** semua · **Halaman:** `/login`

1. Pengguna mengisi username + password (tombol tampilkan password tersedia).
2. `POST /api/v1/auth/login` memeriksa bcrypt dan rate-limit per (username, IP): gagal berulang →
   lockout `LOGIN_LOCKOUT_MIN`.
3. Berhasil → cookie httpOnly berisi JWT (klaim versi `tv`), masa berlaku `ACCESS_TOKEN_EXPIRE_MIN`
   (default 48 jam) dan diperpanjang otomatis selama halaman aktif.
4. Setiap request memeriksa versi token dan status akun; token versi lama atau akun nonaktif → 401 →
   kembali ke login.

Admin awal dibuat otomatis saat API start (`ADMIN_PASSWORD` di `.env`).

## 2. Manajemen user

**Pengguna:** admin · **Halaman:** Konfigurasi → User

1. Admin menambah user (username 3–64 karakter, password 8 karakter–72 byte, role).
2. Per baris: ubah role, reset password, nonaktifkan/aktifkan, hapus. Akun sendiri tidak bisa
   diubah role/dinonaktifkan/dihapus.
3. Reset password, ganti password sendiri, atau nonaktifkan → `token_version` naik → semua sesi lain
   user itu keluar (termasuk koneksi WebSocket). Browser yang mengganti password tetap login.

## 3. Registrasi kamera

**Pengguna:** admin · **Halaman:** Konfigurasi → Kamera

1. **+ Tambah kamera** → isi Nama, Lokasi, IP (port opsional), path mainstream, path substream
   (kosong = sama dengan mainstream), pilih kredensial (`Default (NVR)` dari `.env` atau profil).
2. Opsional **Lanjutan → Deteksi otomatis**: `POST /api/v1/cameras/scan` memindai channel NVR dan mengisi path.
3. **Tes koneksi** → `POST /api/v1/cameras/probe`: resolusi/fps/codec MAIN & SUB + thumbnail.
4. **Simpan** → baris `camera` + `stream_source`; grup lokasi dibuat otomatis; konfigurasi go2rtc
   ditulis ulang; config push ke node.
5. Kamera muncul di Live View. **Deteksi baru berjalan setelah kamera punya zona aktif (§6).**

Kredensial khusus: DB hanya menyimpan referensi `store:cred_<id>`; password di `CAMERA_SECRETS_FILE`.
Import massal: menu **Lanjutan → Import CCTV** (pratinjau → terapkan). Menghapus kamera tidak
menghapus riwayat event.

## 4. Live View & Mode TV

**Pengguna:** semua · **Halaman:** `/live`, `/live/tv?screen=<nama>`

1. Grid kamera 2/3/4 kolom, filter lokasi, pemilih kamera **Kamera (n/m)**; pengaturan tersimpan per
   layar di `localStorage`.
2. Tile memutar stream go2rtc (WebRTC/MSE) hanya saat dekat layar; di luar layar menampilkan
   snapshot terakhir lewat proxy API (`GET /api/v1/cameras/{id}/snapshot`, wajib login).
3. Klik tile → **debugger**: kotak deteksi live (`detections` via WebSocket), label gerbang wajah
   pada kamera attendance.
4. **Mode TV**: kiosk tanpa menu, auto-scroll, toolbar auto-hide, stream gagal dicoba ulang tiap
   60 s. Runbook Raspberry Pi: `docs/runbooks/live-view-tv-pi.md`.
5. Event baru memberi outline tile 30 s (§9); alert kesehatan kamera memberi badge
   **Tanpa frame / FPS rendah** (§14).

## 5. Konfigurasi deteksi & node

**Pengguna:** admin · **Halaman:** Konfigurasi → Deteksi & Model, Konfigurasi → Node

1. **Deteksi & Model** (`PUT /api/v1/detector-settings`): FPS AI default, confidence, filter gerak
   (motion), dan gerbang wajah attendance (lebar min, skor deteksi, yaw, blur, jumlah frame).
2. **Node**: pilih GPU untuk detektor (`PUT /nodes/{id}/detector-device`) dan untuk model wajah
   (`PUT /nodes/{id}/face-device`).
3. Perubahan dikirim lewat config push (MQTT retained) → node menerapkan tanpa restart manual.
4. Node mengirim heartbeat tiap 10 s (perangkat, GPU, statistik kamera) yang tampil di Dashboard dan
   Monitoring.

## 6. Zona deteksi & behavior

**Pengguna:** admin · **Halaman:** Konfigurasi → Zona Deteksi

1. Pilih kamera → gambar polygon di frame (klik titik, tutup di titik awal, drag untuk memindah).
2. Isi nama, behavior (`intrusion`, `loitering`, `running`, `idle_zone`, `crowd`, atau attendance
   dengan arah `entry`/`exit`), severity, jadwal (**24/7**, **Jam tertentu**, **Ikut shift**).
3. Per behavior: toggle **Snapshot**, **Clip**, **Telegram**. Behavior aktif wajib punya Snapshot atau
   Clip (422 `needs snapshot or clip`); attendance wajib snapshot.
4. **Simpan** → `zone` → config push → node memulai worker untuk kamera itu.
5. Menurut jadwal, analyzer di node mengevaluasi setiap track di polygon (§7).

Zona attendance digambar kecil di **area kepala**. Shift lintas tengah malam belum didukung.

## 7. Event behavior (deteksi → Inbox)

**Pengguna:** otomatis · **Hasil:** halaman `/events`

1. Node: frame substream → YOLO26s (TensorRT) → ByteTrack → analyzer.
   - `intrusion`: orang masuk zona; `loitering`: terlalu lama di zona; `running`: kecepatan tinggi;
   - `idle_zone`: zona kosong selama `trigger_seconds`; `crowd`: jumlah ≥ `min_count` selama
     `trigger_seconds`. Keduanya mengirim pengingat tiap `reminder_minutes` selama kondisi berlanjut.
2. Event dikirim (MQTT/HTTP, antrean disk bila putus) → API `ingest`: dedup, simpan `event`, broadcast
   WebSocket.
3. Recorder node menyusun **klip pra-buffer** dari ring mainstream + snapshot beranotasi → upload blob
   → `isentinel/events/media` → path media diisi ke event.
4. Paralel: notifikasi web (§9) dan alert Telegram (§10).

## 8. Event Inbox

**Pengguna:** semua · **Halaman:** `/events`

1. Daftar kiri: filter Tipe, Kamera, Severity, Rentang waktu, dan pencarian; data dari `GET /api/v1/events`
   dan update realtime via WebSocket. Tipe/Kamera/Severity/Rentang difilter **di server** (lima sekaligus
   jadi satu query), pencarian teks tetap di klien.
2. **Filter hidup di URL** (`?type=&camera=&severity=&range=&q=`): deep link, reload, dan Back/Forward
   memulihkan filter; perubahan menulis URL dengan `replace` (riwayat tidak menumpuk) dan menjaga param lain
   termasuk `?event=`. Nilai tak valid di URL jatuh ke default tanpa error; nilai default tidak ditulis.
   Opsi Tipe bertambah **"Keamanan (tanpa absensi)"** (`type=security` = semua tipe kecuali `attendance`,
   dikirim sebagai daftar `type`) dan Rentang bertambah **Hari ini** (`range=today`, sejak 00:00 lokal) —
   keduanya menyamakan semantik angka "Event hari ini" di Dashboard. Setiap dropdown punya opsi **Semua**
   (mengosongkan filter itu) dan tombol **Atur ulang filter** muncul begitu ada filter non-default —
   menghapus kelima param filter, `?event=` tetap ada. Opsi Tipe statis (daftar tipe ingest, berlabel lokal),
   bukan turunan event yang sedang termuat. Respons lama yang tiba belakangan dibuang.
3. **Muat lebih banyak**: daftar memuat 200 event per halaman (`LIMIT`) dengan urutan `ts_event DESC, id DESC`.
   Saat halaman penuh, hitungan jadi `N+ event` + petunjuk dan tombol **Muat lebih banyak** mengambil halaman
   berikutnya (`offset`, digabung dengan dedupe `id` — event baru yang menggeser halaman tidak menduplikasi
   baris). Daftar dibatasi **1000 baris** (`MAX_EVENTS`): setelah itu tombol diganti petunjuk batas dan filter
   perlu dipersempit. Refetch klip tertunda (poll 5 dtk) menggabung halaman pertama tanpa membuang halaman
   yang sudah dimuat; ganti filter mengganti daftar dan mereset halaman.
4. Detail kanan — **event kamera**: tab clip (`#t=` melompat ke detik kejadian), snapshot, crop wajah,
   metadata, status alert Telegram (`queued/sent/failed/rate_limited/not_configured`, realtime).
5. Detail kanan — **event system** (node offline/pulih, health alert): panel **Bukti** menggantikan tab media.
   Fakta dari payload (aturan, target, nilai, ambang, durasi aturan, status) selalu tampil; grafik tren
   menampilkan seri agregat yang sama dengan pengecekan alert (mis. `camera_low_fps` dalam persen target FPS)
   beserta garis ambang dan penanda waktu event. Event baru membawa serinya di `payload.evidence` (disimpan saat
   event dibuat): grafik digambar langsung dari situ — tanpa permintaan jaringan dan tanpa batas 7 hari. Event
   lama tanpa `evidence` memakai `GET /api/v1/monitoring/history?from&to&node_id`; jendela tren maksimum 6 jam,
   data lebih tua dari 7 hari hanya menampilkan fakta. Gagal memuat grafik tidak menyembunyikan fakta. Event
   system memakai judul/lokasi terlokalisasi (bukan `system · cam null`) dan tidak pernah menunggu klip.
6. Media diputar lewat `GET /api/v1/media/{path}` (wajib login). Tautan `/events?event=<id>` (Telegram,
   lonceng/toast, Dashboard) selalu membuka event yang dituju: bila halaman sudah terbuka pilihannya ikut pindah;
   event di luar 200 terbaru (atau tersaring filter) diambil lewat `GET /api/v1/events/{id}` dan disematkan di
   panel detail dengan catatan kecil; klik baris menulis `?event=<id>` ke URL (replace, riwayat tidak menumpuk);
   tanpa parameter atau nilainya tak valid → event pertama dan URL tidak diubah; event tidak ditemukan (dihapus
   retensi) atau gagal dimuat → peringatan dan panel jatuh ke event pertama — tidak pernah diam-diam menampilkan
   event lain. Tautan tetap hanya bisa dibuka dari LAN.

## 9. Notifikasi web

**Pengguna:** semua · **Lokasi:** lonceng header, Live View, Mode TV

1. Event behavior atau node offline/pulih masuk via WebSocket → `EventAlertsProvider`.
2. Badge lonceng + panel tab **Hari ini / Kemarin**, toast 8 s, bunyi pendek (bisa di-mute).
3. Live View: outline warna severity 30 s pada tile; tile di luar layar → chip di kanan bawah.
4. Status dibaca & mute disimpan per browser. Absensi dan alert kesehatan tidak memicu toast
   node offline.

## 10. Alert Telegram

**Pengguna:** admin (setup), staf (penerima) · **Halaman:** Konfigurasi → Notifikasi

1. **Setup satu kali**: buat bot di @BotFather → tambahkan ke grup staf, kirim satu pesan →
   tempel token → **Simpan** → **Deteksi grup** → pilih grup → **Simpan** → **Kirim pesan uji**.
   Token disimpan di `CAMERA_SECRETS_FILE`, tidak pernah tampil lagi.
2. Nyalakan toggle **Telegram** per behavior di zona (§6).
3. Saat event: `alerting` memeriksa toggle, `ALERT_MIN_SEVERITY`, dan rate-limit (per kamera, zona,
   tipe, track; critical tanpa batas, lainnya 2 menit) → baris `alert` berstatus `queued`.
4. `alert_dispatcher` (thread terpisah) mengirim foto + caption HTML → status `sent`/`failed` →
   broadcast ke Inbox.

Pengirim lain: node offline/pulih (§14), disk hampir penuh (§13), alert kesehatan dengan toggle ON (§14).

## 11. Enrollment karyawan & shift

**Pengguna:** admin · **Halaman:** `/enrollment` (tab Karyawan, Shift)

1. **Shift**: nama, jam mulai–selesai (dalam satu hari), hari kerja, toleransi telat (default 15 menit).
2. **Karyawan**: kode, nama, NIK, shift, status aktif.
3. **Foto wajah**: unggah 3–5 foto (`POST /employees/{id}/photos[/batch]`) → API meng-embed dengan
   InsightFace `buffalo_l` → tolak `no_face` / `low_quality` → simpan `face_embedding` → galeri
   pencocokan di-refresh.
4. Karyawan siap absensi bila punya ≥ 3 foto valid (`enrollment-status`). Foto bisa dihapus satu per
   satu atau semua biometrik sekaligus.

## 12. Absensi

**Pengguna:** otomatis + admin (koreksi) · **Halaman:** `/attendance`

1. Karyawan lewat zona attendance → `face_worker` di node mengumpulkan frame wajah yang lolos gerbang
   kualitas → embedding + crop dikirim sebagai event `attendance` (arah entry/exit).
2. API mencocokkan ke galeri (cosine ≥ `face_match_threshold`, default 0,40). Cocok → `attendance_event` →
   `recompute_day` memperbarui `attendance_day`. Tidak cocok → event berlabel `Unknown` (oranye) di
   Inbox, tidak masuk rekap.
3. Status: tepat waktu/telat (entry + exit), **Di dalam** (`waiting`), **Tanpa exit** (`no_exit`),
   **Tanpa entry** (`no_entry`), **Tidak hadir** (`absent`). Batas hari = selesai shift +
   `NO_EXIT_GRACE_MIN` (60 menit).
4. `AttendanceCloser` tiap 15 menit (catch-up 7 hari saat start) membuat `absent` untuk karyawan aktif
   terjadwal yang tidak terdeteksi dan menutup `waiting` lewat batas menjadi `no_exit`.
5. Admin mengoreksi baris (tombol **Koreksi**, catatan wajib) → `override_note` → baris tidak diubah
   job lagi (kecuali ada event absensi baru hari itu).
6. Export/import CSV (`rekap.csv`); tab Harian, Rentang tanggal, Per karyawan dengan filter status.

Runbook: `docs/runbooks/attendance.md` (termasuk kalibrasi gerbang wajah).

## 13. Retensi & Storage

**Pengguna:** admin (ubah), viewer (lihat) · **Halaman:** Konfigurasi → Storage

1. Lihat pemakaian disk dan ukuran per jenis media (`GET /api/v1/storage/stats`).
2. Atur retensi `clip_days`, `snapshot_days`, `attendance_days`, dan ambang disk
   (`PUT /storage/settings`).
3. **Sweep otomatis** harian 03:00 (`isentinel-retention.timer`) atau **Sweep sekarang**
   (`POST /storage/sweep`): hapus media lewat retensi; event yang kehilangan media terakhirnya ikut
   dihapus (kecuali `system`).
4. **Cleanup per rentang** (`POST /storage/cleanup`, selalu **Pratinjau** dulu):
   - `events`: event + media + alert (opsional kamera/jenis; attendance tidak pernah ikut);
   - `attendance_media`: media absensi saja, rekap tetap;
   - `attendance_data`: rekap & riwayat per karyawan, maks kemarin, konfirmasi ketik `HAPUS`.
5. Disk ≥ ambang → banner di Storage/Dashboard + Telegram (pengingat maks 1×/24 jam), pulih di
   bawah ambang − 2 %.

Runbook: `docs/runbooks/storage-retention.md`.

## 14. Monitoring Resource

**Pengguna:** semua (admin mengatur aturan) · **Halaman:** `/monitoring`

1. **Kondisi saat ini** (polling 10 s): status keseluruhan, kartu node + server (CPU/RAM/disk, GPU,
   inferensi, backlog MQTT), tabel kamera (state stream, fps, umur frame), layanan (DB, go2rtc, MQTT,
   retensi, Telegram, disk).
2. **Node offline**: LWT atau heartbeat > 35 s (`NodeHealthMonitor`, cek 15 s) → event `system` +
   Telegram + banner di semua halaman; pulih → event + Telegram "pulih".
3. **Tren**: `HistorySampler` menyimpan bucket per menit ke `monitoring_sample` (7 hari) → grafik
   1 jam / 6 jam / 24 jam / 7 hari dengan arsir periode offline.
4. **Aturan & alert**: 8 aturan (kamera tanpa frame, FPS rendah, GPU panas, VRAM, RAM, CPU, latensi,
   backlog) dievaluasi tiap menit; menyala bila setiap menit dalam durasi melanggar, pulih setelah
   2 menit normal → `health_alert` + event web + Telegram bila toggle ON + badge tile kamera.
5. **Bukti permanen**: event system baru (health firing/resolved, node offline) menyimpan seri menitnya di
   `payload.evidence` saat dibuat → panel **Bukti** di Inbox tetap bergrafik walau retensi 7 hari terpangkas;
   event lama tanpa `evidence` tetap lewat `/monitoring/history` (+ catatan > 7 hari).

Runbook: `docs/runbooks/monitoring.md`.

## 15. Dashboard

**Pengguna:** semua · **Halaman:** `/dashboard`

Layout status-first (revamp 2026-09-30): **strip status** sistem (summary Monitoring + health alert aktif,
teks selalu ikut warna) → **4 tile KPI yang dapat diklik** — Kamera sehat→`/monitoring`, Event hari
ini→`/events?type=security&range=today` (filter yang sama dengan angka tile: keamanan tanpa absensi, sejak
tengah malam), Kehadiran hari ini→`/attendance`, Disk→`/configuration?tab=storage` → **chart event per jam**
hari ini (`GET /api/v1/events/stats/today` — `by_hour`/`critical_by_hour`; tipe `attendance` TIDAK dihitung,
angka tile adalah hitungan keamanan) → grid dua kolom: **8 event terbaru** (sumber realtime yang sama dengan
lonceng — nama kamera, Tag severity dengan teks, thumbnail snapshot, tautan `/events?event=<id>`) |
**masalah aktif** (maks 5, critical dulu; "Semua →" `/monitoring`) + **node ringkas** (status, health, GPU
pertama util/VRAM; detail di Monitoring). Banner disk saat ≥ ambang tetap di atas. Data via `useDashboardData`
(polling 15 dtk, kegagalan terisolasi per sumber — sumber gagal tampil "—"/"Gagal memuat", bukan 0 palsu;
nilai lama bertahan saat poll gagal dan strip menandai basi). Tile/chart ikut terbarukan saat event realtime
baru tiba. Titik masuk: Inbox (Events), Attendance, Monitoring, Storage.
