# Spec — Migrasi Docker (deployment satu perintah)

Status: **disetujui user; implementasi tahap kode selesai dan direview (2026-10-02); Part B (server) menunggu**.
Branch: `feat/docker-deploy` (di-rebase ke `main` @ `bb2f24c`; tahap 1 sudah ter-merge).
Plan: `docs/superpowers/plans/2026-10-01-docker-deploy.md`.
Konteks: tahap 2. Tahap 1 = `2026-10-01-port-nondefault-design.md` (peta port `7700–7705`, perubahan repo saja). Spec ini melakukan **satu-satunya cutover server**.

---

## 1. Latar

Deployment sekarang manual: enam unit systemd, dua venv terpisah, binary go2rtc, Mosquitto dan Postgres di host, `bootstrap.sh` yang hanya menutupi sebagian.
Tujuan: server baru (production) cukup `git clone` lalu `./docker/setup.sh`; server dev `gspe-ai3` berpindah dari systemd ke Docker dengan peta port tahap 1.

### Kondisi (server dev diperiksa read-only 2026-10-01)

| # | Fakta | Sumber |
|---|---|---|
| 1 | Docker 29.1.2, Compose v2.39.1, runtime `nvidia` terpasang; akun `gspe-ai3` di grup `docker`. Container proyek lain sudah berjalan (OCR, `activitydb`, dll.). | server |
| 2 | Port yang dipublikasikan Docker **melewati firewall host**: dari LAN `5511 9400 8005` (container) terbuka, `3131` (proses host) tertutup. Menjalankan stack tidak butuh root; mematikan unit systemd lama butuh root (`sudo` meminta password). | probe LAN |
| 3 | 3 GPU: RTX 4090 (dipakai bersama vLLM), 2× RTX 5080 (Blackwell); driver 580.178.04, CUDA 13.0. Venv vision: Python 3.12.3, `torch 2.14`, `tensorrt_cu13 11.3`, `onnxruntime-gpu 1.24.4`, `ultralytics 8.4.146`, `insightface 2.0`, `nvidia-cudnn-cu13 9.24`. | `vision-venv` |
| 4 | Engine TensorRT (`.engine`) spesifik per arsitektur GPU; dibuat `vision/scripts/export_engine.py` di mesin target. Pin GPU dilakukan di aplikasi (UI Konfigurasi → Node, field `device`), jadi container harus melihat semua GPU. | `export_engine.py`, `nodes.py` |
| 5 | API memakai `insightface` + `onnxruntime`, terpasang manual di venv server tetapi **tidak ada di `backend/pyproject.toml`**. Enrollment di CPU terukur 200 ms (ROADMAP Fase 4); `download_face_models.py` memakai `CPUExecutionProvider`. | `backend/pyproject.toml`, ROADMAP |
| 6 | Baris node `server` dibuat API saat startup (`main.py:37`); `VISION_NODE_ID` harus sama dengan id baris itu, dan heartbeat 404 bila tidak ada. | `main.py`, `vision.env.example` |
| 7 | Data: `STORAGE_ROOT` (API, 878 MB), `VISION_DATA_DIR` (168 KB), file rahasia kamera `~/.isentinel/camera-secrets.json` (wajib di luar `STORAGE_ROOT`; juga menyimpan token Telegram), model wajah `buffalo_l` di `FACE_MODEL_DIR`. | `.env`, `config.py` |
| 8 | Ring klip memakai segmen ffmpeg per kamera di `/dev/shm/isentinel`. `/dev/shm` bawaan container hanya 64 MB. | `vision.env.example` |
| 9 | Retensi = unit oneshot harian 03:00 (`isentinel-retention.timer`), memanggil `scripts/retention_sweep.py`. | `deploy/systemd/` |
| 10 | DB dev ada di Postgres host 16.15 (employee, enrollment, zona, event); harus dipindah dengan dump/restore. Alembic terakhir `0020_health_alert`. | server |
| 11 | `live.py` membentuk URL browser (`webrtc`/`mse`/`hls`) dari `GO2RTC_URL` dengan mengganti host saja; port ikut `GO2RTC_URL`. | `live.py:28-30` |
| 12 | Frontend memanggil `/api` relatif (proxy Vite dev, `ws: true`); tidak ada build statis yang disajikan di server. | `vite.config.ts` |

## 2. Keputusan

| # | Keputusan |
|---|---|
| K1 | **Folder `docker/` di root repo** memuat semua artefak Docker. `deploy/systemd/` tetap sebagai alternatif/rollback, tidak dihapus di siklus ini. |
| K2 | **Port tetap** `7700–7704` dipublikasikan, `7705` (go2rtc RTSP) hanya internal; nomor di dalam container **sama** dengan nomor di host (fakta 11). Tidak ada variabel `PORT_*`. Port bentrok di host lain = ubah `compose.yml` dan `GO2RTC_URL` bersama. Postgres internal `postgres:5432`, tidak dipublikasikan. |
| K3 | **API tanpa GPU** (onnxruntime CPU, fakta 5). Menghindari rebutan GPU 0 dengan vLLM dan image API tetap kecil. Hanya `vision` memakai GPU. |
| K4 | **`vision` melihat semua GPU** (`count: all`); pin per node tetap lewat UI. Image berbasis CUDA 13 (Python 3.12), versi paket dikunci dari `pip freeze` venv vision dev yang teruji (fakta 3). `.engine` tidak di-bake ke image; dibuat di host lewat `docker/scripts/export-engine.sh [GPU]` ke `${DATA_DIR}/models` (`CUDA_VISIBLE_DEVICES=<GPU>` membatasi GPU yang terlihat, karena `export_engine.py` memakai `device=0` dan engine hanya valid untuk arsitektur GPU pembuatnya). |
| K5 | **Web = build statis + nginx** menggantikan Vite dev; nginx memproksi `/api` (termasuk WebSocket) ke `api:7701`. |
| K6 | **Retensi = container `retention`** (image API) menjalankan `docker/scripts/retention_loop.py` (Python, fungsi murni teruji) yang menyapu harian jam 03:00 waktu `TZ`; menggantikan timer systemd tanpa butuh host cron/root. |
| K7 | **Bind mount di `${DATA_DIR}`** (bukan named volume) agar data mudah di-backup dan dipindah; container berjalan sebagai UID/GID host sehingga file tidak jadi milik root. |
| K8 | **Satu `docker/.env`** (0600, gitignored) dihasilkan `setup.sh`; rahasia dibuat acak, tidak pernah dicetak kecuali kredensial admin sekali di akhir setup. Zero-secret: image tidak memuat rahasia. |
| K9 | **`setup.sh` idempoten** dan sekaligus jalur update (`git pull && ./docker/setup.sh`): `.env` yang ada dipertahankan, image dibangun ulang, `up -d`. |
| K10 | **Migrasi dev dua mode** (`migrate-from-host.sh --rehearse` / `--cutover`). Rehearsal berjalan paralel dengan systemd lama, `vision` **mati** (profile compose) dan `camera-secrets.json` **tidak disalin** (tidak ada alert Telegram ganda). Kamera tidak dinonaktifkan di aplikasi. |
| K11 | **Systemd tidak dipakai lagi untuk layanan I-Sentinel setelah cutover**: Docker (`docker.service`, `restart: unless-stopped`) menjalankan semuanya. Unit lama hanya `disable`, bukan dihapus, sampai Docker stabil (hapus = siklus terpisah). Mosquitto host tidak dimatikan sebelum dicek bahwa tidak ada pengguna lain di `1883`. |
| K12 | **Out of scope**: backup otomatis, bundle offline (`docker save`), registry, TLS, Jetson, Postgres terkelola. Build butuh internet saat setup. |

## 3. Desain

### 3.1 Struktur

```
docker/
├── compose.yml
├── .env.example
├── setup.sh
├── backend/{Dockerfile,Dockerfile.dockerignore,entrypoint.sh}   # API + retention (satu image)
├── vision/{Dockerfile,Dockerfile.dockerignore,requirements.lock}   # CUDA 13 + TensorRT + ffmpeg
├── web/{Dockerfile,Dockerfile.dockerignore,nginx.conf}
├── go2rtc/go2rtc.yaml.tmpl   # dirender setup.sh (sed)
├── mosquitto/mosquitto.conf
├── scripts/{export-engine.sh, migrate-from-host.sh, retention_loop.py}
└── tests/                    # pytest: compose, setup --env-only, retention, migrate --dry-run, nginx
```
Konteks build semua image = root repo (`context: ..`); berkas abaikan per-Dockerfile (`Dockerfile.dockerignore`, BuildKit) agar semuanya tetap di dalam `docker/`.
`docker/.env` dan `${DATA_DIR}` masuk `.gitignore`.

### 3.2 Layanan compose (`name: isentinel`)

| Layanan | Image | Publish | Catatan |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | — | **named volume** `pgdata` (pengecualian K7: image postgres tidak andal dijalankan sebagai UID host arbitrer); healthcheck `pg_isready` |
| `mosquitto` | `eclipse-mosquitto:2` | `7704` | `allow_anonymous false`, `password_file` dibuat `setup.sh` (satu pengguna `MQTT_USERNAME` dipakai API dan vision); berjalan sebagai UID host; persistence di `${DATA_DIR}/mosquitto/data` |
| `go2rtc` | `alexxit/go2rtc` (tag dikunci) | `7702`, `7703/tcp+udp` | `api.listen :7702`, `webrtc.listen :7703` + `candidates: ["${GO2RTC_PUBLIC_HOST}:7703"]`, `rtsp.listen :7705` (tidak dipublikasikan); stream kamera ditambahkan API saat runtime dan go2rtc **menulisnya ke yaml** (berisi kredensial RTSP kamera, lihat komentar `go2rtc.example.yaml`), jadi `${DATA_DIR}/go2rtc/go2rtc.yaml` di-mount rw ke `/config`, bermode 0600, di luar repo, dirender `setup.sh` hanya bila belum ada |
| `api` | build `docker/backend` | `7701` | entrypoint `alembic upgrade head` lalu `uvicorn`; healthcheck `/api/v1/health`; `depends_on` postgres, mosquitto, go2rtc (healthy) |
| `vision` | build `docker/vision` | — | profile `vision`; `deploy.resources.reservations.devices` nvidia `count: all`; `shm_size` dari `VISION_SHM_SIZE` (fakta 8); `VISION_API_URL=http://api:7701`, `VISION_MQTT_URL=mosquitto:7704`, `VISION_GO2RTC_URL=http://go2rtc:7702` (default kode `1984`; dipakai `recorder._save_clip`, temuan review tahap 1), `VISION_API_KEY=${NODE_API_KEY}`; model wajah dibaca read-only dari `${DATA_DIR}/api/faces_models`; `depends_on` api healthy |
| `web` | build `docker/web` | `7700` | multi-stage: `npm ci && npm run build` → nginx; SPA fallback `try_files`; `/api/` ke `api:7701` dengan header `Upgrade` dan `proxy_read_timeout` panjang; `client_max_body_size` cukup untuk foto enrollment dan impor CSV |
| `retention` | image `api` | — | `retention_loop.py` (di-mount ro): tidur sampai 03:00 `TZ`, jalankan `scripts/retention_sweep.py`, ulang |

Semua URL layanan di compose menyebut **port eksplisit** (`MQTT_URL=mosquitto:7704`, `GO2RTC_URL=http://go2rtc:7702`, `GO2RTC_RTSP_URL=rtsp://go2rtc:7705`, `VISION_*` di atas): `config_push.py:128`, `events_consumer.py:167`, dan `vision/transport/mqtt.py:35` jatuh ke `1883` bila URL tanpa port.
RTSP `7705` tidak dipublikasikan tetapi harus terjangkau dari container `vision` lewat jaringan compose, jadi `rtsp.listen` di `go2rtc.yaml` untuk Docker adalah `:7705` (bukan `127.0.0.1:7705` seperti template systemd).

Semua layanan: `restart: unless-stopped`, `TZ=${TZ}` (default dari host, fallback `Asia/Jakarta`), logging `json-file` `max-size 10m` `max-file 5` (pengganti journald, mencegah disk penuh).

### 3.3 Image

- **backend**: `python:3.12-slim`; `pip install` dari `backend/` + extra baru `face` di `backend/pyproject.toml` (`insightface`, `onnxruntime` CPU); alat build hanya bila wheel `insightface` tidak tersedia; non-root.
- **vision**: `nvidia/cuda:13.0.3-base-ubuntu24.04` (library CUDA/cuDNN/TensorRT datang dari wheel pip yang dikunci, bukan dari image) + Python 3.12; paket dikunci dari `pip freeze` venv vision dev (`docker/vision/requirements.lock`); `ffmpeg`, `libgl1`, `libglib2.0-0`; memuat `vision/scripts/export_engine.py`.
- **web**: `node:22` build → `nginx:alpine`. Tahap build memakai `npm ci` **termasuk devDependencies** dan tidak men-set `NODE_ENV=production` sebelum `npm run build` (vite dan tsc ada di devDependencies; `NODE_ENV=production` juga merusak suite frontend: React ter-resolve ke build production tanpa `act`, tercatat di review tahap 1).

### 3.4 Data dan rahasia

`${DATA_DIR}` (default `<repo>/../I-Sentinel-docker-data`): `api` (`STORAGE_ROOT=/data/api`, `FACE_MODEL_DIR=/data/api/faces_models`), `vision` (`VISION_DATA_DIR=/data/vision`), `models` (dipasang `/models` di `vision`: `yolo26s.pt` dan `yolo26s.engine`, `VISION_DETECTOR_MODEL=/models/yolo26s.engine`; sesuai tata letak server dev), `go2rtc`, `mosquitto` (`passwd`, `data/`), `secrets` (dipasang `/secrets`, `CAMERA_SECRETS_FILE=/secrets/camera-secrets.json`, di luar `STORAGE_ROOT`). Kode membaca kredensial kamera default dan profil `env:` dari environment (`CAM_USERNAME`, `CAM_PASSWORD`, `CAMERA_CREDENTIAL_*`; `probe.py`, `stream_endpoint._secret`), jadi `api` memuat `${DATA_DIR}/secrets/camera.env` lewat `env_file` opsional; `setup.sh` membuatnya kosong (0600) dan `migrate-from-host.sh` mengisinya dari `.env` host pada rehearsal maupun cutover (temuan review).
`NODE_API_KEY`, `JWT_SECRET`, password DB/MQTT/admin dibuat `setup.sh` (`openssl rand`). `COOKIE_SECURE=false` (LAN HTTP). Bobot YOLO `yolo26s.pt` diunduh ultralytics saat ekspor engine; bila host offline, file diletakkan manual di `${DATA_DIR}/models` (dicetak `setup.sh`).

### 3.5 `setup.sh`

1. Prasyarat: `docker`, `docker compose`, runtime `nvidia` (peringatan jika tidak ada: stack tetap naik tanpa `vision`), akun boleh menjalankan docker.
2. Deteksi IP LAN (→ `GO2RTC_PUBLIC_HOST`, bisa dioverride), `TZ`, `DATA_DIR`, UID/GID.
3. Buat `docker/.env` bila belum ada (rahasia acak, `COMPOSE_PROFILES=vision`; `--rehearse` mengosongkannya); render `go2rtc.yaml`, buat `password_file` Mosquitto.
4. `docker compose build`; `up -d postgres mosquitto go2rtc api`; tunggu `api` healthy (batas ±60 detik; restart/shutdown API bisa 10–40 detik).
5. Baca id baris node `server` dari DB, tulis `VISION_NODE_ID` ke `.env`; unduh model wajah ke `faces_models` bila kosong.
6. `export-engine.sh` bila `vision` aktif dan `.engine` belum ada; `up -d` sisanya.
7. Cetak URL (`http://<ip>:7700`), username dan password admin (sekali), peta port, dan langkah berikut (pendaftaran kamera lewat UI).

### 3.6 Migrasi data dev (`migrate-from-host.sh`)

`--rehearse` (paralel dengan systemd lama, tanpa gangguan produksi):
`DATA_DIR` terpisah dari data lama; `pg_dump` DB host → restore ke container `postgres`; salin `I-Sentinel-data/{api,vision}`; `camera-secrets.json` **tidak** disalin; `vision` mati. Uji: UI `:7700`, login, daftar kamera/zona/employee, event lama termuat beserta klip, Live Wall (WebRTC/MSE) dan snapshot dari klien LAN, dashboard/monitoring (metrik host dibaca dari dalam container; bandingkan dengan sistem lama), enrollment foto, `retention` tidak menghapus apa pun di salinan.

`--cutover` (jam sepi, bukan menjelang pergantian shift; deteksi mati ±5–10 menit):
1. Pengguna menjalankan **satu perintah root** menonaktifkan unit lama: `isentinel-api`, `isentinel-web`, `vision-node`, `go2rtc`, `isentinel-retention.timer` (Mosquitto host dicek dulu: `ss -tn state established '( sport = :1883 )'`; bila ada pengguna lain, dibiarkan).
2. Skrip: `pg_dump` final → hapus dan buat ulang DB container → restore; sinkron ulang `api`/`vision`; salin `camera-secrets.json`; `COMPOSE_PROFILES=vision`; `up -d`; verifikasi 3.9.
3. Rehearsal terakhir dibuang: `DATA_DIR` rehearsal diganti hasil sinkron final.

### 3.7 Systemd setelah cutover

Layanan I-Sentinel dikelola Docker. Unit lama `disabled` (tersedia untuk rollback), file di `deploy/systemd/` dan `bootstrap.sh` ditandai legacy di dokumen. Production baru: tanpa unit aplikasi. `docker.service` harus `enabled` (dicek `setup.sh`).

### 3.8 Rollback

Sebelum data baru ditulis penting: `docker compose down`, `systemctl enable --now` unit lama (root), `app_url` Telegram kembali bila sudah diubah. Sesudah Docker berjalan lama dan data baru terkumpul, rollback butuh dump balik (`pg_dump` container → host): prosedur ada di runbook; karena itu unit lama dibiarkan sampai Docker dinyatakan stabil.
`app_url` Telegram diubah ke `http://<ip>:7700` lewat UI saat cutover; link `:5173` lama di pesan terkirim tidak akan terbuka (diterima).

### 3.9 Pengujian dan verifikasi

Bukan unit test baru (infrastruktur); bukti nyata ditempel di `CHANGELOG.md`/`ROADMAP.md`:
- Statis: `docker compose config` valid; `shellcheck` untuk `setup.sh` dan skrip; `hadolint` bila tersedia.
- Instalasi bersih: `./docker/setup.sh` pada direktori kosong → login admin berhasil, `curl :7701/api/v1/health` → `{"status":"ok"}`, `ss -ltn` menampilkan `7700–7704` (bukan `7705`), Postgres tidak terbuka di host; jalankan ulang `setup.sh` (idempoten, `.env` tidak berubah).
- Dari klien LAN: UI `:7700`, Live Wall WebRTC/MSE, snapshot, MQTT `:7704` menolak tanpa kredensial.
- Vision (setelah engine dibuat): node `online` di UI, satu event uji tercatat end to end (klip + snapshot terputar), deteksi memakai GPU yang dipin, `nvidia-smi` menunjukkan proses di container.
- Migrasi: jumlah baris tabel utama (employee, camera, zone, event) sama antara DB lama dan baru; `alembic current` = `0020_health_alert` (atau head terbaru); checksum klip contoh sama.
- Reboot host: seluruh container naik sendiri tanpa tindakan manual.
- Port lama (`5173 8000 1984 8554 1883`) tidak lagi mendengarkan setelah unit lama dinonaktifkan.

### 3.10 Dokumen dan repo

Diperbarui bersama kodenya: `README.md` (quick start Docker), `ARCHITECTURE.md` (topologi container), `docs/RUNBOOK.md` (perintah `docker compose`, log, restart, rollback, dump balik), `docs/DEVELOPMENT.md`, `ROADMAP.md`, `CHANGELOG.md` (konteks, file, bukti, dampak, rollback), `.gitignore` (`docker/.env`, `${DATA_DIR}`, `go2rtc.yaml` hasil render).

## 4. Di luar cakupan

Lihat K12. Tambahan: penghapusan unit systemd lama dan `bootstrap.sh`, pengetatan `api.origin` go2rtc, deployment Jetson/edge, pemantauan Prometheus/OTel container, CI untuk image.

## 5. Risiko

| Risiko | Mitigasi |
|---|---|
| Deteksi dan absensi mati selama cutover; event pada jendela itu tidak terekam (store-and-forward hanya menahan event dari node yang berjalan) | Jam sepi; durasi diukur dan dicatat; jendela diumumkan ke pengguna |
| `/dev/shm` container terlalu kecil → ring klip gagal pada puluhan kamera | `shm_size` dari `VISION_SHM_SIZE`, default dihitung dari jumlah kamera (ukuran akhir ditetapkan di plan setelah mengukur ring nyata) |
| Blackwell (RTX 5080) butuh CUDA/TensorRT 13: image salah versi → engine gagal dibuat | Versi dikunci dari venv yang sudah teruji; `export-engine.sh` diuji pada GPU 4090 dan 5080 sebelum cutover |
| `insightface` CPU lebih lambat dari GPU lama di API | Terukur 200 ms; latensi enrollment diperiksa saat rehearsal; bila tak diterima, ubah K3 (GPU untuk API) |
| Port Docker melewati firewall → `7701`, `7702`, `7704` terbuka ke seluruh LAN | Sesuai paparan LAN yang sudah diterima; MQTT dengan kredensial, API dengan auth, go2rtc `7702` tanpa auth (sama seperti `1984` sekarang), Postgres dan RTSP tidak dipublikasikan |
| Alert Telegram ganda saat rehearsal | `camera-secrets.json` tidak disalin, `vision` mati |
| Metrik host (CPU/RAM/disk) di dashboard salah dibaca dari dalam container | Diperiksa saat rehearsal (3.6); `/proc` memperlihatkan host, disk dari bind mount |
| Konflik port dengan proyek lain di host production | Blok `7700–7705` diperiksa kosong di setiap host sebelum setup; `setup.sh` menolak jalan bila port terpakai |
| `VISION_NODE_ID` salah → heartbeat 404 | Diambil dari DB oleh `setup.sh` (fakta 6) |
| Bobot YOLO tak bisa diunduh di jaringan tertutup | `setup.sh` mencetak instruksi penempatan manual |
| Image di-build per host, versi dependensi bisa bergeser | `requirements.lock` untuk vision, versi minor base image dikunci |

## 6. Eksekusi

Plan ditulis setelah spec disetujui (skill `writing-plans`), memerinci urutan: image (backend, web, vision) → compose → `setup.sh` → skrip migrasi → uji instalasi bersih → rehearsal dev → cutover.
Sesi eksekusi berhenti di `git push`; instalasi, rehearsal, cutover, dan merge dilakukan di sesi perencanaan dengan OK eksplisit pengguna untuk tiap perubahan di server.
