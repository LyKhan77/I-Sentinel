# Migrasi Docker (deployment satu perintah) Implementation Plan

> Status 2026-10-02: Task 1–7 selesai dan direview; perbaikan review (kredensial kamera `camera.env`, `-T`, model wajah non-fatal, peringatan IP) ada di commit berikutnya. Part B menunggu.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Folder `docker/` yang membangun dan menjalankan seluruh I-Sentinel (postgres, mosquitto, go2rtc, api, vision, web, retention) lewat `./docker/setup.sh`, plus skrip migrasi data dev.

**Architecture:** Satu `compose.yml` (project `isentinel`), tiga image (backend dipakai API dan retensi, vision, web), konfigurasi dari satu `docker/.env` yang dibuat `setup.sh`. Semua logika yang bisa diuji tanpa Docker (pembuatan `.env`, hitung jadwal retensi, rencana migrasi, entrypoint) ditulis sebagai kode yang dites pytest; build/run nyata diverifikasi di `gspe-ai3`.

**Tech Stack:** Docker Compose v2, Dockerfile (BuildKit), bash, Python 3.12 stdlib, nginx, pytest (venv backend).

**Spec:** `docs/superpowers/specs/2026-10-01-docker-deploy-design.md` (branch `feat/docker-deploy`, koreksi plan-time sudah masuk spec di `dc9ffa4`). Spec tahap 1: `2026-10-01-port-nondefault-design.md` (sudah ter-merge).

## Global Constraints

- Port tetap, tanpa `PORT_*`: dipublikasikan `7700` web, `7701` API, `7702` go2rtc API, `7703` WebRTC (tcp+udp), `7704` MQTT; `7705` (go2rtc RTSP) dan Postgres `5432` **tidak** dipublikasikan. Nomor di dalam container = nomor di host.
- Setiap URL layanan di compose menyebut **port eksplisit** (`mosquitto:7704`, `http://go2rtc:7702`, `rtsp://go2rtc:7705`, `http://api:7701`); kode jatuh ke `1883` bila port hilang.
- Container vision: `VISION_GO2RTC_URL=http://go2rtc:7702`, `VISION_MQTT_URL=mosquitto:7704`, `VISION_API_URL=http://api:7701`, `VISION_DETECTOR_MODEL=/models/yolo26s.engine`.
- `docker/.env` bermode 0600 dan di-gitignore; rahasia hex acak (`openssl rand -hex`); tidak ada rahasia di image; `setup.sh` idempoten dan **tidak pernah menimpa** `.env`, `passwd` Mosquitto, atau `go2rtc.yaml` yang sudah ada.
- `restart: unless-stopped`, `TZ=${TZ}`, logging `json-file` `max-size 10m` `max-file 5` di semua layanan; container berjalan sebagai `${HOST_UID}:${HOST_GID}` (kecuali `postgres` dan `web`).
- Profile compose `vision` (mati saat `--rehearse`); `deploy.resources.reservations.devices` nvidia `count: all`; `shm_size: ${VISION_SHM_SIZE}`.
- Konteks build semua image = root repo (`context: ..`), berkas abaikan per-Dockerfile (`<Dockerfile>.dockerignore`).
- Commit Conventional Commits, **tanpa atribusi AI** (AGENTS.md §9), commit lokal, jangan `git push`. Jangan `uv sync`/`uv lock`/venv baru. Jalankan suite berurutan. Bila `NODE_ENV=production` ter-set di shell: `env -u NODE_ENV`.
- Tes docker: `cd /Users/leekhan/project/I-Sentinel && backend/.venv/bin/python -m pytest docker/tests -q`. Tes yang butuh `docker compose` CLI di-`skip` bila tidak ada; build/run nyata hanya bila daemon aktif (`docker info`); bila tidak, catat "tidak dijalankan" di laporan. Mac ini `arm64`: image **vision** tidak dibangun di Mac.

## Review Focus

1. nginx men-cache IP `api` saat start → 502 permanen setelah container `api` dibuat ulang. Wajib `resolver 127.0.0.11` + `proxy_pass` bervariabel (Task 2).
2. `setup.sh` dijalankan ulang menimpa `JWT_SECRET`/`POSTGRES_PASSWORD`/`passwd`/`go2rtc.yaml` → DB terkunci, sesi putus, kredensial kamera hilang (Task 5).
3. `go2rtc.yaml` menyimpan kredensial RTSP kamera yang ditulis go2rtc saat runtime: harus 0600, di luar repo, dan tidak ter-overwrite (Task 4–5).
4. URL layanan tanpa port eksplisit jatuh ke port lama diam-diam (Task 4).
5. `--cutover` dijalankan dua kali, atau saat unit systemd lama masih aktif → data baru tertimpa / dua vision node (Task 6).

## File Structure

`docker/{compose.yml, .env.example, setup.sh}`; `docker/backend/{Dockerfile, Dockerfile.dockerignore, entrypoint.sh}`; `docker/web/{Dockerfile, Dockerfile.dockerignore, nginx.conf}`;
`docker/vision/{Dockerfile, Dockerfile.dockerignore, requirements.lock (sudah ada)}`; `docker/go2rtc/go2rtc.yaml.tmpl`; `docker/mosquitto/mosquitto.conf`;
`docker/scripts/{export-engine.sh, migrate-from-host.sh, retention_loop.py}`; `docker/tests/test_*.py`; ubah `backend/pyproject.toml` (extra `face`), `.gitignore`, dokumen Task 7.

---

### Task 1: Image backend (API + retensi)

**Files:** Create `docker/backend/{Dockerfile,Dockerfile.dockerignore,entrypoint.sh}`, `docker/tests/test_backend_image.py`. Modify `backend/pyproject.toml`.

**Interfaces:** Produces image tag `isentinel-api:local` (dibangun oleh `api` di Task 4; `retention` memakai tag yang sama). `entrypoint.sh`: bila `RUN_MIGRATIONS=1` jalankan `alembic upgrade head` (gagal → keluar non-nol, perintah tidak dijalankan), lalu `exec "$@"`.

- [ ] **Step 1: Tulis tes gagal** di `docker/tests/test_backend_image.py`:
  - `test_entrypoint_skips_migration_by_default`: `alembic` palsu di `PATH` yang mencatat argumennya ke berkas; `entrypoint.sh echo ok` tanpa `RUN_MIGRATIONS` → stdout `ok`, catatan kosong.
  - `test_entrypoint_runs_migration_before_command`: `RUN_MIGRATIONS=1` → catatan berisi tepat satu `upgrade head`, lalu `ok` tercetak.
  - `test_entrypoint_aborts_when_migration_fails`: `alembic` palsu keluar 1 → kode keluar entrypoint ≠ 0 dan `ok` **tidak** tercetak.
  - `test_pyproject_has_face_extra`: `tomllib` membaca `backend/pyproject.toml`; `project.optional-dependencies.face` memuat `insightface` dan `onnxruntime` (bukan `onnxruntime-gpu`).
- [ ] **Step 2: Jalankan, pastikan gagal** (`pytest docker/tests/test_backend_image.py`): berkas/extra belum ada.
- [ ] **Step 3: Implementasi.** `pyproject.toml`: extra `face = ["insightface>=0.7", "onnxruntime>=1.19"]`. `entrypoint.sh` (`set -e`). `Dockerfile`: dua tahap; builder `python:3.12-slim` + `build-essential`, `COPY backend/ /app/`, `pip install -e "/app[face]"` ke `/opt/venv` (**editable**: daftar `packages` di `pyproject` tidak memuat `app.ws`, instal non-editable merusak impor); runtime `python:3.12-slim` + `libgomp1 libgl1 libglib2.0-0`, salin `/opt/venv` dan `/app`, `ENV PATH=/opt/venv/bin:$PATH HOME=/tmp PYTHONUNBUFFERED=1`, `WORKDIR /app`, `COPY docker/backend/entrypoint.sh /entrypoint.sh` (executable), `ENTRYPOINT ["/entrypoint.sh"]`, `CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","7701"]`. `Dockerfile.dockerignore`: `**/.venv`, `**/__pycache__`, `**/node_modules`, `.git`, `temp`, `docs/evidence`.
- [ ] **Step 4: Jalankan tes** → lulus. Bila daemon aktif: `docker build -f docker/backend/Dockerfile -t isentinel-api:local .` lalu `docker run --rm isentinel-api:local python -c "import app.main, app.ws.hub, insightface, onnxruntime"` → exit 0. Bila `insightface` gagal dikompilasi di arm64, catat dan lanjut (verifikasi sebenarnya di `gspe-ai3`).
- [ ] **Step 5: Commit** `feat(docker): image backend (API + retensi) dengan entrypoint migrasi` — `git add docker/backend docker/tests/test_backend_image.py backend/pyproject.toml`.

### Task 2: Image web (Vite build + nginx)

**Files:** Create `docker/web/{Dockerfile,Dockerfile.dockerignore,nginx.conf}`, `docker/tests/test_nginx_conf.py`.

**Interfaces:** Produces image `isentinel-web:local` mendengarkan `7700`, memproksi `/api/` ke `api:7701`.

- [ ] **Step 1: Tulis tes gagal** (`test_nginx_conf.py`, membaca `nginx.conf` sebagai teks, satu tes per mode gagal): `test_listens_on_7700`; `test_api_proxy_survives_api_container_recreate` (ada `resolver 127.0.0.11` dan `proxy_pass` memakai variabel `$…`, bukan hostname literal); `test_api_proxy_passes_websocket_upgrade` (`proxy_http_version 1.1`, header `Upgrade` dan `Connection`); `test_upload_limit_allows_enrollment_photos_and_csv` (`client_max_body_size` ≥ 20m); `test_spa_fallback` (`try_files $uri /index.html`).
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasi.** `nginx.conf`: server `listen 7700`, `root /usr/share/nginx/html`, `location /api/ { set $api_up http://api:7701; proxy_pass $api_up; … proxy_read_timeout 3600s; }` (tanpa URI pada `proxy_pass` agar URI klien diteruskan utuh; teruskan `Host`, `X-Forwarded-For/Proto`), gzip aktif, `location / { try_files $uri /index.html; }`. `Dockerfile`: tahap `node:22-alpine` `WORKDIR /app/frontend`, `COPY frontend/package*.json`, `npm ci` (**tanpa** `NODE_ENV=production`; vite/tsc di devDependencies), `COPY frontend/ .`, `npm run build`; tahap `nginx:1.27-alpine` menyalin `dist` ke `/usr/share/nginx/html` dan `docker/web/nginx.conf` ke `/etc/nginx/conf.d/default.conf`; `HEALTHCHECK` `wget -qO- http://127.0.0.1:7700/`. `Dockerfile.dockerignore`: `**/node_modules`, `**/dist`, `.git`, `temp`.
- [ ] **Step 4: Jalankan tes** → lulus. Bila daemon aktif: build `isentinel-web:local`; `docker run --rm isentinel-web:local nginx -t` → `syntax is ok`.
- [ ] **Step 5: Commit** `feat(docker): image web (build Vite + nginx, proxy /api tahan ganti IP)`.

### Task 3: Image vision + export engine

**Files:** Create `docker/vision/{Dockerfile,Dockerfile.dockerignore}`, `docker/scripts/export-engine.sh`, `docker/tests/test_vision_image.py`. (`docker/vision/requirements.lock` sudah ada.)

**Interfaces:** Produces image `isentinel-vision:local` (entrypoint `isentinel-vision`). `export-engine.sh [--dry-run] [GPU_INDEX=${VISION_ENGINE_GPU:-0}]` menjalankan `docker compose … --profile vision run --rm --no-deps --workdir /models -e CUDA_VISIBLE_DEVICES=<GPU> vision python /app/vision/scripts/export_engine.py --model yolo26s.pt`; hasil `${DATA_DIR}/models/yolo26s.engine`.

- [ ] **Step 1: Tulis tes gagal:** `test_lock_is_fully_pinned` (setiap baris bukan komentar berbentuk `nama==versi`; tanpa `-e`, ` @ `, atau rentang); `test_lock_pins_gpu_stack` (`torch`, `tensorrt_cu13`, `onnxruntime-gpu`, `ultralytics`, `insightface`); `test_export_engine_dry_run_pins_gpu` (`export-engine.sh --dry-run 1` mencetak perintah dengan `CUDA_VISIBLE_DEVICES=1` dan `--workdir /models`); `test_export_engine_rejects_non_numeric_gpu` (keluar ≠ 0).
- [ ] **Step 2: Jalankan, pastikan gagal** (tes lock mungkin langsung lulus: itu pin regresi; buktikan bisa merah dengan menyisipkan baris `foo>=1` sementara, lalu kembalikan).
- [ ] **Step 3: Implementasi.** `Dockerfile`: `FROM nvidia/cuda:13.0.3-base-ubuntu24.04`; `apt` `python3.12 python3.12-venv python3-pip ffmpeg libgl1 libglib2.0-0`; venv `/opt/venv`; `COPY docker/vision/requirements.lock` + `pip install -r`; `COPY vision/ /app/vision/` + `pip install --no-deps -e /app/vision`; `ENV NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility,video HOME=/tmp PATH=/opt/venv/bin:$PATH`; `WORKDIR /app/vision`; `CMD ["isentinel-vision"]`. Dua paket opencv (full + headless) ikut dari lock apa adanya karena sudah teruji; `libgl1` melayani yang full. `export-engine.sh`: `set -euo pipefail`, validasi GPU `^[0-9]+$`, `--dry-run` hanya `echo`.
- [ ] **Step 4: Jalankan tes** → lulus. **Jangan** `docker build` di Mac (arm64); build nyata di Part B.
- [ ] **Step 5: Commit** `feat(docker): image vision CUDA 13 dengan versi terkunci + skrip export engine`.

### Task 4: Compose, template, dan loop retensi

**Files:** Create `docker/compose.yml`, `docker/.env.example`, `docker/mosquitto/mosquitto.conf`, `docker/go2rtc/go2rtc.yaml.tmpl`, `docker/scripts/retention_loop.py`, `docker/tests/{test_compose.py,test_retention_loop.py}`. Modify `.gitignore`.

**Interfaces:** `.env.example` mendefinisikan kunci: `HOST_UID HOST_GID TZ DATA_DIR GO2RTC_PUBLIC_HOST POSTGRES_PASSWORD JWT_SECRET NODE_API_KEY MQTT_USERNAME MQTT_PASSWORD ADMIN_USERNAME ADMIN_PASSWORD VISION_NODE_ID VISION_SHM_SIZE VISION_ENGINE_GPU COMPOSE_PROFILES RETENTION_DAYS` (nilai placeholder `CHANGE_ME`/contoh; `COMPOSE_PROFILES=vision`). Task 5 menghasilkan berkas bernama kunci yang sama. `retention_loop.py`: `seconds_until(now: datetime, at: str = "03:00") -> float` (selalu > 0; `now >= at` → besok), `main(run=…, sleep=…, max_runs=None)`.

- [ ] **Step 1: Tulis tes gagal.**
  `test_retention_loop.py`: `seconds_until` — 02:00 → 3600; tepat 03:00:00 → 86400; 23:30 → 12 jam (43200); nilai selalu > 0. `test_loop_survives_failed_sweep`: `run` pertama mengembalikan 1 lalu 0, `max_runs=2` → `sleep` dipanggil dua kali dan loop tidak melempar.
  `test_compose.py` (skip bila tak ada `docker compose`; memakai `docker compose -f docker/compose.yml --env-file docker/.env.example --profile vision config --format json`): port terpublikasi **tepat** `7700 7701 7702 7703/tcp 7703/udp 7704` (tidak ada `7705`, `5432`); `vision` hanya hidup dengan profile `vision` (tanpa profile, `vision` tidak muncul); setiap nilai env bernama `*_URL` yang berisi host harus memuat `:\d+`; `postgres` memakai named volume `pgdata`; tiap layanan punya `restart: unless-stopped` dan `logging.driver json-file`; `api`, `postgres`, `mosquitto`, `web` punya healthcheck; `vision` meminta GPU nvidia; `api` tidak memuat `POSTGRES_PASSWORD` mentah di luar `DATABASE_URL`.
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasi.** `compose.yml` (`name: isentinel`): tujuh layanan sesuai tabel spec §3.2 dan Global Constraints; `api`: `build: {context: .., dockerfile: docker/backend/Dockerfile}`, `image: isentinel-api:local`, env eksplisit (bukan `env_file`): `DATABASE_URL=postgresql+psycopg://isentinel:${POSTGRES_PASSWORD}@postgres:5432/isentinel`, `JWT_SECRET`, `NODE_API_KEY`, `ADMIN_USERNAME/PASSWORD`, `MQTT_URL=mosquitto:7704`, `MQTT_USERNAME/PASSWORD`, `GO2RTC_URL=http://go2rtc:7702`, `GO2RTC_RTSP_URL=rtsp://go2rtc:7705`, `GO2RTC_PUBLIC_HOST`, `STORAGE_ROOT=/data/api`, `FACE_MODEL_DIR=/data/api/faces_models`, `CAMERA_SECRETS_FILE=/secrets/camera-secrets.json`, `COOKIE_SECURE=false`, `RETENTION_DAYS`, `RUN_MIGRATIONS=1`; healthcheck `python -c` + `urllib` ke `/api/v1/health`. `retention`: `image: isentinel-api:local`, `pull_policy: never`, `depends_on: api (healthy)`, mount `./scripts/retention_loop.py:/retention_loop.py:ro`, `command: ["python","/retention_loop.py"]`, `working_dir: /app`. `go2rtc`: `alexxit/go2rtc:1.9.9` (sama dengan server), mount `${DATA_DIR}/go2rtc:/config` rw. `mosquitto`: `eclipse-mosquitto:2.0.22`, mount `./mosquitto/mosquitto.conf` ro + `${DATA_DIR}/mosquitto/passwd` + `${DATA_DIR}/mosquitto/data`. `vision` sesuai spec §3.2 dan Global Constraints; mount `${DATA_DIR}/vision:/data/vision`, `${DATA_DIR}/models:/models`, `${DATA_DIR}/api/faces_models:/faces:ro` dengan `VISION_FACE_MODEL_DIR=/faces`. `web`: `7700:7700`, `depends_on: api (healthy)`. `mosquitto.conf`: `listener 7704 0.0.0.0`, `allow_anonymous false`, `password_file /mosquitto/config/passwd`, persistence ke `/mosquitto/data/`, `log_dest stdout`. `go2rtc.yaml.tmpl`: `api: { listen: ":7702", origin: "*" }`, `webrtc: { listen: ":7703", candidates: ["${GO2RTC_PUBLIC_HOST}:7703"] }`, `rtsp: { listen: ":7705" }`, `log: { level: info }`. `.gitignore`: `docker/.env`, `docker/*.local`. `retention_loop.py`: dua fungsi di atas + pemanggilan `subprocess.run(["python","scripts/retention_sweep.py"])` dengan log; kegagalan dicatat, loop lanjut.
- [ ] **Step 4: Jalankan tes** → lulus; `docker compose -f docker/compose.yml --env-file docker/.env.example config -q` exit 0.
- [ ] **Step 5: Commit** `feat(docker): compose.yml, .env.example, template go2rtc/mosquitto, loop retensi`.

### Task 5: `setup.sh` idempoten

**Files:** Create `docker/setup.sh`, `docker/tests/test_setup_env.py`.

**Interfaces:** Consumes kunci `.env.example` (Task 4), `export-engine.sh` (Task 3). Produces `setup.sh [--env-only] [--rehearse] [--no-engine]`; env `ENV_FILE` (default `docker/.env`), `DATA_DIR`, `GO2RTC_PUBLIC_HOST` sebagai override. `--env-only`: hanya buat `.env`, folder `${DATA_DIR}/{api,vision,models,go2rtc,mosquitto/data,secrets}`, dan render `go2rtc.yaml`; tanpa Docker.

- [ ] **Step 1: Tulis tes gagal** (`subprocess`, `DATA_DIR` dan `ENV_FILE` di `tmp_path`, `GO2RTC_PUBLIC_HOST=192.0.2.10`): `test_env_created_with_strong_secrets_and_0600` (mode `0o600`; `JWT_SECRET`, `NODE_API_KEY` ≥ 32 karakter; `POSTGRES_PASSWORD` hanya `[0-9a-f]`; `ADMIN_PASSWORD` dan `MQTT_PASSWORD` tak kosong; semua kunci `.env.example` hadir); `test_rerun_keeps_env_byte_identical` (isi `.env` sama persis setelah run kedua); `test_go2rtc_yaml_rendered_once_0600` (berisi `192.0.2.10:7703`; mode `0o600`; run kedua dengan IP lain **tidak** mengubahnya); `test_rehearse_disables_vision_profile` (`--rehearse` → `COMPOSE_PROFILES=` kosong; default `vision`); `test_data_dirs_created`; `test_admin_credentials_printed_only_when_env_is_created` (keluaran run pertama memuat `ADMIN_USERNAME` dan `ADMIN_PASSWORD`; run kedua tidak memuat password).
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasi** `setup.sh` (`set -euo pipefail`; fungsi kecil, mode `--env-only` berhenti setelah bagian 2–3). Urutan mode penuh (spec §3.5): prasyarat (`docker`, `docker compose`, `docker info` tanpa sudo; runtime `nvidia` di `docker info`, bila tak ada → peringatan dan profile `vision` dikosongkan); tolak jalan bila `7700–7704` dipakai proses lain saat stack belum berjalan; IP LAN (`hostname -I` Linux, `ipconfig getifaddr en0` macOS, override env), `TZ` dari `/etc/timezone` (fallback `Asia/Jakarta`), `id -u/-g`; buat `.env` hanya bila belum ada; render `go2rtc.yaml` dengan `sed` hanya bila belum ada; buat `passwd` Mosquitto lewat `docker run --rm --user $HOST_UID:$HOST_GID -v … eclipse-mosquitto:2.0.22 mosquitto_passwd -b -c` hanya bila belum ada; `compose build`; `up -d postgres mosquitto go2rtc api`; tunggu `api` healthy (≤120 dtk, polling); baca id node `server` lewat `compose exec -T postgres psql -U isentinel -d isentinel -tAc "select id from node where type='server' order by id limit 1"` dan tulis `VISION_NODE_ID` ke `.env` (ganti nilai kunci yang ada, tanpa menyentuh baris lain); unduh model wajah bila `${DATA_DIR}/api/faces_models` kosong (`compose run --rm --no-deps api python scripts/download_face_models.py`); bila profile `vision` aktif dan `${DATA_DIR}/models/yolo26s.engine` tak ada (dan tanpa `--no-engine`) → `export-engine.sh`; `compose up -d`; cetak URL `http://<ip>:7700`, peta port, `ADMIN_USERNAME`/`ADMIN_PASSWORD` **hanya pada run yang membuat `.env`** (selanjutnya hanya menunjuk ke `.env`), dan petunjuk menaruh `yolo26s.pt` manual bila offline.
- [ ] **Step 4: Jalankan tes** → lulus. `bash -n docker/setup.sh` bersih. Bila daemon aktif di Mac: `./docker/setup.sh --rehearse --no-engine` dengan `DATA_DIR` sementara → `curl -s localhost:7701/api/v1/health` `{"status":"ok"}`, UI `localhost:7700` 200, login admin, `docker compose ps` semua `healthy`; jalankan ulang (idempoten); `compose down -v` dan hapus `DATA_DIR` sementara. Catat bila daemon tak ada.
- [ ] **Step 5: Commit** `feat(docker): setup.sh idempoten (env, build, up, node id, model wajah, engine)`.

### Task 6: `migrate-from-host.sh`

**Files:** Create `docker/scripts/migrate-from-host.sh`, `docker/tests/test_migrate.py`.

**Interfaces:** `migrate-from-host.sh (--rehearse | --cutover) [--dry-run] [--force]`; env `HOST_ENV_FILE`, `HOST_DATA_ROOT`, `HOST_SECRETS_FILE`, `HOST_ENGINE`, `OLD_UNITS_CHECK=skip` (hanya tes). `--dry-run` mencetak setiap perintah berawalan `+ ` tanpa menjalankannya dan menyamarkan kredensial `DATABASE_URL`.

- [ ] **Step 1: Tulis tes gagal** (`--dry-run`, berkas env palsu di `tmp_path`): `test_rehearse_plan` (urutan: stop `api` dan `retention` → `pg_dump` host → recreate DB di container → restore lewat `psql` → `rsync` `api/` → `up -d`; **tidak** ada `camera-secrets` dan tidak ada `COMPOSE_PROFILES=vision`; kata sandi DB tidak muncul di keluaran); `test_cutover_plan` (rsync `api/` dan `vision/`, salin secrets, set `COMPOSE_PROFILES=vision`, `compose up -d`); `test_cutover_refuses_when_old_units_active` (`systemctl` palsu melaporkan `active` → keluar ≠ 0 sebelum perintah destruktif apa pun); `test_cutover_refuses_second_run_without_force` (penanda `${DATA_DIR}/.cutover-done` ada); `test_requires_exactly_one_mode`.
- [ ] **Step 2: Jalankan, pastikan gagal.**
- [ ] **Step 3: Implementasi.** `set -euo pipefail`; `DATABASE_URL` host dibaca dengan python (`postgresql+psycopg://` → `postgresql://`), tidak pernah di-echo; dump `pg_dump --no-owner --no-privileges` (SQL polos); restore: hentikan `api`/`retention`, `DROP DATABASE`/`CREATE DATABASE isentinel` lewat `psql -d postgres`, pipe dump ke `psql -d isentinel`; `rsync -a` (cutover: `--delete`) `${HOST_DATA_ROOT}/api/` → `${DATA_DIR}/api/` dan, hanya cutover, `vision/`; salin `HOST_ENGINE` (`/home/gspe-ai3/isentinel-data/models/yolo26s.engine`) ke `${DATA_DIR}/models` bila belum ada; cutover: periksa `systemctl is-active isentinel-api isentinel-web vision-node go2rtc isentinel-retention.timer` (semua harus bukan `active`, kecuali `OLD_UNITS_CHECK=skip`), salin `HOST_SECRETS_FILE` ke `${DATA_DIR}/secrets/` mode 0600, ganti `COMPOSE_PROFILES=vision` di `.env`, tulis `.cutover-done`; akhiri dengan mencetak pengingat `app_url` Telegram dan perintah verifikasi.
- [ ] **Step 4: Jalankan tes** → lulus; `bash -n` bersih. Tidak ada eksekusi nyata di Mac.
- [ ] **Step 5: Commit** `feat(docker): migrate-from-host.sh (--rehearse / --cutover / --dry-run)`.

### Task 7: Dokumen

**Files:** Modify `README.md`, `ARCHITECTURE.md`, `docs/RUNBOOK.md`, `docs/DEVELOPMENT.md`, `ROADMAP.md`, `CHANGELOG.md`.

- [ ] **Step 1: Perbarui** (spec §3.10): README bagian "Quick start Docker" (`git clone`, `./docker/setup.sh`, URL, di mana `ADMIN_PASSWORD`); ARCHITECTURE topologi container dan tabel layanan; RUNBOOK bagian Docker (`docker compose -f docker/compose.yml ps/logs/restart <svc>`, update `git pull && ./docker/setup.sh`, rebuild engine, backup `pg_dump` dari container, rollback dan dump balik, prosedur cutover/rehearsal dari spec §3.6) dengan penanda "belum aktif di `gspe-ai3` sampai cutover"; DEVELOPMENT catatan Docker; ROADMAP baris `DK` `[~] kode selesai, belum diverifikasi di server` (angka uji nyata); CHANGELOG entri (konteks, file, uji dengan keluaran nyata, dampak: belum ada perubahan server, rollback `git revert`). Tulis hanya yang benar-benar sudah dijalankan.
- [ ] **Step 2: Verifikasi:** `pytest docker/tests -q` hijau; `pytest tests -q -m "not gpu"` (backend) dan `npx vitest run` tetap sama dengan baseline (656 passed; 33 file / 420); `git diff --stat main...HEAD` hanya berisi berkas pada daftar Files + spec/plan.
- [ ] **Step 3: Commit** `docs: Docker (README, ARCHITECTURE, RUNBOOK, DEVELOPMENT, ROADMAP, CHANGELOG)`.

---

## Part B — Operasi (sesi perencanaan; bukan tugas executor; tiap perubahan di server butuh OK eksplisit pengguna)

1. Clone terpisah `/home/gspe-ai3/project_cv/I-Sentinel-docker` (jangan mengganti branch pohon systemd yang sedang berjalan), `DATA_DIR=/home/gspe-ai3/project_cv/I-Sentinel-docker-data`.
2. Build tiga image di server (`docker compose build`); `docker build` vision pertama kali di sini. Verifikasi `alexxit/go2rtc:1.9.9` dan `eclipse-mosquitto:2.0.22` tertarik.
3. `./docker/setup.sh --rehearse` lalu `migrate-from-host.sh --rehearse`; jalankan uji spec §3.9 (instalasi bersih, idempoten, port, LAN, migrasi jumlah baris, metrik host, latensi enrollment CPU, reboot).
4. Uji vision di jendela singkat (satu kamera, GPU yang dipin) termasuk `export-engine.sh` pada 4090 dan 5080 dan ukuran `shm_size` ring; hasil menetapkan default `VISION_SHM_SIZE`.
5. Cutover jam sepi sesuai spec §3.6 (satu perintah root pengguna untuk menonaktifkan unit lama), verifikasi, catat durasi gap deteksi; rollback sesuai spec §3.8.

## Self-review (spec coverage)

| Spec | Task |
|---|---|
| K1 `docker/`, §3.1 struktur | 1–6 |
| K2 port tetap/URL eksplisit, §3.2 | 4 (tes compose) |
| K3 API CPU, §3.3 backend | 1 |
| K4 vision GPU/lock/engine, §3.3 | 3, 4 |
| K5 web nginx | 2 |
| K6 retensi | 4 |
| K7–K8 data/rahasia/`.env` | 4, 5 |
| K9 `setup.sh` idempoten, §3.5 | 5 |
| K10 migrasi dua mode, §3.6 | 6 |
| K11 systemd, §3.7–3.8 | Part B, 7 |
| §3.9 verifikasi | Part B (nyata), tes pytest per task |
| §3.10 dokumen | 7 |
