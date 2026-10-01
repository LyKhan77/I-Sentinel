# Spec — Port non-default (blok 7700–7705)

Status: **menunggu review spec tertulis**.
Branch: `feat/port-nondefault` (dari `main` @ `cc18cd2`).
Plan: belum ada (ditulis setelah spec disetujui, `docs/superpowers/plans/2026-10-01-port-nondefault.md`).
Konteks: tahap 1 dari dua tahap, **perubahan repo saja**. Tahap 2 = migrasi Docker (`2026-10-01-docker-deploy-design.md`) yang memakai peta port ini dan melakukan satu-satunya cutover server.

---

## 1. Latar

Server dev `gspe-ai3` dipakai bersama proyek lain (OCR, AMR, dll.). Semua port I-Sentinel masih default (`8000`, `5173`, `1984`, `8554`, `8555`, `1883`),
sehingga rawan bentrok di server dev maupun production. Tujuan: pindah ke blok port 4 digit yang tidak umum, mudah diingat, dan bisa dibuka firewall dengan satu aturan rentang.
Peta yang sama dipakai tahap 2 (Docker), jadi pengguna dan firewall tidak berganti dua kali.

### Kondisi (`main` @ `cc18cd2`, server dev diperiksa read-only 2026-10-01)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Port tersebar di: unit systemd (`--port 8000`, `--port 5173`), `.env` (`MQTT_URL`, `GO2RTC_URL`), `vision.env` (`VISION_MQTT_URL`, `VISION_API_URL`, `VISION_CAMERAS_JSON`), `go2rtc.yaml`, konfigurasi mosquitto, proxy Vite. | `deploy/`, `.env.example`, `frontend/vite.config.ts:11` |
| 2 | `config_push.py` menulis `rtsp://localhost:8554/cam_{id}` **langsung di kode** untuk node bertipe `server`; nilai ini dikirim ke vision node lewat MQTT. Tidak bisa diubah lewat konfigurasi. | `backend/app/services/config_push.py:84` |
| 3 | Browser memutar live langsung ke go2rtc: `LiveWall.tsx` memasang `<video-stream src={live.webrtc}>` (`ws://<GO2RTC_PUBLIC_HOST>:<port go2rtc_url>/api/ws`). Port go2rtc API karenanya harus terjangkau klien LAN; bila tidak, tile jatuh ke snapshot lewat proxy API. `README.md:20` menulis go2rtc 1984 tertutup dari LAN, bertentangan dengan perilaku kode; probe dari Mac di LAN (2026-10-01) menunjukkan `192.168.2.133:1984` **terbuka**, jadi README yang basi. | `backend/app/api/live.py:63-76`, `frontend/src/features/live/LiveWall.tsx:47-58` |
| 4 | `_rewrite_host` mengambil port dari `GO2RTC_URL`, jadi URL live mengikuti port baru otomatis. | `backend/app/api/live.py:28-30` |
| 5 | Mosquitto di server mendengarkan lewat `/etc/mosquitto/conf.d/default.conf` (`listener 1883` + `password_file`), bukan `mosquitto.conf` utama. File repo `deploy/mosquitto/mosquitto.conf` berbeda isi dengan yang berjalan. | server, root-owned |
| 6 | Akun `gspe-ai3` bukan root dan `sudo` meminta password. File root-owned yang perlu diubah: `/etc/systemd/system/isentinel-api.service`, `isentinel-web.service`, `/etc/mosquitto/conf.d/default.conf`, plus firewall. Firewall host **aktif dengan whitelist per port**: probe dari LAN menunjukkan `8000 5173 1883 1984 8077 5151` terbuka, sedangkan `3131` tertutup walau listening di `0.0.0.0` (rincian aturan tidak terbaca tanpa root). Port baru karenanya pasti perlu dibuka. Akun ada di grup `docker`. | server |
| 7 | `app_url` Telegram tersimpan di DB (setting notifikasi) dan memuat port web (`http://192.168.2.133:5173`). | `backend/app/services/telegram.py`, UI Notifikasi |
| 8 | Port yang sudah dipakai proyek lain di server dev: `80 3131 4040 4096 5151 5345 5511 6379 6388 8005 8011 8077 8125 9400` dan UDP `7000–7019`. Rentang `7700–7799` kosong (TCP/UDP/Docker), di bawah ephemeral OS (`32768–60999`). | server |

## 2. Keputusan

| # | Keputusan |
|---|---|
| K1 | **Blok `7700–7705`.** LAN-facing berurutan `7700–7704`, RTSP terpisah di `7705` (hanya loopback). `7706–7709` dicadangkan, tidak dipakai. `7777` dihindari. |
| K2 | **Angka baru ditulis di titik konfigurasi yang sudah ada** (`.env`, `vision.env`, unit, `go2rtc.yaml`, mosquitto), bukan lapisan `PORT_*` baru. Default di kode tetap port lama sehingga dev lokal (`uvicorn --port 8000`, `npm run dev`) tidak berubah. Tidak ada variabel `PORT_*` terpusat di tahap mana pun: port tetap, karena `_rewrite_host` (fakta 4) mengambil port go2rtc untuk URL ke browser dari `GO2RTC_URL`, sehingga port internal dan port yang dipublikasikan harus sama. |
| K3 | **Kode berubah di dua titik saja:** `config_push.py` memakai setting baru `go2rtc_rtsp_url` (default `rtsp://localhost:8554`), dan `vite.config.ts` membaca target proxy dari env `API_URL` (default `http://localhost:8000`). |
| K4 | **go2rtc RTSP diikat ke `127.0.0.1:7705`.** go2rtc tidak punya autentikasi, dan tidak ada pembaca RTSP dari luar host: vision node server membaca dari localhost, node edge (Fase E) menarik langsung dari kamera. |
| K5 | **go2rtc API (`7702`) dan WebRTC (`7703`) tetap terbuka ke LAN** karena Live Wall memutar langsung dari browser (fakta 3). Pengetatan origin (`api.origin: "*"`) di luar cakupan. |
| K6 | **Tidak ada cutover systemd di server dev.** Server pindah sekali langsung ke Docker (tahap 2), diuji paralel dengan systemd lama karena port `77xx` tidak bentrok. Alasan di 3.3. |
| K7 | File unit dan template di repo tetap diperbarui ke port baru agar instalasi systemd baru konsisten, tetapi **tidak di-deploy** ke server dev. |

## 3. Desain

### 3.1 Peta port

| Port | Fungsi | Sebelumnya | Akses | Pemilik konfigurasi |
|---|---|---|---|---|
| 7700 | Web UI (Vite dev) | 5173 | LAN | `isentinel-web.service` |
| 7701 | API FastAPI | 8000 | LAN | `isentinel-api.service` |
| 7702 | go2rtc API (WS/MSE/HLS/snapshot) | 1984 | LAN | `go2rtc.yaml` `api.listen` |
| 7703 | go2rtc WebRTC (tcp+udp) | 8555 | LAN | `go2rtc.yaml` `webrtc.listen` |
| 7704 | MQTT Mosquitto | 1883 | LAN (Jetson Fase E) | `conf.d/default.conf` `listener` |
| 7705 | go2rtc RTSP | 8554 | `127.0.0.1` saja | `go2rtc.yaml` `rtsp.listen` |

Tidak berubah: Postgres host `127.0.0.1:5432` (hanya localhost, tahap 2 memindahkannya ke jaringan internal compose); port RTSP kamera/NVR eksternal (`:8554` di host kamera adalah milik perangkat);
port 22. Firewall: satu aturan `7700:7704/tcp` + `7703/udp`; `7705` tidak dibuka.

### 3.2 Perubahan repo

Kode (TDD, test dulu):
- `backend/app/core/config.py`: `go2rtc_rtsp_url: str = "rtsp://localhost:8554"`.
- `backend/app/services/config_push.py:84`: `source_url = f"{settings.go2rtc_rtsp_url.rstrip('/')}/cam_{cam.id}"`.
- `frontend/vite.config.ts`: `target: process.env.API_URL ?? 'http://localhost:8000'`.

Deploy dan template (tidak berpengaruh ke dev lokal):
- `deploy/systemd/isentinel-api.service`: `--port 7701`.
- `deploy/systemd/isentinel-web.service`: `--port 7700 --strictPort` dan `Environment=API_URL=http://localhost:7701`. `strictPort` agar bentrok gagal keras, bukan diam-diam pindah port.
- `deploy/go2rtc/go2rtc.example.yaml`: `api: { listen: ":7702", origin: "*" }`, `webrtc: { listen: ":7703" }`, `rtsp: { listen: "127.0.0.1:7705" }`.
- `deploy/mosquitto/mosquitto.conf`: `listener 7704 0.0.0.0` (file template; di server nilai ini ada di `conf.d/default.conf`, lihat 3.3).
- `.env.example`: `MQTT_URL=localhost:7704`, `GO2RTC_URL=http://localhost:7702`, `GO2RTC_RTSP_URL=rtsp://localhost:7705`.
- `deploy/vision.env.example`: `VISION_MQTT_URL=...:7704`, `VISION_API_URL=http://localhost:7701`, `source_url` contoh ke `:7705`.
- `deploy/bootstrap.sh`: `curl localhost:7701`. Skrip `deploy/loadtest/*` tetap memakai env override (`ISENTINEL_API`, `GO2RTC_API`); runbook mencatat nilai barunya.
- `frontend/src/app/i18n.tsx`: contoh hint `notifications.appUrlHint` (id dan en) `:5173` → `:7700`.
- `backend/app/api/live.py` docstring `camera_snapshot`: hapus klaim "firewall hanya membuka 8000/5173/1883" yang basi (komentar saja).

Dokumen: `README.md` (diagram + baris "Port terbuka di LAN" dikoreksi sesuai K5), `ARCHITECTURE.md`, `docs/RUNBOOK.md` (tabel port, perintah health, checklist cutover + rollback root), `docs/DEVELOPMENT.md`, `ROADMAP.md`, `CHANGELOG.md`, catatan Fase E (`VISION_MQTT_URL=<host>:7704`).

### 3.3 Server dev: tidak ada perubahan di tahap ini

Tahap 1 **tidak men-deploy apa pun** ke `gspe-ai3`. Cutover port dikerjakan sekali lewat Docker (spec tahap 2, `2026-10-01-docker-deploy-design.md`), yang memakai peta 3.1.
Alasan: Docker tidak butuh root dan port yang dipublikasikannya melewati firewall host (probe LAN 2026-10-01: `5511 9400 8005` milik container terbuka, `3131` milik proses host tertutup),
sedangkan cutover systemd butuh root untuk dua unit, `conf.d/default.conf`, dan firewall, lalu disusul cutover Docker kedua. Systemd dev lama (port default) tetap berjalan sampai Docker menggantikannya.
File unit dan template di repo tetap diperbarui (3.2) supaya instalasi systemd baru konsisten dengan peta port.

### 3.4 Rollback

`git revert` commit tahap 1. Tidak ada perubahan server, DB, atau migrasi.

### 3.5 Pengujian dan verifikasi

Backend (`test_config_push.py`): `source_url` node server memakai `settings.go2rtc_rtsp_url` (monkeypatch ke `rtsp://localhost:7705` → `rtsp://localhost:7705/cam_{id}`); default tanpa override tetap `rtsp://localhost:8554/cam_{id}` (uji lama dipertahankan); slash di akhir nilai tidak menggandakan `/`.
Backend (`test_go2rtc.py`): dengan `go2rtc_url=http://localhost:7702` dan `go2rtc_public_host=192.168.2.133`, URL `webrtc`/`mse`/`hls` dari `/live` memakai `:7702` (regresi fakta 4).
Frontend: tanpa uji baru; `vite.config.ts` hanya konfigurasi. Bukti: `pytest -m "not gpu"`, `npx vitest run`, `npm run build`, `npm run lint` ditempel di `CHANGELOG.md`; `vite` dijalankan lokal dengan `API_URL` dan tanpanya (proxy target benar di kedua kasus).

## 4. Di luar cakupan

Cutover server dev/prod, Docker, nginx dan build statis menggantikan Vite dev, pemindahan Postgres, pengetatan `api.origin` go2rtc, TLS, perubahan port di Jetson/edge nyata (hanya dokumentasi Fase E). Semua dibahas di spec tahap 2.

## 5. Risiko

| Risiko | Mitigasi |
|---|---|
| Default kode berubah tak sengaja → dev lokal rusak | Default kode tetap port lama; uji default dipertahankan (3.5) |
| Template (`go2rtc.example.yaml`, unit) dipakai apa adanya di server lama dan memutus port | Template hanya untuk instalasi baru; server dev lama tidak di-deploy di tahap 1 (3.3) |
| Proyek lain mengambil `7700–7705` kemudian | Blok diverifikasi kosong 2026-10-01; daftar port dipakai dicatat di runbook |

## 6. Eksekusi

Plan ditulis setelah spec disetujui (skill `writing-plans`): tiga perubahan kode (TDD), pembaruan template dan dokumen. Tidak ada langkah deploy; sesi eksekusi berhenti di `git push`.
