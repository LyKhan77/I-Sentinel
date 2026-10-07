# RUNBOOK — Operasional I-Sentinel di gspe-ai3

**Sejak 2026-10-02 13:36 WIB `gspe-ai3` berjalan di Docker**; operasi harian ada di bagian "Docker" di akhir.
Bagian bernomor di bawah (systemd) adalah prosedur **legacy**: unit lama dinonaktifkan (bukan dihapus) dan hanya untuk rollback.
Host: `gspe-ai3` (LAN `192.168.2.133`). Clone Docker `/home/gspe-ai3/project_cv/I-Sentinel-docker`, data
`/home/gspe-ai3/project_cv/I-Sentinel-docker-data`. Pohon systemd lama `/home/gspe-ai3/project_cv/I-Sentinel` dan data lama
`I-Sentinel-data` kini cadangan beku.

## 1. Service & restart

| Unit | Fungsi |
|---|---|
| `isentinel-api.service` | FastAPI backend, port 8000 |
| `vision-node.service` | Vision node (MQTT → event) |
| `isentinel-web.service` | Frontend dev server, port 5173 |
| `go2rtc` | RTSP bridge/snapshot, port 1984 (API) + 8554 (RTSP) |
| `isentinel-retention.timer` | Sweep retensi harian 03:00 |

**Peta port** (referensi repo & instalasi baru; blok `7700–7705`):

| Port | Fungsi | Akses |
|---|---|---|
| 7700 | Web UI (Vite dev) | LAN |
| 7701 | API FastAPI | LAN |
| 7702 | go2rtc API (WS/MSE/HLS/snapshot) | LAN |
| 7703 | go2rtc WebRTC (tcp+udp) | LAN |
| 7704 | MQTT Mosquitto | LAN (node edge Fase E) |
| 7705 | go2rtc RTSP | `127.0.0.1` saja |

> **Status server dev:** sejak cutover 2026-10-02 `gspe-ai3` memakai blok `7700–7705` lewat Docker. Perintah systemd dan port lama di
> bagian bernomor hanya berlaku untuk rollback. Port yang dipublikasikan Docker melewati firewall host; instalasi baru tanpa Docker
> membuka `7700:7704/tcp` + `7703/udp` (`7705` tidak dibuka).

Restart tanpa sudo (unit memakai `Restart=always`, jadi kill cgroup = restart):

```bash
ssh gspe-ai3
kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs)
kill $(cat /sys/fs/cgroup/system.slice/vision-node.service/cgroup.procs)
kill $(cat /sys/fs/cgroup/system.slice/isentinel-web.service/cgroup.procs)
```

Verifikasi:

```bash
systemctl is-active isentinel-api vision-node isentinel-web go2rtc
curl -s localhost:8000/api/v1/health          # {"status":"ok"}
journalctl -u isentinel-api -n 50 --no-pager
```

Update versi di server:

```bash
ssh gspe-ai3 "cd /home/gspe-ai3/project_cv/I-Sentinel && git pull"
# bila ada migration baru:
ssh gspe-ai3 "export \$(tr '\0' '\n' < /proc/\$(systemctl show isentinel-api -p MainPID --value)/environ | grep '^DATABASE_URL=' | head -1) && cd /home/gspe-ai3/project_cv/I-Sentinel/backend && /home/gspe-ai3/isentinel-venv/bin/alembic upgrade head"
```

## 2. Backup

```bash
# DB (redact: jangan salin URL ke log/git)
ssh gspe-ai3 "export \$(tr '\0' '\n' < /proc/\$(systemctl show isentinel-api -p MainPID --value)/environ | grep '^DATABASE_URL=' | head -1) && pg_dump \"\$DATABASE_URL\" > ~/backup/isentinel-\$(date +%F).sql"
# .env — salin manual, mode 600
ssh gspe-ai3 "ls -l /home/gspe-ai3/project_cv/I-Sentinel/.env"   # pastikan 600
```

Restore: `psql "$DATABASE_URL" < file.sql` + `alembic downgrade` bila DB lebih baru dari kode.

## 3. Tambah kamera

UI: **Konfigurasi → Kamera → Tambah** — isi Nama/Lokasi/IP → **Deteksi otomatis**
(scan channel NVR) → pilih stream MAIN/SUB → simpan.

- `go2rtc.yaml` ditulis otomatis (stream `cam_<id>` via API go2rtc).
- Node membaca kamera setelah config push MQTT (otomatis, tanpa restart service manual).
  Hanya kamera yang berubah yang dimulai ulang (detect + face + recorder); kamera lain tetap berjalan.
  Stream kamera itu tersambung ulang sekitar 20–30 detik; setelan global mengulang semua kamera.
  Config identik tidak memulai ulang worker. Perkiraan durasi ini belum diukur untuk kode lokal baru.
- Deteksi baru berjalan setelah ada zona aktif: zona behavior dan absensi dibuat di tab **Zona Deteksi** (tab Gate Absensi sudah tidak ada).
- Kamera yang baru ditambahkan di instalasi Docker memakai kredensial dari **Kelola kredensial** (UI) atau `<DATA_DIR>/secrets/camera.env`.

## 4. GPU detektor (pin/unpin)

UI: **Konfigurasi → Node** → pilih `cuda:N` (dropdown dari heartbeat hw) →
Simpan → node hot-reload tanpa restart service manual, tetapi perubahan device detector
memulai ulang **semua kamera**, sebagaimana perubahan model/nms/conf/imgsz dan device face.
Badge Dashboard berubah `Detektor: PIN cuda:N`.
Perubahan `FaceSettings` hanya memulai ulang kamera dengan worker face.
Config pertama dan galat diff juga memakai restart penuh. Antrean snapshot digabung ke yang terakhir.
Pantau log `config applied: restarted [..], added [..], removed [..], unchanged N` pada jalur diff,
atau `started N worker(s) for M camera(s)` pada jalur penuh.

Status perubahan per kamera: BELUM diuji di server nyata. Verifikasi setelah rebuild `vision`:
edit zona satu kamera, lalu pastikan kamera lain tetap `streaming`, `frames` tidak mereset,
dan `reconnects_1h` tidak naik. Tidak ada migrasi atau perubahan backend.

Fallback env (bootstrap): `VISION_DETECTOR_DEVICE=cuda:1` di `vision.env`,
lalu restart vision-node. Prioritas: **DB (UI) > env > auto**.

Gagal pin (`cuda:N` > jumlah GPU): start → exit fail-fast; config push →
ditolak (node tetap hidup, device lama).

## 5. Troubleshooting

> Tabel gejala di bawah ditulis untuk sistem lama (systemd). Di Docker gunakan
> `docker compose -f docker/compose.yml ps|logs --tail 100 <layanan>` (api, vision, go2rtc, mosquitto, postgres, web, retention).

| Gejala | Cek |
|---|---|
| Live view 502/gambar hitam | `systemctl is-active go2rtc`; `curl -o /dev/null -w '%{http_code}' 'http://127.0.0.1:1984/api/frame.jpeg?src=cam_<id>'` |
| Node offline di Dashboard | heartbeat: `select status from node`; LWT di log MQTT; vision `journalctl -u vision-node` |
| Kamera worker mati (RTSP 404) | cek stream di `http://<host>:1984` WebUI; kredensial NVR di `.env` (references) |
| Vision node exit segera saat start | log `detector device pin invalid` — pin > jumlah GPU; koreksi di UI Node |
| Retensi tidak jalan | `systemctl list-timers isentinel-retention.timer`; manual: `cd backend && python scripts/retention_sweep.py` |
| API 500 setelah deploy | alembic belum upgrade: jalankan per §1; cek `journalctl -u isentinel-api` |

## 5b. Alert & Telegram

- Telegram belum dikonfigurasi → alert **tetap tercatat di DB**, hanya
  pengiriman yang dilewati (status `not_configured` di log). Verifikasi:
  `curl -H 'Authorization: Bearer <token>' localhost:8000/api/v1/alerts`.
- Konfigurasi Telegram: env `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` di `.env`,
  restart API. Rate limit alert: `ALERT_MIN_SEVERITY`, `TELEGRAM_RATE_LIMIT`.
- Caption AI pada alert (edit `editMessageCaption`) butuh `app_url` benar
  (Konfigurasi → Notifikasi → port web `7700`) agar tautan klip pada caption
  yang diedit menunjuk aplikasi; alert lama tanpa `message_id` tidak pernah diedit.

## 5c. Rotasi JWT secret

```bash
# 1. set JWT_SECRET baru di .env (nilai baru, acak, 32+ byte)
# 2. restart isentinel-api (kill-cgroup per §1)
```

Efek: **semua sesi login mati seketika** (token lama tak valid) — user login ulang.
Tidak memengaruhi data event/alert/absensi.

## 5d. Retensi

- Jadwal: `isentinel-retention.timer`, harian 03:00 (`Persistent=true`).
- Manual: `cd /home/gspe-ai3/project_cv/I-Sentinel/backend && \
  /home/gspe-ai3/isentinel-venv/bin/python scripts/retention_sweep.py`.
- Scope: clip/crop/snapshot/faces melebihi `RETENTION_DAYS`; DB baris tidak
  dihapus (media path dibiarkan — kosong di disk). Hasil sweep terlihat di
  `journalctl -u isentinel-retention.service`.

## 6. Load test / soak

```bash
cd /home/gspe-ai3/project_cv/I-Sentinel
export ISENTINEL_PASS='<password-admin>'   # zero-secret: dari .env, jangan masukkan log
./deploy/loadtest/make-streams.sh start 32    # 32 stream ffmpeg file (sample 2 jam)
python3 deploy/loadtest/register-cams.py add 32
SOAK_PIN=cuda:1 SOAK_OUT=~/isentinel-data/loadtest/soak.csv ./deploy/loadtest/soak.sh 120 32
./deploy/loadtest/soak-churn.sh 5 300         # churn paralel (terminal lain)
./deploy/loadtest/register-cams.py remove && ./deploy/loadtest/make-streams.sh stop 2000
```

## 7. Batasan yang diketahui

- **sudo tanpa password terbatas** — pemasangan unit baru / upgrade paket perlu user.
- **Hot-reload device GPU**: inferensia pindah seketika; CUDA context lama di
  GPU sebelumnya lepas hanya saat proses vision-node direstart.
- **isentinel-recorder.service**: stub (tidak ter-install) — recorder blob
  berjalan di dalam vision node.
- **Disk 85%** — retensi `RETENTION_DAYS` memotong clip/crop/snapshot, bukan
  log/DB; pantau `df -h`.

## Docker — operasi di `gspe-ai3` (aktif sejak 2026-10-02)

Cutover dilakukan 2026-10-02: unit systemd lama dinonaktifkan sebelum 13:36, stack Docker naik 13:36:22, gap deteksi ±77 dtk (heartbeat
lama terakhir 13:35:25, baru 13:36:42); 25 tabel DB cocok dengan DB host yang dibekukan; bukti di `CHANGELOG.md`. Cadangan DB terakhir sistem
lama: `/home/gspe-ai3/project_cv/I-Sentinel-data/backups/isentinel-pre-docker-20261002-133603.sql` (mode 600). Data lama (Postgres host,
`I-Sentinel-data`) kini **beku**: jangan menyalakan sistem lama tanpa sinkron balik. Prosedur "Rehearsal dan cutover" di bawah sudah
dijalankan; dipertahankan sebagai referensi untuk instalasi atau migrasi berikutnya.

### Catatan dari rehearsal di `gspe-ai3` (2026-10-02)

- `VISION_NODE_ID` adalah **nama** node (`server`), bukan id numerik: MQTT memakai `isentinel/nodes/<name>/heartbeat` dan
  `isentinel/config/<name>`. Gejala nama salah: container hidup tapi idle, log API `heartbeat for unknown node`.
- Node tanpa zona aktif tidak membuat pekerja (`started 0 worker(s) for N camera(s)`) dan tidak memakai GPU. Itu normal; di server dev
  semua zona memang `active=false` sejak 1 Okt. Container tanpa kamera statis butuh `VISION_AWAIT_CONFIG=true` (sudah di compose).
- `onnxruntime-gpu` dari PyPI adalah build CUDA 12: image membawa library CUDA 12.8 lewat apt dan lock dipasang `--no-deps`. Bila
  log vision memuat `CUDAExecutionProvider is not in available provider names` atau CPU container melonjak, face embedder jatuh ke CPU.
- Memindah pin GPU detektor di UI berlaku tanpa restart vision (config push), tetapi meninggalkan konteks CUDA ~386 MiB di GPU 0.
  Satu berkas `yolo26s.engine` hanya valid untuk jenis GPU pembuatnya (5080 <-> 5080 aman, ke 4090 tidak).
- Ring klip memakai ~1 MB per kamera pada stream uji; `VISION_SHM_SIZE=2gb` memadai untuk puluhan kamera.

### Retensi (container `retention`)

Sweep berjalan sekali sehari pukul 03:00 waktu `TZ`. Berbeda dari timer systemd lama
(`Persistent=true`), container yang restart **setelah** 03:00 melewatkan sweep hari itu
dan baru berjalan besok. Jalankan manual bila perlu:
`docker compose -f docker/compose.yml run --rm -T retention python scripts/retention_sweep.py`.

### Operasi setelah instalasi Docker

Dari root checkout Docker (di server dev: `/home/gspe-ai3/project_cv/I-Sentinel-docker`):

```bash
docker compose -f docker/compose.yml --env-file docker/.env ps
docker compose -f docker/compose.yml --env-file docker/.env logs --tail 100 api
docker compose -f docker/compose.yml --env-file docker/.env restart api
git pull && ./docker/setup.sh
curl -s localhost:7701/api/v1/health
```

Jangan menyalin keluaran `compose config` tanpa `-q` ke log publik karena env
resolved memuat rahasia. Jangan mengubah password DB di `.env` tanpa rotasi DB.
Setup menjaga `.env`, passwd MQTT, dan YAML go2rtc existing. Pada API recreation,
nginx meresolve upstream melalui DNS Docker (proxy variabel tanpa URI).

Ekspor engine di GPU target:

```bash
./docker/scripts/export-engine.sh --dry-run 1
./docker/scripts/export-engine.sh 1
```

`CUDA_VISIBLE_DEVICES` membatasi GPU yang dilihat exporter (`device=0`).
Hasil di `${DATA_DIR}/models/yolo26s.engine` hanya valid untuk arsitektur GPU
pembuatnya. Cadangkan engine sebelum ekspor ulang; jangan membangun image vision
atau engine di Mac arm64. Ukur shm ring klip untuk menentukan VISION_SHM_SIZE final.

### Caption AI dan Tanya AI — rollout terpisah

MVP sudah diuji di `gspe-ai3` dengan LLM nyata (2026-10-06; lihat `CHANGELOG.md`). Prosedur ini
untuk deploy ke server lain atau ulang, bukan bukti bahwa layanan aktif di lingkungan Anda.

1. Konfirmasikan kepada pemilik endpoint bahwa snapshot/keyframe tidak disimpan atau dipakai
   melatih model. Gambar dapat memuat wajah karyawan. Backup DB dan secrets sebelum migrasi.
2. Deploy kode yang disetujui memakai `./docker/setup.sh`: image `api` harus dibangun ulang
   untuk `ffmpeg`, image `web` untuk panel, dan entrypoint API menjalankan migrasi `0021` dan `0022` (kolom `alert.message_id`/`message_photo`/`ai_synced`
   untuk edit caption Telegram; aditif, alert lama tetap NULL dan tidak pernah diedit).
   `setup.sh` membuat `${DATA_DIR}/secrets/llm.env` berupa komentar (0600) tanpa menimpa file lama.
3. Admin membuka **Konfigurasi → AI Integration** untuk URL API (base `/v1`), model, kunci,
   aktif/nonaktif, dan parameter lanjutan. Kunci tulis-saja disimpan di `secret_store` (0600 di luar
   `storage_root`), bukan DB/respons. Tombol **Tes koneksi** memakai form tanpa menyimpan
   (teks + JPEG sintetis 64×64; timeout 30 detik per panggilan); konfirmasikan teks/vision/latensi.
   Simpan hanya field berubah. Viewer tidak melihat tab dan ketiga endpoint memberi 403.
   Pengaturan UI ini sudah diuji di `gspe-ai3` (tes koneksi teks + vision OK).
4. `llm.env` tetap nilai awal/fallback, bukan satu-satunya cara konfigurasi. Prioritas **DB > env > default**.
   `setting.llm` kosong mempertahankan perilaku sebelumnya. **Reset ke env**: kosongkan field atau
   pilih reset lalu Simpan. Hapus kunci hanya menghapus secret_store; `LLM_API_KEY` env tetap berlaku.
   `LLM_CONCURRENCY`/`AI_QUEUE_MAX` hanya env, ditampilkan hanya-baca. Default concurrency 2,
   antrean 100, throttle caption 60 detik/zona, kuota ask 6/menit/user, timeout caption/ask 60/120
   detik, max tokens 1000; `LLM_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":false}}`.
   Jangan mencetak env, resolved compose config, atau kunci. Bila mengubah env (termasuk batas
   restart-only), muat ulang dengan **recreate**, bukan restart biasa:

   ```bash
   docker compose -f docker/compose.yml --env-file docker/.env up -d --no-deps --force-recreate api
   ```

   `docker compose restart api` tidak membaca ulang `env_file`; override DB tetap menang setelah recreate.
   Tetap satu proses API: singleton settings, semaphore/rate limit/throttle lokal proses.
   Tahap AI Integration memerlukan rebuild `api` dan `web`, tanpa migrasi tambahan di atas fitur induk.
5. Dengan izin pemilik, tes koneksi UI dan tes kontrak marker `llm` dapat dicoba pada endpoint nyata.
   Verifikasi `/api/v1/ai/status` sesudah login, tanpa URL/model/kunci dalam respons status.
6. Aktifkan **Caption AI otomatis** pada satu zona non-attendance dengan snapshot aktif,
   pilih Bawaan/Kustom, picu event nyata. Verifikasi caption pending → ok, Tanya AI dengan
   preset/teks, cache, jumlah frame, dan fallback klip. Alert Telegram tetap terkirim tanpa menunggu
   LLM; begitu caption `ok`, pesan `sent` ber-foto diedit sekali dengan baris `🤖 AI:` (tanpa
   notifikasi baru). Hasil AI tidak mengubah severity atau menekan alert. Pastikan **Konfigurasi →
   Notifikasi → app_url** menunjuk alamat LAN web (mis. `http://192.168.2.133:7700`) agar tautan caption
   benar. Real user melakukan penerimaan UI dan memeriksa pesan di grup Telegram.

**Rollback fitur aman:** admin menonaktifkan AI di tab AI Integration lalu Simpan; override DB
mengalahkan `LLM_ENABLED` env. Tidak ada panggilan caption/ask baru, panel tersembunyi, ask 503
`disabled`; zona/prompt dan audit tetap di DB. Toggle zona off hanya menghentikan caption otomatis,
bukan Tanya AI global. Bila memakai env untuk mematikan fitur, reset override `enabled` terlebih
dulu lalu set `LLM_ENABLED=false` dan recreate API. Tes koneksi admin tetap aksi eksplisit.

**Rollback pengaturan UI:** revert commit tahap AI Integration lalu rebuild `api` dan `web`.
Kode lama kembali membaca `llm.env`; baris `setting.llm` tidak dipakai dan audit AI tidak dihapus.
Cadangkan secrets terlebih dahulu. Bila kunci baru hanya ada di secret_store, atur fallback env secara
privat sebelum rollback; kode lama belum membaca kunci LLM dari secret_store.

**Rollback skema (destruktif):** `alembic downgrade 0020` menghapus seluruh `event_ai` dan kolom
prompt/toggle zona. Jangan menjalankannya pada API baru yang masih aktif: backup dulu, hentikan
writer API/retention dalam maintenance, jalankan downgrade lewat image yang masih mempunyai migrasi
0021, lalu jalankan kode lama yang cocok. Downgrade tidak dapat memulihkan jawaban yang dihapus.
Tidak perlu downgrade hanya untuk mematikan fitur.

**Rollback caption Telegram:** `git revert -m 1 97dcd9b` (kolom aditif aman) atau
`alembic downgrade 0021`, yang hanya menghapus `alert.message_id`/`message_photo`/`ai_synced`; riwayat
alert tidak hilang, pesan yang sudah diedit tetap seperti adanya di Telegram. Mematikan AI (tab AI
Integration) otomatis menghentikan edit baru karena tidak ada caption `ok` baru.

Gejala caption Telegram: baris `🤖 AI:` tidak muncul → periksa alert `sent` dengan `message_id` dan
`message_photo=true` (alert lama/teks-saja tidak diedit), caption event `ok`, chat aktif masih sama dengan
`alert.chat_id`, token terpasang, dan `ai_synced` (true setelah edit sukses; edit gagal melepas klaim,
log api mencatat nama tipe galat tanpa token).

Gejala: caption tidak muncul → periksa enabled, toggle zona, snapshot, throttle, status failed.
Ask 409 `clip_unavailable` → preset temporal memerlukan klip; kegagalan ekstraksi pada pertanyaan biasa
memberi `frames_used=0`. 429 → tunggu kuota; 503 `busy` → slot penuh; 502 → endpoint/timeout.
Riwayat `event_ai` hilang saat retensi menghapus event; pencarian permanen dan Telegram Tanya AI belum tersedia.

### Rehearsal dan cutover (memerlukan persetujuan operator)

1. Siapkan clone terpisah dan DATA_DIR terpisah dari
   `/home/gspe-ai3/project_cv/I-Sentinel-data`. Build tiga image di server;
   verifikasi tag go2rtc/mosquitto, wheel CUDA, import API, dan `nginx -t`.
2. Jalankan `DATA_DIR=/home/gspe-ai3/project_cv/I-Sentinel-docker-data ./docker/setup.sh --rehearse`.
   Vision mati. Jangan menyalin `camera-secrets.json` (berisi token Telegram) ke target rehearsal.
   Kredensial kamera dari `.env` host (`CAM_USERNAME`, `CAM_PASSWORD`, `CAMERA_CREDENTIAL_*`)
   disalin `migrate-from-host.sh` ke `${DATA_DIR}/secrets/camera.env` (0600, hanya dibaca API;
   nilai tidak dicetak), supaya stream dan Live View bisa diuji tanpa alert ganda.
3. Periksa rencana, lalu jalankan migrasi rehearsal hanya setelah disetujui:

   ```bash
   ./docker/scripts/migrate-from-host.sh --rehearse --dry-run
   ./docker/scripts/migrate-from-host.sh --rehearse
   ```

   Override sumber dengan HOST_ENV_FILE, HOST_DATA_ROOT, HOST_SECRETS_FILE,
   HOST_ENGINE bila berbeda; jangan cetak DATABASE_URL. Rehearsal menyalin API,
   bukan data vision (detail Task 6); data vision disinkron saat cutover.
   Skrip menghentikan container api/retention/vision sebelum dump, mengganti
   **DB container**, restore dengan ON_ERROR_STOP, rsync data, memperbarui nama node (`VISION_NODE_ID`),
   lalu menghidupkan stack tanpa vision. DB host tidak diubah. Periksa jumlah
   employee/camera/zone/event, Alembic head, checksum klip, login, live dari LAN,
   snapshot, enrollment CPU, metrik host, serta retensi pada salinan.
4. Jadwalkan cutover pada jam sepi, bukan menjelang pergantian shift. Backup
   kedua sisi. Pengguna menjalankan satu perintah root untuk disable layanan lama:

   ```bash
   sudo systemctl disable --now isentinel-api isentinel-web vision-node go2rtc isentinel-retention.timer
   ```

   Periksa `ss -tn state established '( sport = :1883 )'` sebelum memutuskan
   Mosquitto host: jangan hentikan bila ada pengguna lain. Skrip tidak mematikan
   Mosquitto host atau unit systemd apa pun.
5. Setelah persetujuan eksplisit:

   ```bash
   ./docker/scripts/migrate-from-host.sh --cutover --dry-run
   ./docker/scripts/migrate-from-host.sh --cutover
   ```

   Cutover melakukan dump final, DROP/CREATE DB container, rsync `--delete` API
   dan vision, copy secrets `0600` dan `camera.env`, profile vision, refresh nama node, lalu up.
   **Data rehearsal di tujuan diganti; operasi ini destruktif.** Guard menolak
   unit lama aktif/tidak bisa diverifikasi, path sumber/tujuan overlap, dan marker
   `.cutover-done` existing. `--force` mengizinkan overwrite data setelah cutover:
   jangan gunakan tanpa backup serta persetujuan eksplisit. OLD_UNITS_CHECK=skip
   hanya untuk tes, bukan operasi produksi.
6. Ubah app_url Telegram ke `http://<IP-LAN>:7700` melalui UI, ukur gap deteksi.
   Verifikasi MQTT tanpa kredensial ditolak, semua layanan inti healthy, heartbeat
   vision online, satu event + klip/snapshot end-to-end pada GPU yang dipin,
   port lama tak lagi listening (kecuali Mosquitto bersama), dan reboot recovery.
   Retention dan vision tidak memiliki healthcheck HTTP; periksa log/hasil kerja.

### Backup manual dan rollback

Backup SQL polos ke direktori privat (di luar repo), selain salinan DATA_DIR
(termasuk go2rtc YAML, passwd, models, api, vision, secrets) dan `docker/.env`:

```bash
umask 077
docker compose -f docker/compose.yml --env-file docker/.env exec -T postgres \
  pg_dump -U isentinel --no-owner --no-privileges isentinel > /path/private/isentinel.sql
```

Untuk snapshot konsisten, hentikan writer api/vision/retention di jendela
maintenance sebelum dump + salin media. Named volume pgdata memerlukan dump
tersendiri; DATA_DIR saja bukan backup DB. Tidak ada backup otomatis pada siklus ini.

- **Sebelum data Docker baru penting:** `docker compose -f docker/compose.yml --env-file docker/.env down`
  (**tanpa `-v`**), lalu operator root `systemctl enable --now` unit lama yang
  dinonaktifkan (termasuk timer retensi); kembalikan app_url Telegram bila diubah.
- **Sesudah data baru terkumpul:** hentikan writer Docker, dump final seperti di
  atas, cadangkan DB host, dan dengan persetujuan operator DROP/CREATE DB host
  melalui `psql -d postgres` menggunakan koneksi privat. Restore SQL ke DB host:
  `psql -v ON_ERROR_STOP=1 "$HOST_DATABASE_URL" < /path/private/isentinel.sql`
  (gunakan URI PostgreSQL/libpq, bukan `postgresql+psycopg`, jangan log URI).
  Sinkronkan API/vision/models/secrets dari DATA_DIR Docker kembali ke lokasi
  legacy, periksa ownership/0600, pastikan kode legacy cocok dengan Alembic head,
  baru `down` tanpa `-v` dan enable layanan lama. Pastikan go2rtc legacy mendapat
  stream/config yang sesuai port lama; YAML Docker tidak bisa disalin mentah.
  Jangan menjalankan dua vision atau dua dispatcher Telegram bersamaan.
- **Rollback kode lokal sebelum deploy:** `git revert` commit Task 1–7
  (urut terbalik). Tidak ada perubahan server atau DB dari sesi executor.
