# I-Sentinel

Sistem surveillance AI: FastAPI backend + vision-node + frontend.

## Arsitektur

```
Browser (LAN)
   │  :5173 (Vite dev — isentinel-web.service)
   ▼
API FastAPI :8000 ──── Postgres (isentinel) ─── go2rtc :1984 (API/snapshot, proxy same-origin)
   ▲  ▲                                    └── go2rtc :8554 RTSP (LAN, tertutup firewall)
   │  └── MQTT Mosquitto :1883 ◄── vision-node (heartbeat + event + config push + LWT)
   └──── blob upload (clip/snapshot/crop) ─── vision-node (YOLO26s TensorRT + ByteTrack)
```

- Port terbuka di LAN: **8000** (API), **5173** (UI dev). go2rtc 1984/8554 hanya
  localhost/LAN-internal — snapshot browser lewat proxy API (auth-gated).
- Vision node: satu worker per kamera; detektor pin GPU via UI (Konfigurasi → Node).

## Peta Folder

```
isentinel/
├── backend/                  # FastAPI server pusat
│   ├── app/
│   │   ├── main.py
│   │   ├── api/              # routers: auth, cameras, zones, nodes, gates,
│   │   │                     #   detection, employees, attendance, events, alerts,
│   │   │                     #   telegram, users, settings
│   │   ├── core/             # config(env), security(jwt), db
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic
│   │   ├── services/         # probe, attendance, alerting, face, events_consumer,
│   │   │                     #   recorder, retention
│   │   └── ws/               # websocket hub
│   └── tests/
├── vision/                   # vision-node (deployable ke Jetson, minimal deps)
│   ├── node.py
│   ├── pipeline/             # source(go2rtc) → detector(YOLO) → tracker(ByteTrack) → emit
│   ├── analyzers/            # intrusion, loitering, running, idle_zone, crowd (face: face_worker.py)
│   ├── transport/            # mqtt client + disk queue store-and-forward
│   └── tests/
├── frontend/                 # React 19 + Vite + Carbon (9 halaman)
│   ├── src/
│   │   ├── app/              # shell, routing, i18n
│   │   ├── features/         # dashboard, live, events, attendance, enrollment, config
│   │   ├── components/
│   │   └── api/              # REST client + WS
├── deploy/
│   ├── go2rtc/go2rtc.example.yaml   # template; salin ke go2rtc.yaml (gitignored, isi kredensial RTSP)
│   ├── mosquitto/mosquitto.conf
│   ├── systemd/              # isentinel-api.service, isentinel-recorder.service,
│   │                         #   vision-node.service, isentinel-retention.service
│   └── sql/                  # alembic migrations
├── docs/plans/               # spec desain awal + milestone tersisa (Edge Jetson)
├── docs/superpowers/         # spec + plan per fitur (catatan)
├── docs/runbooks/            # prosedur operasional per fitur
└── README.md
```

## Run (dev lokal)

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Frontend (dev server dengan proxy ke API):

```bash
cd frontend
npm install
npm run dev
npm test          # vitest run
```

## Run (server dev)

```bash
ssh gspe-ai3
cd /home/gspe-ai3/project_cv/I-Sentinel && git pull
./deploy/bootstrap.sh
# isi .env di root project (DATABASE_URL postgres, JWT_SECRET, ADMIN_PASSWORD, CAM_USERNAME/PASSWORD)
sudo systemctl start isentinel-api
curl -s localhost:8000/api/v1/health
```

`bootstrap.sh` membuat venv, install `backend[dev]`, `alembic upgrade head`, menyalin unit systemd ke `/etc/systemd/system/`, lalu daemon-reload + enable (tidak start).

## Manajemen Kamera

Registrasi kamera cukup lewat **Konfigurasi → Kamera → + Tambah kamera**:

1. Isi **Nama kamera**, **Lokasi** (pilih dari kamera lain atau ketik baru), **IP kamera**
   (port opsional: `192.168.2.179:8554`), **Path mainstream** (wajib), **Path substream**
   (kosong = pakai mainstream).
2. Pilih **Kredensial**: `Default (NVR)` (fallback `CAM_USERNAME`/`CAM_PASSWORD` dari `.env`)
   atau profil khusus; **+ Kredensial baru…** langsung membuat profil (Nama, Username, Password).
3. Klik **Tes koneksi** — probe menampilkan res/fps/codec MAIN & SUB + thumbnail substream;
   peringatan muncul bila substream sama dengan mainstream (AI memproses resolusi penuh).
   Tempel URL RTSP berisi password ke kolom path pun aman — yang terkirim hanya path.
4. **Simpan** — bila belum dites muncul peringatan; klik **Simpan** sekali lagi untuk tetap
   menyimpan.

**Lanjutan** (tertutup default): **Node** (hanya bila node > 1) dan **Deteksi otomatis** —
backend memindai channel NVR (pola Hikvision `/Streaming/Channels/<ch>`, wave paralel, berhenti
setelah 2 wave kosong) dan menampilkan dropdown channel; memilih channel mengisi path main/sub.
Menu **Lanjutan** di header halaman berisi Import CCTV, Sync go2rtc, dan **Kelola kredensial**
(ubah username/password — password dikosongkan = tidak diganti; nonaktifkan ditolak bila profil
masih dipakai kamera aktif; tambah profil baru).

Aturan yang perlu diketahui:

- **Grup lokasi otomatis** dari teks Lokasi (get-or-create, tidak diinput manual).
- **Password kamera tidak pernah tampil di UI atau DB.** Default: kredensial dari `.env`
  (`CAM_USERNAME`/`CAM_PASSWORD`). Kredensial khusus dibuat via Kelola kredensial: DB hanya
  menyimpan referensi `store:cred_<id>`; password aslinya di file rahasia server
  `CAMERA_SECRETS_FILE` (default `~/.isentinel/camera-secrets.json`, izin `0600`, direktori
  `0700`, WAJIB di luar `STORAGE_ROOT`).
- **Backup**: file rahasia tersebut harus ikut dibackup bersama DB — tanpa file itu, kamera
  berkredensial khusus gagal konek ("credential reference is unavailable").
- **Rollback** (`git revert`): kamera berprofil `store:` dikembalikan ke Default (NVR) atau
  `env:` SEBELUM revert, karena referensi `store:` tidak bisa di-resolve oleh kode lama.
- Duplikat nama-per-node atau duplikat stream ditolak (409) dan ditampilkan
  sebagai InlineNotification.
- Menghapus kamera tidak menghapus riwayat: `event` dan `alert` tetap
  (migration `0008`, FK `ON DELETE SET NULL`).
- List kamera memakai kolom terpisah Nama/Lokasi + kolom **Kredensial**; Live View filter
  lokasi bisa direset ke **All locations**.
- **Deteksi hanya berjalan di kamera yang punya zona aktif.** Zona (behavior + absensi) diatur
  di satu tempat — tab **Zona Deteksi** — termasuk Snapshot/Clip per behavior; kamera tanpa zona
  aktif tetap bisa dipantau di Live View, tetapi tidak menghasilkan event/klip. Chip analyzer
  per kamera (kolom `camera.analyzers`) sudah tidak dipakai.
- **Zona kosong (Idle Zone)**: aktif bila tak ada orang di poligon selama `trigger_seconds` (default
  300 detik). **Kerumunan (Crowd)**: aktif bila jumlah orang di poligon mencapai `min_count` (default 5)
  selama `trigger_seconds` (default 30 detik); penurunan jumlah ≤ 5 detik ditoleransi. Keduanya
  mengirim event awal, lalu pengingat tiap `reminder_minutes` (default 15; 0 = tanpa pengingat)
  selama kondisi berlanjut; pulih → siaga lagi. Snapshot idle menggambar poligon, crowd
  menggambar semua kotak orang. Clip idle default mati saat behavior baru dicentang.
- Jadwal zona: **24/7**, **Jam tertentu**, atau **Ikut shift** (satu shift). Pilihan shift
  mengikuti perubahan jam/hari shift lewat config push; shift yang dipakai zona tidak bisa dihapus.
  Jadwal manual dan shift memakai jam dinding lokal (termasuk frame vision bertimestamp monotonic).
  Shift malam/jadwal lintas tengah malam belum didukung; gunakan rentang dalam satu hari.

Prosedur operasional (restart, backup, tambah kamera, pin GPU, troubleshooting,
load test): lihat **`docs/RUNBOOK.md`**. Unit systemd di `deploy/systemd/` kini
sudah direkonsiliasi dengan yang berjalan di `gspe-ai3` (Fase 5 Task 12):
`User=gspe-ai3` + path `/home/gspe-ai3/project_cv/I-Sentinel`. `sudo` tanpa
password tidak tersedia di server, jadi restart service dilakukan lewat
`kill $(cat /sys/fs/cgroup/system.slice/<unit>.service/cgroup.procs)` (unit
memakai `Restart=always`).

## Live View & Mode TV

Live View (halaman **Live**) menampilkan grid kamera: pilih 2/3/4 kolom, dan pilih kamera
mana yang tampil lewat **Kamera (n/m)** (checkbox per kamera, dikelompokkan per lokasi).
Pengaturan ini tersimpan per layar di `localStorage`.

Tombol **Mode TV** membuka kiosk `/live/tv?screen=<nama>` — tanpa header/side-nav,
untuk layar TV command center (runbook Pi: `docs/runbooks/live-view-tv-pi.md`):

- **Pengaturan per layar**: `?screen=A` dan `?screen=B` menyimpan kolom/pilihan/auto-scroll
  terpisah (dua jendela TV di satu Pi). `?screen=` tidak dikenal → `default`.
- **Stream hanya tile terlihat**: tile di luar viewport menampilkan snapshot terakhir;
  `<video-stream>` hanya di-mount untuk tile dekat layar (pra-muat 50 % viewport).
- **Pulih sendiri**: tile yang gagal stream dicoba ulang tiap 60 detik; snapshot tampil
  sampai video benar-benar `playing`.
- **Auto-scroll**: gulir halus turun, jeda 5 detik di dasar, kembali ke atas. Berhenti
  saat operator aktif (mouse/keyboard; lanjut 10 s setelah diam) atau pemilih/debugger
  terbuka. Toolbar auto-hide 4 detik (kursor ikut disembunyikan).
- **Sesi bergulir 48 jam**: cookie login diperpanjang otomatis selama halaman aktif
  me-refresh (`ACCESS_TOKEN_EXPIRE_MIN`, default 2880) — TV tidak logout tiba-tiba.

**Notifikasi event.** Event behavior (intrusion, loitering, running, idle zone, crowd) dan node offline memunculkan
badge di lonceng header (panel dua tab **Hari ini** / **Kemarin**, klik → detail event), toast 8 detik, dan bunyi pendek (bisa di-mute di
lonceng atau toolbar mode TV; status dibaca & mute disimpan per browser). Di Live View, tile kamera yang kena event
diberi outline warna severity selama 30 detik; bila tile sedang di luar layar muncul chip di kanan bawah. Absensi
tidak memicu notifikasi. Notifikasi OS tidak tersedia karena app diakses lewat `http://` LAN.

## User management

Tab **User** di Konfigurasi (admin-only): daftar username, role, status, dibuat, login terakhir;
tombol **+ Tambah user**, dan per baris: jadikan admin/viewer, reset password, nonaktifkan/aktifkan,
hapus. Akun sendiri ditandai "(Anda)" — ubah role/nonaktif/hapus dinonaktifkan untuk diri sendiri.

- **2 role**: `admin` (semua konfigurasi + enrollment + koreksi) dan `viewer` (read-only semua
  menu). Akun TV sebaiknya `viewer` khusus.
- **Nonaktifkan/aktifkan**: akun nonaktif tidak bisa login (pesan khusus hanya muncul untuk
  pemegang password benar) dan sesi aktifnya langsung ditolak.
- **Reset password** (admin) dan **ganti password sendiri** (tombol **Password** di kartu akun
  sidebar, **khusus admin** — password viewer/akun TV diatur admin lewat reset) menaikkan
  `token_version` → semua sesi lain user itu keluar; browser yang mengganti password tetap login
  (cookie baru dari server).
- Halaman login punya tombol tampilkan/sembunyikan password.
- **Aturan password**: minimal 8 karakter, maksimal 72 byte (batas bcrypt); konfirmasi divalidasi
  di form. Username: 3–64 karakter `[A-Za-z0-9._-]`.
- **Pencabutan sesi**: JWT membawa klaim versi (`tv`); token versi lama atau akun nonaktif → 401.
  Token yang terbit sebelum fitur ini (tanpa `tv`) tetap berlaku sampai password diganti/akun
  dinonaktifkan — deploy tidak mengeluarkan semua orang.

## Attendance (absensi)

Halaman **Attendance** (`/attendance`) punya tiga tab: **Harian** (ringkasan tanggal
tertentu), **Rentang tanggal**, dan **Per karyawan**. Rentang/Per karyawan menampilkan
tabel datar dengan kolom **Tanggal** (format lokal pendek, urut terbaru dulu); Entry/Exit
ditampilkan `HH:MM` (WIB). Tile ringkasan Harian (Hadir, Di dalam, Perlu koreksi,
Tidak hadir) bisa diklik untuk menyaring baris; tab Rentang/Per karyawan punya chip
filter status yang sama. Baris yang dikoreksi manual ditandai ikon pensil dengan
tooltip berisi catatan.

Arti status:

- **TEPAT WAKTU / TELAT n MNT**: entry + exit terdeteksi; durasi = exit − entry.
- **DI DALAM** (`waiting`): entry tanpa exit, belum lewat batas. Untuk hari ini
  durasinya dihitung live tiap menit (`3j 10m · berjalan`); untuk hari lampau tampil `—`.
- **TANPA EXIT — PERLU KOREKSI** (`no_exit`): entry tanpa exit setelah batas.
- **TANPA ENTRY — PERLU KOREKSI** (`no_entry`): hanya exit yang terdeteksi
  (orangnya hadir tapi entry terlewat). Durasi tidak dihitung untuk keduanya.
- **TIDAK HADIR** (`absent`): karyawan aktif terjadwal kerja tanpa deteksi apa pun —
  dibuat **otomatis** setelah batas.

Batas hari = **jam selesai shift + `NO_EXIT_GRACE_MIN`** (default 60 menit, tz server).
Sebuah job latar (`AttendanceCloser`) menutup hari tiap **15 menit** — termasuk
catch-up **7 hari ke belakang** saat API start — sehingga baris "Tidak hadir" dan
"Tanpa exit" muncul tanpa menunggu event baru; status yang lewat batas juga langsung
tampil benar saat dibaca walau job belum jalan. Karyawan tanpa shift tidak pernah
otomatis "Tidak hadir"/"Tanpa exit".

**Koreksi manual** (admin): klik baris mana pun, atau tombol **Koreksi** di baris
`no_exit`/`no_entry`, isi status/jam + catatan wajib. Baris yang sudah dikoreksi
**tidak pernah diubah** oleh job penutupan maupun status efektif — koreksi tetap
terjaga sampai event absensi baru masuk untuk hari itu.

Detail operasional: `docs/runbooks/attendance.md`.

## Retensi & Storage

Tab **Storage** di Konfigurasi: pemakaian disk, ukuran per jenis media (clips/snapshots/crops),
sweep retensi manual (admin), pengaturan retensi, dan (admin) pembersihan event per rentang tanggal.

- **Retensi editable dari UI**: `GET/PUT /api/v1/storage/settings` menyimpan clip dan snapshot
  **terpisah** (`clip_days`, `snapshot_days`, `attendance_days` untuk media absensi, 1–3650 hari) plus ambang peringatan disk
  (`disk_alert_percent`, 50–99 %). Nilai disimpan di tabel `setting` (key `storage`) — tanpa migrasi.
  Field yang belum pernah disimpan tetap mengikuti `RETENTION_DAYS` di `.env`; sweep harian systemd
  (`isentinel-retention.timer`) membaca nilai DB, jadi perubahan berlaku pada sweep berikutnya tanpa
  restart. Viewer melihat nilainya read-only (PUT tetap admin-only).
- **Sweep terpisah clip vs snapshot**: event yang lebih tua dari `clip_days` kehilangan clip, yang
  lebih tua dari `snapshot_days` kehilangan snapshot. **Media absensi** (snapshot + crop wajah
  `payload.crop_path`) mengikuti `attendance_days`; `crop_path` di-null-kan saat crop dihapus (Inbox
  tanpa gambar rusak). Baris absensi, rekap, dan foto enrollment (`faces/`) tidak pernah dihapus.
  Clip insiden yang masih dirujuk event lebih baru tidak dihapus; file orphan disapu per jenis
  (`crops/` ikut `attendance_days`; crop yang masih dirujuk bukan orphan). Hasil sweep mencatat
  `clip_days`/`snapshot_days`/`attendance_days`.
- **Event tanpa media dihapus**: event = bukti visual. Saat retensi/cleanup menghapus media **terakhir**
  sebuah event (clip, snapshot, dan crop semuanya habis), baris event + alert-nya ikut dihapus → card hilang
  dari Events (hasil sweep: `events_deleted`). Berlaku untuk behavior & absensi (rekap `attendance_day` dan
  riwayat `attendance_event` tetap); log `system` dikecualikan; event baru yang medianya masih menyusul tidak
  tersentuh (hanya event ber-`media_expired`). Mode cleanup "Media absensi saja" ikut menghapus entri Inbox-nya.
- **Behavior wajib punya media**: Zona Deteksi menolak behavior aktif dengan Snapshot **dan** Clip off
  (peringatan merah + Simpan nonaktif; backend 422 `needs snapshot or clip`; attendance wajib snapshot).
- **Bersihkan event per rentang tanggal** (admin): pilih tanggal dari/sampai (maks hari ini), opsional
  kamera dan jenis (`intrusion`/`loitering`/`running`/`idle_zone`/`crowd`/`system`) → **Pratinjau**
  (dry run) menampilkan "N event · M file · X" → **Hapus** dengan konfirmasi merah. Yang dihapus: baris
  event, clip/snapshot-nya, dan alert-nya. **Event `attendance`** (rekap absensi) **tidak pernah dihapus**,
  juga bila diminta eksplisit. **Log `system`** (node offline/LWT, satu baris tiap vision-node restart)
  hanya terhapus bila dipilih di Jenis — filter Jenis kosong tidak menyentuhnya. Mode **Media absensi
  saja** (`mode: "attendance_media"`) menghapus semua media event absensi di rentang — foto, crop wajah, dan
  clip lama (event absensi sebelum 25 Sep 2026 masih punya clip dari pipeline lama; tidak tampil di UI) (path
  `event.snapshot_path`, `payload.crop_path`, `attendance_event.snapshot_path` di-null-kan); event,
  riwayat masuk/keluar, dan rekap `attendance_day` tetap. Clip yang masih
  dirujuk event di luar rentang dipertahankan; crop (`payload.crop_path`) tidak dikumpulkan cleanup dan
  dibiarkan ke sapuan orphan. Rentang memakai zona waktu lokal server (`[dari 00:00, sampai+1 hari 00:00)`)
  dan **tidak bisa dipulihkan** — karena itu tombol Hapus baru aktif setelah pratinjau untuk filter yang
  sama, dan jumlah pada konfirmasi berasal dari pratinjau saat itu (event baru yang masuk ke rentang
  sebelum konfirmasi tetap ikut terhapus).
- **Peringatan disk hampir penuh**: banner merah di tab Storage dan Dashboard saat pemakaian ≥ ambang;
  thread API memeriksa tiap 10 menit dan mengirim Telegram "⚠️ Disk hampir penuh …" dengan pengingat
  berulang dibatasi sekali per 24 jam, serta "✅ Disk pulih" saat pemakaian turun di bawah ambang − 2 %
  (setelah pulih, kenaikan lagi di atas ambang mengirim pesan baru). Tanpa token/grup Telegram state tetap
  diperbarui (banner tetap jalan) dan tidak ada error. Token tidak pernah masuk log/pesan.
- **Data absensi (rekap & riwayat), admin, permanen** (`mode: "attendance_data"`): untuk server dengan
  campuran karyawan uji dan nyata. Pilih karyawan (wajib) atau centang "Semua karyawan", tanggal
  maksimum **kemarin** (shift hari ini bisa masih berjalan) → **Pratinjau** menampilkan ringkasan +
  tabel per karyawan → **Hapus data absensi** mengunci sampai kata `HAPUS` diketik di modal konfirmasi.
  Menghapus permanen `attendance_event`, `attendance_day` (**termasuk `override_note`**), event Inbox
  `attendance` terkait, dan medianya untuk seleksi itu; "Semua karyawan" juga menghapus event wajah
  tak dikenal di rentang tersebut, filter karyawan tidak. File yang masih dirujuk baris di luar
  seleksi dipertahankan. Audit log mencatat ID karyawan dan jumlah, **tidak pernah nama**. Ekspor CSV
  attendance untuk rentang yang dibersihkan akan kosong sesudahnya — tidak bisa dipulihkan.

## Alert Telegram

Kirim foto + caption kejadian ke grup staf. Tanpa dependensi baru (klien stdlib),
tanpa migrasi DB.

**Menyambungkan bot + grup** (satu kali, oleh admin):

1. **@BotFather** → `/newbot` (atau pakai bot yang ada) → salin **token**
   (`123456789:AA...`).
2. Tambahkan bot ke **grup staf**, lalu kirim satu pesan apa pun di grup itu agar
   bot melihat `chat_id`-nya.
3. Buka **Konfigurasi → Notifikasi**: tempel token → **Simpan** → **Deteksi grup**
   → pilih grup dari daftar → **Simpan** → **Kirim pesan uji**. Chip status menjadi
   *Siap* dan pesan uji masuk ke grup.
4. **Zona Deteksi**: nyalakan toggle **Telegram** per behavior (intrusi/loitering/
   berlari/Idle Zone/Crowd/absensi) pada zona yang boleh mengirim alert. Tanpa toggle aktif,
   event tetap tercatat tapi tidak dikirim.

Yang perlu diketahui:

- **Snapshot ikut terkirim keluar LAN** (foto kejadian diunggah ke Telegram). Tautan
  klip hanya menunjuk aplikasi (`.../events?event=<id>`) yang bisa dibuka **dari LAN
  saja** — Telegram tidak membawa video.
- **Token disimpan di file rahasia server** `CAMERA_SECRETS_FILE` (key
  `telegram_bot_token`, izin `0600`, di luar `STORAGE_ROOT`) — bukan di DB dan tidak
  pernah tampil di UI/log/response. `TELEGRAM_BOT_TOKEN` di `.env` hanya fallback.
- **Kirim berjalan di thread terpisah** — konsumen MQTT tidak pernah menunggu
  jaringan Telegram. Rate-limit per kamera, zona, tipe, dan `track_id`: severity
  critical tanpa batas, lainnya 2 menit; absensi tercatat tanpa batas. Pengingat
  Idle Zone/Crowd mengikuti interval yang diatur, termasuk interval < 2 menit.
  Event tanpa `track_id` dikelompokkan per kamera/zona/tipe. Status alert
  (`queued/sent/failed/rate_limited/not_configured`) tampil di Inbox.
- **Format pesan**: foto snapshot dengan caption HTML — judul tebal berbahasa
  Inggris (`INTRUSION`, `LOITERING`, `RUNNING`, `IDLE ZONE`, `CROWD`,
  `ATTENDANCE — CHECK IN/OUT`, `UNKNOWN FACE`), lalu satu data per baris berlabel
  Indonesia (Nama/Kamera/Zona/Waktu/Level; idle: durasi kosong, crowd: jumlah orang)
  dan tautan klip di akhir. Pengingat ditandai di judul. Snapshot behavior berlabel
  jenis kejadian; snapshot absensi berlabel nama karyawan (atau `Unknown` oranye
  untuk wajah tak dikenal).

## Monitoring Resource

Halaman **System › Monitoring** (`/monitoring`) dapat dibuka **semua user** dan punya
tiga tab — **Kondisi saat ini** (`?tab=current`, default), **Tren** (`?tab=trend`), dan
**Aturan & alert** (`?tab=alerts`). Pengaturan aturan hanya dapat disimpan admin;
viewer melihat aturan dan alert dalam mode read-only.

- **Ringkasan**: status keseluruhan (terburuk dari kamera/node/layanan) + jumlah
  ok/peringatan/kritis per kelompok; halaman polling tiap 10 detik.
- **Kartu node + server pusat**: umur heartbeat, CPU/RAM/disk, per-GPU (util, VRAM,
  suhu, daya), inferensi (model/device, ms rata-rata & maks per jendela heartbeat,
  fps inferensi, antrean wajah, backlog MQTT), daftar masalah.
- **Tabel kamera**: state sumber AI (`streaming`/`starting`/`reconnecting`/`stalled`),
  fps aktual/target, umur frame terakhir, reconnect 1 jam, skip motion, status stream
  go2rtc; filter **Hanya bermasalah**; urut kritis → peringatan → sehat.
- **Layanan**: database, go2rtc, broker MQTT, sweep retensi, Telegram, disk — dicek
  dengan cache 10 detik; kegagalan menjadi status **kritis** tanpa membuat endpoint 500.

Sumber data: heartbeat vision tiap 10 detik (statistik per worker kamera, jendela
inferensi, host `/proc`, GPU NVML) yang disimpan apa adanya di JSON `node.hw` /
`node.modules` — **tanpa migrasi DB**. Node lama (vision versi sebelumnya) tetap
tampil; kamera ber-node yang belum mengirim statistik diberi `no_data`.

**Tab Tren** (S2 — riwayat & grafik):

- Rentang **1 jam / 6 jam / 24 jam / 7 hari** (tersimpan di URL `?range=`), refresh
  otomatis tiap 60 detik; hanya tab aktif yang di-mount (polling S1 berhenti di tab Tren).
- Setiap heartbeat diagregasi ke **bucket per menit** (avg/max/min sesuai metrik: fps
  kamera = min+avg antar worker, state = terburuk) oleh `HistorySampler` dan disimpan di
  tabel `monitoring_sample` — ±1.440 baris/node/hari, **dipangkas otomatis setelah 7 hari**.
- Grafik **SVG buatan sendiri** (tanpa dependensi baru): CPU & RAM, util & VRAM per GPU,
  suhu GPU, latensi inferensi (rata-rata & maks), fps inferensi, backlog MQTT, dan per
  kamera (fps aktual vs garis putus-putus target + umur frame, maks 4 kamera dipilih).
- **Arsir merah** = periode node offline (dari event `system`); **celah pada garis** =
  tidak ada data (node offline / API restart kehilangan ≤ 1 menit bucket berjalan).
- Downsample per rentang: 1 jam & 6 jam per menit, 24 jam per 5 menit, 7 hari per
  30 menit. API: `GET /api/v1/monitoring/history?range=…` (semua user login; 422 bila
  rentang tidak valid).

**Tab Aturan & alert** (S3 — kesehatan berkelanjutan):

| Aturan | Ambang default | Durasi | Severity | Telegram |
|---|---|---|---|---|
| Kamera tanpa frame | > 30 s, atau kamera tidak ada di sampel node | 2 menit | Kritis | ON |
| FPS kamera rendah | < 50 % target (lewati `starting`/tanpa target) | 10 menit | Peringatan | OFF |
| GPU panas | ≥ 85 °C | 5 menit | Kritis | ON |
| VRAM GPU tinggi | ≥ 90 % | 10 menit | Peringatan | OFF |
| RAM node tinggi | ≥ 90 % | 10 menit | Peringatan | OFF |
| CPU node tinggi | ≥ 90 % | 10 menit | Peringatan | OFF |
| Latensi inferensi tinggi | ≥ 50 ms | 5 menit | Peringatan | OFF |
| Event tertahan di node | backlog MQTT > 0 | 5 menit | Peringatan | ON |

- Semua aturan default aktif. Admin mengatur aktif, ambang, durasi 1–60 menit,
  severity, dan Telegram per aturan; nilai disimpan di setting `health_rules`.
- Evaluator berjalan tiap menit setelah sampel S2 tersimpan: alert menyala hanya bila
  **setiap menit selesai** dalam durasi punya sampel dan melanggar. Pulih setelah
  **dua menit normal**; tidak ada pengingat ulang. Node offline atau tanpa sampel
  di lookback menahan alert, bukan memulihkannya.
- Event web selalu dibuat saat menyala/pulih; Telegram hanya bila toggle aturan ON.
  Aturan dinonaktifkan atau target hilang ditutup dengan event resolved tanpa Telegram.
- Alert aktif dan 50 riwayat terakhir ditampilkan, refresh 30 detik; riwayat resolved
  dipangkas setelah 7 hari. Alert kamera aktif memberi badge **Tanpa frame/FPS rendah**
  pada tile Live View dan TV, terpisah dari outline event baru.
- Ambang tab Kondisi saat ini mengikuti setting yang sama, meski aturan alert
  dinonaktifkan. Default `low_fps` halaman sengaja berubah **80 % → 50 % target**.
- API: `GET/PUT /api/v1/monitoring/rules` (PUT admin, invalid → 422);
  `GET /api/v1/monitoring/alerts`. Migrasi baru `0020_health_alert`; vision tidak berubah.

**Node offline/pulih** (event + Telegram + banner):

- Node dianggap offline bila LWT MQTT diterima atau heartbeat terakhir lebih tua dari
  **35 detik** (`NodeHealthMonitor`, cek tiap 15 detik). Transisi `online → offline`
  membuat satu event `system` warning (`reason: lwt|timeout`) + satu pesan Telegram;
  `offline → online` membuat event info `system` (`reason: online`) + Telegram "pulih".
  `unknown → online` (node baru) tidak membuat event.
- **Banner persisten** muncul di semua halaman (AppShell) dan mode TV selama ada node
  offline, dan hilang sendiri saat node kembali online; lonceng/toast menampilkan
  "Node pulih" tanpa chip offline.
- **LWT retained diperbaiki**: vision mempublikasikan `{"status":"online"}` retained
  saat connect sehingga retained "offline" lama dari broker tidak lagi membuat event
  "Node offline" palsu setiap kali API restart; backend mengabaikan payload LWT non-offline.

Kode masalah dan langkah penanganan: `docs/runbooks/monitoring.md`.
