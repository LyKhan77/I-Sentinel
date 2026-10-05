# I-Sentinel

Sistem surveillance AI **on-premise** untuk jaringan LAN/pabrik. Kamera RTSP (umumnya di balik NVR) diproses di server GPU
lokal: deteksi orang berbasis zona untuk keamanan, dan pengenalan wajah untuk absensi. Data disimpan lokal; fitur LLM opsional mengirim snapshot/keyframe ke endpoint yang dipilih operator.

| | |
|---|---|
| **Keamanan** | Zona poligon per kamera: intrusi, loitering, berlari, zona kosong, kerumunan. Snapshot + klip, Inbox Events, alert Telegram. |
| **Absensi** | Enrollment wajah (3 foto), gerbang wajah di kamera pintu, shift, rekap harian, ekspor/impor CSV. |
| **Operasional** | Live View + Mode TV, Dashboard, Monitoring dengan alert kesehatan, retensi storage, user admin/viewer. |

Status: pra-rilis `0.x`. Berjalan di Docker Compose (server dev `gspe-ai3` sejak 2026-10-02).

**Isi:** [Arsitektur](#arsitektur) · [Instalasi](#instalasi) · [Penyiapan pertama](#penyiapan-pertama) ·
[Operasi harian](#operasi-harian) · [Panduan fitur](#panduan-fitur) · [Pengembangan](#pengembangan) · [Peta dokumen](#peta-dokumen)

## Arsitektur

```text
Browser (LAN)
  ├─ :7700  web (nginx: UI + proxy /api) ─────► api :7701 ─────► postgres (internal)
  └─ :7702 / :7703  go2rtc  (video langsung: WebRTC / MSE)

Kamera / NVR ──RTSP──► go2rtc ──RTSP internal──► vision (GPU: YOLO26s + wajah)
vision ──MQTT :7704──► mosquitto ◄──► api        (heartbeat, event, config node)
vision ──HTTP internal──► api                    (unggah snapshot / klip)
retention                                        (sapuan harian pukul 03:00: DB + file)
```

| Layanan | Fungsi | Port host | Akses |
|---|---|---|---|
| `web` | UI React (build statis) + proxy `/api` dan WebSocket | `7700` | LAN |
| `api` | Backend FastAPI, konsumen MQTT, alert, retensi data | `7701` | LAN (juga untuk node edge, Fase E) |
| `go2rtc` | Jembatan RTSP → WebRTC / MSE / snapshot | `7702`, `7703` (TCP+UDP) | LAN (browser memutar langsung) |
| `mosquitto` | Broker MQTT (event, heartbeat, config, LWT) | `7704` | LAN, wajib kredensial |
| `vision` | Deteksi (YOLO26s TensorRT + ByteTrack), wajah, rekam klip | tanpa port | internal; memakai GPU |
| `postgres` | Database | tanpa port | internal (named volume `pgdata`) |
| `retention` | Sapuan retensi harian | tanpa port | internal |

RTSP go2rtc (`7705`) hanya di jaringan internal Compose. Port yang dipublikasikan Docker melewati filter firewall host
(terbukti di server dev) dan tidak ada TLS: pasang di LAN tepercaya, bukan di internet. Detail kontrak MQTT/HTTP/WS dan
alur data: [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Instalasi

**Persyaratan server (Linux):**

- Docker Engine dengan Compose v2, dan akun Anda di grup `docker` (tanpa `sudo`). `docker.service` enabled agar container naik lagi setelah reboot.
- **NVIDIA driver + NVIDIA Container Toolkit** untuk deteksi. Tanpa runtime `nvidia`, `setup.sh` memberi peringatan dan menjalankan stack **tanpa vision** (UI dan Live View tetap jalan, tanpa deteksi).
- `python3` dan `openssl` di host (dipakai skrip setup).
- Port `7700–7704` TCP dan `7703` UDP kosong (`setup.sh` berhenti bila ada yang terpakai).
- Internet saat instalasi: unduh image dan model. Siapkan ±20 GB disk untuk image (vision ±15 GB) di luar ruang media.

**Langkah:**

```bash
git clone <URL_REPO> I-Sentinel
cd I-Sentinel
./docker/setup.sh
```

Server dengan lebih dari satu kartu jaringan atau VPN: tentukan IP LAN yang dilihat klien agar WebRTC berfungsi, mis.
`GO2RTC_PUBLIC_HOST=192.168.2.133 ./docker/setup.sh`. Nilai ini ditulis sekali ke `go2rtc.yaml`.

`setup.sh` membuat semuanya: memeriksa prasyarat, menulis `docker/.env` (rahasia acak, mode `0600`), menyiapkan folder data
(`../I-Sentinel-docker-data`), membuat password broker MQTT, membangun image, menyalakan layanan, menjalankan migrasi database
otomatis, mengunduh model wajah, membangun engine TensorRT, lalu menyalakan sisanya. Instalasi pertama memakan ±25–30 menit
(sebagian besar unduhan image vision); berikutnya hanya hitungan detik sampai menit.

Hasil di akhir: alamat `http://<IP-LAN>:7700`, user `admin`, dan **password admin dicetak sekali saja** (selanjutnya hanya di
`docker/.env`, jangan disalin ke log atau git). Skrip ini aman diulang (idempoten): tidak menimpa `.env`, password MQTT, atau
`go2rtc.yaml`.

**Model** (tidak ada yang disimpan di git):

| Model | Fungsi | Sumber | Lokasi |
|---|---|---|---|
| YOLO26s | Deteksi orang | `yolo26s.pt` (20 MB) diunduh otomatis oleh Ultralytics saat ekspor, lalu dikompilasi menjadi engine TensorRT FP16 (±20 detik) di GPU server | `<DATA_DIR>/models/yolo26s.engine` |
| InsightFace `buffalo_l` | Pengenalan wajah | Diunduh otomatis (±280 MB); bila gagal hanya muncul peringatan, jalankan ulang `setup.sh` | `<DATA_DIR>/api/faces_models` |

Engine TensorRT hanya valid untuk **satu jenis GPU**; jangan disalin antar tipe GPU yang berbeda. Server tanpa internet:
letakkan `yolo26s.pt` di `<DATA_DIR>/models/` dan folder `models/buffalo_l` di `<DATA_DIR>/api/faces_models/` sebelum menjalankan
`setup.sh`. Server multi-GPU: engine dibangun di GPU `VISION_ENGINE_GPU` (default 0); bila GPU lain dipakai,
`./docker/scripts/export-engine.sh <nomor-GPU>`.

**Opsi** (set sebagai variabel lingkungan saat menjalankan `setup.sh` pertama kali; selanjutnya `docker/.env` yang berlaku):
`DATA_DIR` (lokasi data), `GO2RTC_PUBLIC_HOST`, `TZ`, `VISION_ENGINE_GPU`, `VISION_SHM_SIZE` (default `2gb`, memadai untuk puluhan kamera),
`RETENTION_DAYS`. Flag: `--no-engine` (lewati ekspor engine), `--env-only` (hanya buat konfigurasi, tanpa Docker).

**Lokasi data** (`../I-Sentinel-docker-data/`): `api/` (media: clips, snapshots, crops, faces, faces_models), `vision/`, `models/`,
`go2rtc/` (`go2rtc.yaml` berisi kredensial RTSP kamera, perlakukan sebagai rahasia), `mosquitto/`, `secrets/`
(`camera.env`, `camera-secrets.json`, `llm.env`). Database ada di named volume `pgdata`.

## Penyiapan pertama

Instalasi menghasilkan sistem kosong. Urutan berikut membawa Anda dari login sampai deteksi berjalan:

| # | Langkah | Di mana | Hasil |
|---|---|---|---|
| 1 | Login `admin`, lalu ganti password | tombol **Password** di kartu akun sidebar (khusus admin) | akun aman |
| 2 | Siapkan kredensial kamera/NVR | **Konfigurasi → Kamera → Lanjutan → Kelola kredensial**; atau isi `CAM_USERNAME`/`CAM_PASSWORD` di `<DATA_DIR>/secrets/camera.env` lalu `./docker/setup.sh` | pilihan kredensial tersedia |
| 3 | Tambah kamera | **Konfigurasi → Kamera → + Tambah kamera → Tes koneksi → Simpan** | otomatis terdaftar di go2rtc dan dikirim ke node; tampil di **Live View** |
| 4 | (Opsional) Pilih GPU | **Konfigurasi → Node** (satu GPU: biarkan tanpa pin) | detektor dan wajah dipin ke GPU |
| 5 | Buat zona deteksi | **Konfigurasi → Zona Deteksi**: gambar poligon, pilih behavior, jadwal, Snapshot/Clip, toggle Telegram | **deteksi aktif hanya di kamera yang punya zona aktif** |
| 6 | (Opsional) Telegram | **Konfigurasi → Notifikasi** | alert foto ke grup staf |
| 7 | (Opsional) Absensi | **Enrollment → Shift** (buat shift), **Enrollment → Karyawan** (3 foto), lalu zona absensi di kamera pintu (langkah 5) | rekap di **Attendance** |
| 8 | Verifikasi | **Dashboard** (kamera sehat, node `online`) dan **Monitoring** | sistem siap |

Penting: menambah kamera saja sudah cukup untuk **Live View**. Tanpa zona aktif kamera tidak menghasilkan event atau klip.
Kredensial: bila "Default (NVR)" gagal pada instalasi baru, `camera.env` masih kosong (langkah 2). Rincian tiap fitur ada di
[Panduan fitur](#panduan-fitur).

## Operasi harian

Jalankan dari folder `docker/` (Compose otomatis memakai `docker/.env`):

```bash
cd I-Sentinel/docker
docker compose ps                         # semua layanan harus healthy / running
docker compose logs --tail 100 api        # log layanan: api, vision, go2rtc, mosquitto, postgres, web, retention
docker compose restart api                # restart satu layanan
curl -s localhost:7701/api/v1/health      # {"status":"ok"}
```

- **Update versi:** `git pull && ./docker/setup.sh` (membangun ulang image yang berubah, migrasi database otomatis).
- **Backup:** salin `<DATA_DIR>` (termasuk `secrets/` dan `go2rtc/`) dan `docker/.env`; database terpisah:
  `docker compose exec -T postgres pg_dump -U isentinel --no-owner --no-privileges isentinel > cadangan.sql` (simpan di luar repo, mode privat).
  Tidak ada backup otomatis.
- **Retensi:** container `retention` menyapu media dan event lama tiap hari pukul 03:00 (`TZ`); atur masa simpan di **Konfigurasi → Retensi & Storage**.
- **Setelah reboot server:** container naik sendiri (`restart: unless-stopped`).

**Masalah umum**

| Gejala | Periksa |
|---|---|
| Live View hitam atau hanya snapshot | `curl -s localhost:7702/api/streams` memuat `cam_<id>`; kredensial kamera benar; `GO2RTC_PUBLIC_HOST` adalah IP LAN (bukan `127.0.0.1`); UDP `7703` terjangkau dari klien; **Lanjutan → Sync go2rtc** |
| Tidak ada event | ada zona **aktif** di kamera; node `online`; `docker compose logs vision` memuat `started N worker(s)` dengan N > 0 |
| Node `offline` / log API `heartbeat for unknown node` | `VISION_NODE_ID` di `docker/.env` harus **nama** node (`server`), bukan angka |
| Vision tidak berjalan | runtime NVIDIA tidak ada (`docker info` tanpa `nvidia`): pasang toolkit lalu ulangi `./docker/setup.sh` |
| CPU container vision tinggi, log `CUDAExecutionProvider is not in available provider names` | wajah jatuh ke CPU: bangun ulang image vision (`./docker/setup.sh`) |
| `setup.sh` berhenti "Port … in use" | hentikan layanan lain di `7700–7704`; port ini tetap |
| Disk hampir penuh | **Konfigurasi → Retensi & Storage** (kurangi masa simpan, bersihkan event) |

Prosedur lengkap (backup, rollback, pin GPU, load test, cutover dari sistem lama): [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Panduan fitur

Rincian perilaku tiap fitur. Alur lengkap per fitur ada di [`WORKFLOW.md`](WORKFLOW.md).

- [Manajemen Kamera](#manajemen-kamera): wizard, kredensial, zona, jadwal
- [Live View & Mode TV](#live-view--mode-tv): grid, TV, notifikasi, Inbox Events
- [Dashboard](#dashboard) · [User management](#user-management) · [Attendance](#attendance-absensi)
- [Retensi & Storage](#retensi--storage) · [Alert Telegram](#alert-telegram) · [Monitoring Resource](#monitoring-resource)

## Manajemen Kamera

Registrasi kamera cukup lewat **Konfigurasi → Kamera → + Tambah kamera**:

1. Isi **Nama kamera**, **Lokasi** (pilih dari kamera lain atau ketik baru), **IP kamera**
   (port opsional: `192.168.2.179:8554`), **Path mainstream** (wajib), **Path substream**
   (kosong = pakai mainstream).
2. Pilih **Kredensial**: `Default (NVR)` (fallback `CAM_USERNAME`/`CAM_PASSWORD` dari `secrets/camera.env`)
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
- **Password kamera tidak pernah tampil di UI atau DB.** Default: kredensial dari `secrets/camera.env` (`CAM_USERNAME`/`CAM_PASSWORD`). Kredensial khusus dibuat via Kelola kredensial: DB hanya
  menyimpan referensi `store:cred_<id>`; password aslinya di file rahasia server
  `CAMERA_SECRETS_FILE` (di Docker: `<DATA_DIR>/secrets/camera-secrets.json`; default non-Docker `~/.isentinel/camera-secrets.json`; izin `0600`, direktori
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

Prosedur operasional lainnya (restart, backup, pin GPU, load test): lihat **`docs/RUNBOOK.md`**.

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

**Inbox Events.** `/events` master-detail: filter **Tipe, Kamera, Severity, dan Rentang waktu difilter di server**
(satu query; pencarian teks tetap di klien), tiap dropdown punya opsi **Semua** dan tombol **Atur ulang filter**
muncul saat ada filter non-default. Opsi Tipe statis dan berlabel lokal — termasuk grup **"Keamanan (tanpa
absensi)"** — dan Rentang bertambah **Hari ini** (sejak 00:00 lokal). **Filter hidup di URL** (`?type=&camera=
&severity=&range=&q=`): deep link, reload, dan Back/Forward memulihkannya; nilai tak valid jatuh ke default.
Daftar memuat 200 event per halaman dan tombol **Muat lebih banyak** menggabung halaman berikutnya (dedupe id)
sampai batas **1000 baris** → hitungan menjadi `N+ event` disertai petunjuk mempersempit filter. Event kamera
tetap memakai tab clip/snapshot/crop;
**event system** (node offline/pulih, health alert) memakai panel **Bukti**: fakta dari payload ditambah grafik tren
dengan garis ambang dan penanda waktu event — tanpa tab media dan tanpa menunggu klip. Event baru membawa serinya di
`payload.evidence` (digambar tanpa fetch, tetap ada walau retensi 7 hari terpangkas); event lama memakai
`/monitoring/history` (mode `from`/`to`, jendela maks 6 jam) — trennya hanya tersedia ≤ 7 hari. Alur lengkap:
`WORKFLOW.md §8`.

## Caption AI dan Tanya AI (opsional)

Fitur MVP tersedia di kode, **belum diuji di server/UI/LLM nyata**. Default `LLM_ENABLED=false`:
tidak ada panggilan LLM, panel disembunyikan, dan endpoint Tanya AI memberi 503 `disabled`.

- Admin mengaktifkan **Caption AI otomatis** per zona non-attendance, terpisah dari severity dan Telegram.
  Mode **Bawaan** memakai prompt per tipe; **Kustom** mengganti instruksi tipe saja (maksimal 600 karakter,
  spasi tepi dibuang, kosong menjadi bawaan). Pesan sistem dan batas tiga kalimat selalu dipertahankan.
- Caption diproses di latar setelah snapshot tersedia, dengan throttle per zona. Detail event menampilkan
  lencana **Dibuat AI** dan status menunggu/berhasil/gagal. AI tidak mengubah severity atau menekan alert.
- Semua user login, termasuk viewer, dapat memakai **Tanya AI**: preset atau pertanyaan maksimal 500 karakter.
  Snapshot disertai 6 keyframe klip ≤30 detik, atau 12 untuk klip lebih panjang. Klip gagal/hilang memberi
  jawaban snapshot saja (`frames_used=0`); preset temporal memerlukan klip. Cache preset tidak menghabiskan kuota.
  Riwayat browser maksimal enam giliran dikirim, direset saat event berganti; audit server tetap tersimpan.
- Attendance dan event system tidak dilayani AI. Hasil manual tidak mengisi kotak caption.
  Hasil berupa saran, bukan bukti pasti; benda kecil dan gambar malam bisa salah dikenali.
  `event_ai` mengikuti umur event dan dihapus oleh retensi/cleanup.

Admin mengatur LLM melalui **Konfigurasi → AI Integration**: aktif/nonaktif, URL API (base `/v1`),
model, kunci API, serta parameter lanjutan. Tab dan ketiga endpoint `/api/v1/ai/settings`
(GET/PUT dan POST `/test`) hanya untuk admin; viewer tetap dapat memakai Tanya AI.
**Tes koneksi** memakai nilai form tanpa menyimpan, dengan teks dan JPEG sintetis 64×64 (30 detik
per panggilan). Kunci form kosong memakai kunci tersimpan/env. Kunci tulis-saja di `secret_store`
(0600 di luar `storage_root`), tidak di respons atau tabel `setting`, dan dikosongkan setelah dikirim.

Prioritas **DB > env > default**: tabel `setting`, key `llm`, hanya menyimpan override non-rahasia.
**Reset ke env**: kosongkan field atau pilih tombol reset, lalu Simpan (`null` menghapus override).
Hapus kunci hanya menghapus kunci tersimpan; kunci env tetap menjadi fallback. Perubahan berlaku
pada panggilan berikutnya tanpa restart. Tanpa baris `llm`, perilaku startup tetap seperti sebelumnya.

`${DATA_DIR}/secrets/llm.env` tetap nilai awal/fallback `LLM_*` (0600, hanya container `api`);
`setup.sh` membuat template komentar tanpa menimpa file lama. Default: concurrency 2, antrean 100,
throttle caption 60 detik/zona, kuota Tanya AI 6/menit/user, timeout caption/ask 60/120 detik,
`LLM_MAX_TOKENS=1000`, `LLM_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":false}}`.
**`LLM_CONCURRENCY` dan `AI_QUEUE_MAX` tetap env dan hanya-baca di UI**; ubah file lalu recreate API.
Perubahan env memerlukan **recreate**, bukan `docker compose restart api`, dan tidak menimpa override DB.
Rollout tahap ini belum dilakukan; setelah review, rebuild `api` dan `web`, tanpa migrasi tambahan.
Panduan rollout/rollback: [`docs/RUNBOOK.md`](docs/RUNBOOK.md#caption-ai-dan-tanya-ai--rollout-terpisah).

**Sebelum produksi, konfirmasi kepada pemilik endpoint bahwa gambar tidak disimpan atau dipakai melatih model.
Snapshot dapat memuat wajah karyawan.** Jalankan satu proses API; semaphore, throttle, dan rate limit bersifat lokal proses.

## Dashboard

`/dashboard` satu layar status-first: **strip status** (summary Monitoring + health alert aktif, selalu
berteks) → **4 tile yang dapat diklik** (Kamera sehat → Monitoring; Event hari ini → `/events?type=security&range=today`
(filter yang sama dengan angka tile); Kehadiran hari
ini → Attendance; Disk → Konfigurasi tab Storage) → **chart event per jam** hari ini → **8 event terbaru**
(sumber realtime yang sama dengan lonceng: nama kamera, Tag severity dengan teks, thumbnail snapshot) →
**masalah aktif** (maks 5, critical dulu) + **node ringkas** (GPU util/VRAM; detail di Monitoring).
`GET /api/v1/events/stats/today` memperluas `total`/`by_type` dengan `by_severity`, `by_hour`,
`critical_by_hour` dan **mengecualikan tipe `attendance`** — "Event hari ini" adalah angka keamanan, sejajar
dengan isi lonceng. Data di-poll 15 detik per sumber; satu sumber gagal tidak mengosongkan blok lain
(tampil "—"/"Gagal memuat", bukan 0 palsu) dan strip menandai data basi. Alur lengkap: `WORKFLOW.md §15`.

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
  Field yang belum pernah disimpan tetap mengikuti `RETENTION_DAYS` di `docker/.env`; sweep harian (container `retention`, pukul 03:00 sesuai `TZ`) membaca nilai DB, jadi perubahan berlaku pada sweep berikutnya tanpa
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
  saja** — Telegram tidak membawa video. Tautan lama tetap membuka event yang dituju
  walau sudah di luar daftar terbaru (atau menampilkan peringatan bila sudah dihapus).
- **Token disimpan di file rahasia server** `CAMERA_SECRETS_FILE` (key
  `telegram_bot_token`, izin `0600`, di luar `STORAGE_ROOT`) — bukan di DB dan tidak
  pernah tampil di UI/log/response. `TELEGRAM_BOT_TOKEN` di `.env` hanya fallback (tidak diteruskan pada Docker: isi token lewat UI).
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

## Pengembangan

Dev lokal (tanpa Docker):

```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && alembic upgrade head
uvicorn app.main:app --reload --port 8000
# frontend (proxy /api ke http://localhost:8000; ubah dengan env API_URL)
cd frontend && npm install && npm run dev
```

Tes: backend `pytest tests -q -m "not gpu"`, vision `pytest tests -q -m "not gpu"` (dari `vision/`), frontend `npx vitest run`
lalu `npm run build` dan `npm run lint`, infrastruktur Docker `pytest docker/tests -q`. Jalankan berurutan, bukan bersamaan.
Aturan kerja, konvensi, dan alur branch/commit: [`AGENTS.md`](AGENTS.md) dan [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

```text
I-Sentinel/
├── backend/            FastAPI: app/{api,core,models,schemas,services,ws}, alembic/, scripts/, tests/
├── vision/             vision node (deployable): vision/{node,recorder,pipeline,analyzers,transport,face*}, scripts/, tests/
├── frontend/           React 19 + Vite + Carbon: src/{app,features,components,api}
├── docker/             compose.yml, setup.sh, Dockerfile (backend, vision, web), scripts/, tests/
├── deploy/             legacy: unit systemd, bootstrap.sh, template go2rtc/mosquitto, loadtest/ (rollback dan uji beban)
└── docs/               DEVELOPMENT, RUNBOOK, runbooks/ (per fitur), superpowers/ (spec + plan), plans/
```

## Peta dokumen

| Dokumen | Isi |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | komponen, kontrak MQTT/HTTP/WS, alur data, topologi Docker |
| [`WORKFLOW.md`](WORKFLOW.md) | alur per fitur (kamera, zona, event, absensi, monitoring) |
| [`DESIGN.md`](DESIGN.md) | pedoman desain UI |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | operasi server: backup, rollback, pin GPU, troubleshooting, cutover |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | siklus pengembangan, verifikasi, deploy |
| [`docs/runbooks/`](docs/runbooks/) | prosedur per fitur: absensi, monitoring, retensi/storage, Live View TV (Raspberry Pi) |
| [`ROADMAP.md`](ROADMAP.md) · [`CHANGELOG.md`](CHANGELOG.md) | status fase dan bukti · riwayat perubahan |
| [`docs/superpowers/`](docs/superpowers/) | spec dan plan tiap fitur (catatan) |
