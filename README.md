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
│   ├── analyzers/            # intrusion.py, loitering.py, running.py (face: face_worker.py di vision/vision/)
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
├── docs/plans/               # spec + rencana per milestone
├── mockup-ui/                # mockup disetujui
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

Detail migrasi skema: `docs/runbooks/camera-management-migration.md`.

Prosedur operasional (restart, backup, tambah kamera, pin GPU, troubleshooting,
load test): lihat **`docs/RUNBOOK.md`**. Unit systemd di `deploy/systemd/` kini
sudah direkonsiliasi dengan yang berjalan di `gspe-ai3` (Fase 5 Task 12):
`User=gspe-ai3` + path `/home/gspe-ai3/project_cv/I-Sentinel`. `sudo` tanpa
password tidak tersedia di server, jadi restart service dilakukan lewat
`kill $(cat /sys/fs/cgroup/system.slice/<unit>.service/cgroup.procs)` (unit
memakai `Restart=always`).

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
   berlari/absensi) pada zona yang boleh mengirim alert. Tanpa toggle aktif, event
   tetap tercatat tapi tidak dikirim.

Yang perlu diketahui:

- **Snapshot ikut terkirim keluar LAN** (foto kejadian diunggah ke Telegram). Tautan
  klip hanya menunjuk aplikasi (`.../events?event=<id>`) yang bisa dibuka **dari LAN
  saja** — Telegram tidak membawa video.
- **Token disimpan di file rahasia server** `CAMERA_SECRETS_FILE` (key
  `telegram_bot_token`, izin `0600`, di luar `STORAGE_ROOT`) — bukan di DB dan tidak
  pernah tampil di UI/log/response. `TELEGRAM_BOT_TOKEN` di `.env` hanya fallback.
- **Kirim berjalan di thread terpisah** — konsumen MQTT tidak pernah menunggu
  jaringan Telegram. Rate-limit per kamera, zona, tipe, dan `track_id`: severity
  critical tanpa batas, lainnya 2 menit; absensi tercatat tanpa batas. Event tanpa
  `track_id` dikelompokkan bersama. Status alert (`queued/sent/failed/rate_limited/
  not_configured`) tampil di Inbox.
