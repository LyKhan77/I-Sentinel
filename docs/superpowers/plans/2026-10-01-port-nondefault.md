# Port Non-default (blok 7700–7705) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repo memakai peta port `7700–7705` di semua template, unit, dan dokumen, dan dua nilai yang tertanam di kode (`rtsp://localhost:8554`, proxy Vite `:8000`) menjadi bisa dikonfigurasi.

**Architecture:** Default di kode tetap port lama, sehingga dev lokal tidak berubah. Angka baru hanya muncul di berkas deploy/template/dokumen. Dua perubahan kode: setting `go2rtc_rtsp_url` dan env `API_URL` untuk proxy Vite. Tidak ada deploy ke server di tahap ini.

**Tech Stack:** FastAPI + pydantic-settings + pytest (backend), Vite 8 + Vitest + oxlint (frontend), systemd/go2rtc/mosquitto (berkas template).

**Spec:** `docs/superpowers/specs/2026-10-01-port-nondefault-design.md` (branch `feat/port-nondefault`). Tahap berikutnya: `docs/superpowers/specs/2026-10-01-docker-deploy-design.md`.

## Global Constraints

- Peta port (spec 3.1): `7700` web, `7701` API, `7702` go2rtc API, `7703` go2rtc WebRTC (tcp+udp), `7704` MQTT, `7705` go2rtc RTSP (hanya `127.0.0.1`). `7706–7709` cadangan, tidak dipakai; `7777` dihindari.
- Default di kode **tidak berubah** (`8000`, `8554`, `1883`, `1984`); dev lokal (`uvicorn --port 8000`, `npm run dev`) harus tetap jalan tanpa env tambahan.
- Tidak ada variabel `PORT_*` terpusat (spec K2).
- Berkas `.env`/`vision.env` baru ditulis **tanpa komentar inline** (`EnvironmentFile` systemd tidak mendukungnya).
- Tidak ada perubahan di server `gspe-ai3`, tidak ada ssh. Unit dan template di repo diperbarui tetapi tidak di-deploy (spec K6, K7).
- Commit Conventional Commits, **tanpa atribusi AI** (`Co-Authored-By`, "Generated with") di commit, kode, atau dokumen (AGENTS.md §9). Jangan `git push` kecuali diminta pengguna.
- Jangan `uv sync`/`uv lock`/membuat ulang venv. Jalankan suite berurutan, tidak bersamaan.
- Tes: backend `cd backend && .venv/bin/pytest tests -q -m "not gpu"`; frontend `cd frontend && npx vitest run`, `npm run build`, `npm run lint`.

## Review Focus

1. `GO2RTC_RTSP_URL` berakhiran `/` → URL `rtsp://…:7705//cam_N` (diuji, Task 1).
2. `go2rtc_url` bernomor port baru → URL `webrtc`/`mse`/`hls` ke browser ikut port itu (diuji, Task 1).
3. `API_URL=` terset tetapi kosong → proxy Vite tidak boleh memakai string kosong; harus jatuh ke `http://localhost:8000` (`||`, bukan `??`; diverifikasi, Task 2).
4. Komentar inline di baris port `.env.example`/`vision.env.example` merusak nilai di `EnvironmentFile` (diperiksa dengan grep, Task 3).
5. Listener RTSP terikat `127.0.0.1` tetapi URL memakai `localhost` yang dapat me-resolve ke `::1` lebih dulu → klien tanpa fallback gagal: template memakai `127.0.0.1` literal (deviasi dari spec; Task 3).

**Deviasi dari spec (disengaja):** nilai `GO2RTC_RTSP_URL` dan `source_url` di template memakai `rtsp://127.0.0.1:7705`, bukan `rtsp://localhost:7705` (butir 5). Task 3 menambahkan koreksi satu baris ke spec 3.2.

## File Structure

| Berkas | Tanggung jawab |
|---|---|
| `backend/app/core/config.py`, `backend/app/services/config_push.py` | Setting `go2rtc_rtsp_url`; node `server` memakainya |
| `backend/tests/test_config_push.py`, `backend/tests/test_go2rtc.py` | Uji Task 1 |
| `frontend/vite.config.ts` | Target proxy dari `API_URL` |
| `deploy/systemd/isentinel-{api,web}.service`, `deploy/go2rtc/go2rtc.example.yaml`, `deploy/mosquitto/mosquitto.conf`, `deploy/vision.env.example`, `deploy/bootstrap.sh`, `.env.example` | Template berpeta port baru |
| `frontend/src/app/i18n.tsx`, `backend/app/api/live.py` | Hint contoh port dan docstring basi |
| `README.md`, `ARCHITECTURE.md`, `docs/RUNBOOK.md`, `docs/DEVELOPMENT.md`, `ROADMAP.md`, `CHANGELOG.md` | Dokumen |

---

### Task 1: Setting `go2rtc_rtsp_url` + regresi URL live

**Files:**
- Modify: `backend/app/core/config.py` (setelah `go2rtc_url`), `backend/app/services/config_push.py:84`
- Test: `backend/tests/test_config_push.py`, `backend/tests/test_go2rtc.py`

**Interfaces:**
- Produces: `settings.go2rtc_rtsp_url: str`, default `"rtsp://localhost:8554"`, env `GO2RTC_RTSP_URL`. Dipakai Task 3 (`.env.example`) dan tahap 2 (Docker).

- [ ] **Step 0: Catat baseline.** `cd backend && .venv/bin/pytest tests -q -m "not gpu"` → catat jumlah `passed` (terakhir tercatat 653). Catat juga hasil `cd ../frontend && npx vitest run` (terakhir 420) dan jumlah peringatan `npm run lint`.

- [ ] **Step 1: Tulis tes gagal** di `backend/tests/test_config_push.py` (memakai `_node`, `_cam`, `_zone` yang ada):
  - `test_build_node_config_server_source_url_uses_go2rtc_rtsp_url(db, monkeypatch)`: `monkeypatch.setattr(settings, "go2rtc_rtsp_url", "rtsp://127.0.0.1:7705")`; node `server` + satu kamera enabled → `cfg["cameras"][0]["source_url"] == f"rtsp://127.0.0.1:7705/cam_{cam.id}"`.
  - `test_build_node_config_server_source_url_ignores_trailing_slash(db, monkeypatch)`: nilai `"rtsp://127.0.0.1:7705/"` → hasil sama, tanpa `//cam_`.
  Tes lama `test_build_node_config_server_includes_active_cam_and_zones_excludes_disabled` (assert `rtsp://localhost:8554/cam_{id}`) **tidak diubah**: ia mengunci default.
  Di `backend/tests/test_go2rtc.py` tambah `test_live_endpoint_urls_follow_go2rtc_url_port(client, monkeypatch)`: `settings.go2rtc_url = "http://localhost:7702"`, `go2rtc_public_host = "192.168.2.133"`; `GET /api/v1/cameras/{cid}/live` dengan header `Host: localhost:7701` → `webrtc`, `mse`, `hls` masing-masing diawali `http://192.168.2.133:7702/api/ws?src=`, `…/api/stream.mse?src=`, `…/api/stream.m3u8?src=`. Ikuti pola `test_live_endpoint_prefers_go2rtc_public_host_over_request_host`. Tes ini sudah lulus saat ditulis (pin regresi spec fakta 4), bukan merah.
  Perbaiki komentar basi di `test_go2rtc.py` (baris "snapshot bukan URL go2rtc: port 1984 tidak terjangkau dari LAN"): ganti jadi "snapshot bukan URL go2rtc: lewat proxy API agar same-origin dan di belakang auth".

- [ ] **Step 2: Jalankan, pastikan dua tes `config_push` baru gagal** (`AttributeError`/`ValueError` karena field belum ada): `cd backend && .venv/bin/pytest tests/test_config_push.py tests/test_go2rtc.py -q`. Tes `test_go2rtc` baru lulus.

- [ ] **Step 3: Implementasi.** `config.py`: `go2rtc_rtsp_url: str = "rtsp://localhost:8554"` dengan komentar satu baris (alamat RTSP go2rtc yang dipakai vision node `server`; tidak dikirim ke browser). `config_push.py:84`: `source_url = f"{settings.go2rtc_rtsp_url.rstrip('/')}/cam_{cam.id}"`.

- [ ] **Step 4: Jalankan tes** (perintah Step 2) → semua lulus. Lalu suite penuh `.venv/bin/pytest tests -q -m "not gpu"` → baseline + 3 `passed`, 0 gagal.

- [ ] **Step 5: Commit**
```bash
git add backend/app/core/config.py backend/app/services/config_push.py backend/tests/test_config_push.py backend/tests/test_go2rtc.py
git commit -m "feat(config): go2rtc_rtsp_url — alamat RTSP node server tak lagi tertanam di kode"
```

### Task 2: Proxy Vite membaca `API_URL`

**Files:**
- Modify: `frontend/vite.config.ts:11`

**Interfaces:**
- Produces: env `API_URL` (target proxy `/api`, default `http://localhost:8000`). Dipakai Task 3 (`isentinel-web.service`).

- [ ] **Step 1: Implementasi.** Ganti target proxy menjadi `process.env.API_URL || 'http://localhost:8000'` (`||` agar nilai kosong jatuh ke default; `@types/node` sudah ada di `tsconfig.node.json`). Tambahkan satu baris komentar: server memakai `API_URL=http://localhost:7701`.

- [ ] **Step 2: Verifikasi proxy** (tidak ada tes unit; ini konfigurasi). Dari `frontend/`, pastikan tidak ada API lokal di `:8000`:
  1. `python3 -m http.server 7701 --bind 127.0.0.1 &` (API tiruan) lalu `API_URL=http://localhost:7701 npx vite --port 5199 --strictPort &`; `curl -s -o /dev/null -w '%{http_code}\n' localhost:5199/api/x` → `404` (dijawab server tiruan, proxy bekerja). Hentikan vite.
  2. Tanpa `API_URL`, dan dengan `API_URL=` (kosong): perintah curl yang sama → `500` (proxy menuju `:8000` yang kosong). Hentikan vite dan server tiruan.

- [ ] **Step 3: `npm run build` dan `npm run lint`** → build 0 error; lint tidak menambah peringatan dibanding baseline Step 0 Task 1.

- [ ] **Step 4: Commit**
```bash
git add frontend/vite.config.ts
git commit -m "feat(web): proxy dev Vite membaca target dari env API_URL"
```

### Task 3: Template, unit, dan teks contoh memakai blok 7700–7705

**Files:**
- Modify: `deploy/systemd/isentinel-api.service`, `deploy/systemd/isentinel-web.service`, `deploy/go2rtc/go2rtc.example.yaml`, `deploy/mosquitto/mosquitto.conf`, `deploy/vision.env.example`, `deploy/bootstrap.sh`, `.env.example`, `frontend/src/app/i18n.tsx` (kunci `notifications.appUrlHint`, dua bahasa), `backend/app/api/live.py` (docstring `camera_snapshot`), `docs/superpowers/specs/2026-10-01-port-nondefault-design.md` (koreksi 3.2)

**Interfaces:**
- Consumes: `GO2RTC_RTSP_URL` (Task 1), `API_URL` (Task 2).

- [ ] **Step 1: Ubah berkas** (nilai persis):
  - `isentinel-api.service`: `--port 7701`.
  - `isentinel-web.service`: tambah `Environment=API_URL=http://localhost:7701`; `ExecStart=/usr/bin/npm run dev -- --host 0.0.0.0 --port 7700 --strictPort`.
  - `go2rtc.example.yaml`: `api: { listen: ":7702", origin: "*" }`, `webrtc: { listen: ":7703" }`, `rtsp: { listen: "127.0.0.1:7705" }`; komentar yang menyebut `1984`/`5173` disesuaikan menjadi `7702`/`7700`.
  - `mosquitto.conf`: `listener 7704 0.0.0.0`.
  - `.env.example`: `MQTT_URL=localhost:7704`, `GO2RTC_URL=http://localhost:7702`, baris baru `GO2RTC_RTSP_URL=rtsp://127.0.0.1:7705` (komentar di baris sendiri di atasnya, bukan inline).
  - `vision.env.example`: `VISION_MQTT_URL=mqtt://localhost:7704`, `VISION_API_URL=http://localhost:7701`, `source_url` contoh `rtsp://127.0.0.1:7705/cam_2`; contoh di komentar broker memakai `:7704`.
  - `bootstrap.sh`: `curl -s localhost:7701/api/v1/health`.
  - `i18n.tsx`: contoh `http://192.168.2.133:5173` → `http://192.168.2.133:7700` (id dan en).
  - `live.py`: ganti paragraf docstring yang menyebut "firewall server hanya membuka 8000/5173/1883" dengan: snapshot diambil dari sisi server agar same-origin dan di belakang `get_current_user`, karena go2rtc tidak punya autentikasi sendiri. Perilaku tidak berubah.
  - Spec 3.2: ganti `GO2RTC_RTSP_URL=rtsp://localhost:7705` dan contoh `source_url` ke `rtsp://127.0.0.1:7705`, tambahkan satu kalimat alasan (listener hanya `127.0.0.1`; `localhost` bisa me-resolve ke `::1`).

- [ ] **Step 2: Verifikasi.**
  - `grep -n -E '\b(5173|8000|1984|8554|1883)\b' deploy/systemd deploy/go2rtc deploy/mosquitto deploy/bootstrap.sh deploy/vision.env.example .env.example` → tidak ada baris (`deploy/loadtest/` tidak termasuk; ia memakai env override).
  - `grep -n -E '^(GO2RTC_RTSP_URL|MQTT_URL|GO2RTC_URL)=.*#' .env.example` → kosong (tanpa komentar inline).
  - `cd frontend && npx vitest run` → jumlah lulus = baseline, 0 gagal. `cd ../backend && .venv/bin/pytest tests -q -m "not gpu"` → sama dengan akhir Task 1.

- [ ] **Step 3: Commit**
```bash
git add deploy .env.example frontend/src/app/i18n.tsx backend/app/api/live.py docs/superpowers/specs/2026-10-01-port-nondefault-design.md
git commit -m "chore(deploy): template dan unit memakai blok port 7700-7705"
```

### Task 4: Dokumen

**Files:**
- Modify: `README.md`, `ARCHITECTURE.md`, `docs/RUNBOOK.md`, `docs/DEVELOPMENT.md`, `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: Perbarui dokumen** dengan keputusan berikut:
  - Semua dokumen: peta `7700–7705` adalah **referensi repo dan instalasi baru**; server dev `gspe-ai3` masih memakai port lama (`5173/8000/1984/8554/1883`) sampai cutover Docker (`docs/superpowers/specs/2026-10-01-docker-deploy-design.md`). Perintah operasional untuk `gspe-ai3` di RUNBOOK/DEVELOPMENT **tidak diubah** agar tetap benar.
  - `README.md`: diagram arsitektur dan butir "Port terbuka di LAN" memakai peta baru; koreksi klaim lama: go2rtc `7702`/`7703` terbuka ke LAN (Live Wall memutar langsung dari browser; terbukti `1984` terjangkau dari LAN 2026-10-01), RTSP `7705` hanya localhost; tambahkan catatan status server dev.
  - `ARCHITECTURE.md`: diagram dan tabel komponen memakai port baru; catatan yang sama.
  - `docs/RUNBOOK.md` §1: tambahkan tabel "Peta port" (enam baris, kolom: port, fungsi, akses LAN/localhost) dan catatan status server dev; tabel unit dan perintah yang ada tidak diubah.
  - `docs/DEVELOPMENT.md`: satu catatan di bagian server: blok `7700–7705` berlaku setelah cutover Docker.
  - `ROADMAP.md`: baris baru `PN` mengikuti format baris `PE`: status `[~] repo selesai; tanpa deploy — cutover lewat Docker (spec docker-deploy)`, bukti (angka backend/frontend/lint dari Task 1–3), rentang commit; di Fase E tambahkan satu butir: node edge memakai `VISION_MQTT_URL=<host>:7704`.
  - `CHANGELOG.md`: satu entri baru di atas, mengikuti format entri yang ada (Konteks, Diubah, Uji, Evidence dengan keluaran nyata dari Step 0/Task 1–3, Dampak: tidak ada perubahan server, Rollback: `git revert` rentang commit).

- [ ] **Step 2: Verifikasi.** `grep -n -E '5173|:8000' README.md ARCHITECTURE.md` → hanya baris catatan "server dev masih port lama"; keluaran suite penuh (pytest, vitest, build, lint) ditempel di entri CHANGELOG; semua angka di ROADMAP cocok dengan CHANGELOG.

- [ ] **Step 3: Commit**
```bash
git add README.md ARCHITECTURE.md docs/RUNBOOK.md docs/DEVELOPMENT.md ROADMAP.md CHANGELOG.md
git commit -m "docs: peta port 7700-7705 (README, ARCHITECTURE, RUNBOOK, ROADMAP, CHANGELOG)"
```

---

## Self-review (spec coverage)

| Spec | Task |
|---|---|
| 3.1 peta port | Task 3 (template), Task 4 (dokumen) |
| 3.2 kode: `go2rtc_rtsp_url`, `config_push`, `API_URL` | Task 1, Task 2 |
| 3.2 deploy/template, i18n, docstring `live.py` | Task 3 |
| 3.2 dokumen, Fase E | Task 4 |
| 3.3 tidak ada deploy | Global Constraints |
| 3.4 rollback `git revert` | Task 4 (CHANGELOG) |
| 3.5 uji `config_push`, `/live`, build/lint, Vite lokal | Task 1, Task 2 |
