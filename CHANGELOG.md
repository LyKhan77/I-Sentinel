# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/) ringkas — satu baris per commit.
Skema versi: [SemVer](https://semver.org/). Status proyek: pra-rilis (`0.x`).

## [0.2.0] — 2026-09-15 · Fase 1: Vision Inti

Pipeline vision end-to-end: YOLO26s TensorRT (nms=False) + ByteTrack → MQTT → DB → dashboard/live/events. Terverifikasi 4 kamera NVR via go2rtc di server GPU.

### Commits (ringkas)

- `728de79`/`0449061` feat: event model, ingest idempotent, events API + ws hub
- `3454791` feat: mqtt events consumer (events + node lwt)
- `1098d86` feat: go2rtc stream sync + live url endpoint
- `9d5746e` feat: vision pipeline stages (source, detector iface, byte tracker)
- `b09c6cc`/`d3c5e7d` feat: vision node runner (mqtt transport, disk queue, graceful)
- `0d60702` feat: yolo26s tensorrt export script + gpu smoke test
- `cef8afa` feat: internal heartbeat ingest + node staleness + vision deploy files
- `3dced18` feat: dashboard tiles, live view (snapshot), events live list
- `f25c664` fix: g100 dark theme via css custom properties
- `ea892ee`/`e5a8302` fix: ts_event wall-clock (monotonic offset)
- `1bdb19b`/`9c25396`/`17f3d10` fix: ingest node-by-name + iso parsing + relationship
- `2a65d4c` feat: consumer marks node online from heartbeat topic

### Highlights

- **vision/** paket terpisah (tanpa FastAPI): pipeline source→detector→tracker→emit, DiskQueue store-and-forward, LWT+heartbeat MQTT
- **YOLO26s TRT FP16 nms=False**: 1.7 ms/frame di 4090, 762 MB GPU
- **Backend**: consumer MQTT (events/heartbeat/LWT), idempotent ingest, WS broadcast, go2rtc sync
- **Frontend**: dashboard tile hidup, live view snapshot grid (fokus+fullscreen), events list realtime

## [0.5.3] — 2026-09-15 · Responsif: nol overflow horizontal di 390px

Audit 9 halaman di viewport 390px menemukan 4 halaman bisa di-scroll ke samping.
Semua diperbaiki; sekarang 9/9 `docOverflow=0`, termasuk `window.scrollX` setelah
`scrollTo(500,0)` — bukan cuma angka `scrollWidth`.

| Halaman | Sebelum | Sesudah | Penyebab |
|---|---|---|---|
| /events | 132px | **0** | 3 dropdown filter tidak wrap; `<dl>` detail memakai grid `auto 1fr` dengan UUID tanpa titik putus; grid master-detail menyusutkan panel detail ke ~30px tapi isinya (thumbnail 72px, `<video>`) punya `min-width:auto` |
| /attendance | 115px | **0** | baris tab + tombol Import/Export tidak wrap |
| /config/gates | 23px | **0** | overflow tabel tembus ke halaman walau `.cds--data-table-content` sudah `overflow-x:auto` |
| /live | 0 (tapi chip menimpa judul) | **0** | `.app-page__head` flex tanpa wrap, anak pertama `flex:1` boleh menyusut sampai 0 |
| 4 lainnya | 0 | 0 | — |

### Perbaikan

- `a0ab278` fix(ui): `.app-page__head` `flex-wrap` + basis 280px — aksi turun ke baris
  sendiri di layar sempit, tidak menimpa judul. Kena /live, /events, /enrollment, /config/cameras
- `f30dfa9` fix(ui): filter /events wrap (basis 200px / maks 240px) + baris tab /attendance wrap
- `ce081ee` fix(ui): `overflow-wrap:anywhere` pada `<dl>` detail event — min-content kolom
  `1fr` jadi satu karakter, tidak lagi selebar UUID
- `15505a4` fix(ui): scroller di `.cds--data-table-container` — diverifikasi dengan uji
  sembunyikan-elemen di browser (menyembunyikan container → overflow 0; menambah
  `overflow:hidden` di wrapper dalam tetap 23)
- `2e5abf4` fix(ui): `/events` ditumpuk satu kolom di bawah 900px; desktop tetap master-detail

### Bukti

- Pengukuran per halaman di 390px: `/dashboard /live /events /attendance /enrollment
  /config/cameras /config/zones /config/gates` → semua `overflow=0 scrollX=0`
- Screenshot mobile + desktop: `docs/evidence/ui-polish/after/`
- `pytest backend/tests` **201 passed** · `pytest vision/tests` **79 passed, 2 skipped**
- `npx vitest run` **37 passed** · `npm run build` sukses · `npx oxlint` 0 error

## [0.5.2] — 2026-09-15 · Penutup polish + bug live view LAN

Menutup dua elemen mockup yang belum dikerjakan, plus satu bug nyata yang
membuat Live View mati untuk semua klien LAN.

### Perbaikan

- `fd42e31` fix(backend): host go2rtc untuk browser tidak lagi diturunkan dari header
  `Host`. Proxy Vite dev mengirim `Host: localhost:8000` ke API → klien menerima
  `http://localhost:1984/api/frame.jpeg`, yaitu mesin klien sendiri. Live View mati
  total di luar server. Setting baru `GO2RTC_PUBLIC_HOST` (kosong = perilaku lama).
  Fix `9fcfbee` sebelumnya mengganti host ke host request, tapi sumbernya sudah rusak.
- `4413a7e` chore(.gitignore): `.env` tidak mengabaikan `.env.bak.*` / `.env.local`

### Fitur (elemen mockup yang tersisa)

- `9ca496c` feat(ui): Live View — chip "3/2/4 kolom" + filter "Semua lokasi" (mockup 02),
  pilihan kolom persist; dipaksa turun di layar sempit (≤1055px → 2, ≤671px → 1).
  Grid disamakan mockup: gap 1px di atas `#393939` + border luar.
- `9ca496c` feat(ui): /config/zones — daftar zona di bawah editor dengan swatch tipe,
  badge tipe + AKTIF/NONAKTIF, klik baris = pilih zona (mockup 06).

### Bukti

- `curl` lewat proxy Vite (jalur browser) sebelum/sesudah:
  `"snapshot":"http://localhost:1984/..."` → `"snapshot":"http://192.168.2.133:1984/..."`
- `pytest backend/tests` **201 passed** · `pytest vision/tests` **79 passed, 2 skipped**
- `npx vitest run` **37 passed** · `npm run build` sukses · `npx oxlint` 0 error
- Screenshot Live View (toolbar kolom + grid 3 kolom): `docs/evidence/ui-polish/after/`

### Keamanan (temuan sesi ini, sudah ditindak)

- PAT GitHub tersimpan plaintext di `.git/config` (remote URL) → sudah dicabut dari URL;
  autentikasi lewat Git Credential Manager. **Token-nya sendiri masih perlu di-revoke user.**
- `temp/data/` (gitignored, tidak pernah masuk history) berisi PAT, kredensial kamera uji,
  dan catatan login SSH plaintext → dipindahkan ke `~/.isentinel/secrets/` di luar pohon proyek.
- Tidak ada rahasia di file ter-track maupun di git history (diverifikasi `git grep` +
  `git log -S`). `.env` server mode 600.

## [0.5.1] — 2026-09-15 · UI/UX Polish

Semua 9 halaman dibuat proper terhadap mockup 01–06. Murni frontend — tidak ada perubahan
perilaku backend. Tiga bug fondasi yang sejak Fase 0 membuat tiap halaman salah tampil
diperbaiki di akarnya (offset konten, token tema, pemuatan font).

### Perbaikan

- `6c6545f` fix(ui): konten tertimpa sidebar fixed di semua halaman; sidebar rail collapse 48px
  (ikon saja, tanpa hover-expand, persist localStorage); markup `<ul>` valid; IBM Plex Sans akhirnya
  termuat; layout halaman diseragamkan (`.app-page`)
- `f9b4f9e` fix(ui): token g100 di-emit Carbon, bukan 31 token tulis-tangan — select "Arah" di
  /config/gates tidak lagi berlatar putih dengan teks putih
- `e2fe1d2` fix(ui): state no-signal untuk tile live view (ikon + OFFLINE + timestamp + badge
  LIVE/OFFLINE) dan fallback snapshot editor zona (tidak ada lagi ikon gambar rusak)
- `40b9548` fix(ui): brand header tidak lagi pecah dua baris di viewport < 480px
- `b5df1c9` fix(ui): /events, /live, /dashboard menampilkan error saat request gagal, bukan empty
  state yang menyesatkan; CamerasPage disamakan memakai `lowContrast`

### Bukti

- Screenshot sebelum/sesudah 9 halaman + rail/mobile/EN: `docs/evidence/ui-polish/`
- `npx vitest run` 36 passed · `npm run build` sukses · `pytest backend/tests` 199 passed ·
  `pytest vision/tests` 79 passed, 2 skipped · `npx oxlint` 0 error

## [Unreleased]

- `9fcfbee` fix: live endpoint rewrites go2rtc host to request host
- `3ec0d3a` feat: zone editor (click-to-draw polygon) + events master-detail inbox
- feat: loitering analyzer (dwell per zone)
- feat: running analyzer (calibrated m/s)
- feat: alert model + zone analyzer params + camera calibration
- feat: alerting service (rate-limit, telegram foundation)
- feat: alerts api + inbox badge + telegram status chip
- fix: ws guard drops alert frames by kind
- feat: attendance + enrollment + gates UI (AttendancePage tabs/summary/override, EnrollmentPage face gallery+shifts, GatesPage absensi zones + conflict; api/attendance.ts + api/employees.ts)
- fix: api client keeps FormData content-type (multipart CSV import + face upload)
- feat: gate crop from mainstream frame (face resolution) — `Recorder.fetch_frame` fetches `/api/frame.jpeg?src=cam_N_main`, `CameraWorker._attach_crop` crops attendance face from the full-res main stream with substream fallback

## [0.1.0] — 2026-09-10 · Fase 0: Skeleton

Backend, frontend, dan infrastruktur dasar I-Sentinel: auth, kamera + probe RTSP, UI shell Carbon dark, deploy configs. Terverifikasi end-to-end di server dev (login → wizard probe kamera nyata → kamera online).

### Commits

- `14e1294` chore: gitignore tensorrt engine artifacts
- `6e7a885` docs: sinkronkan checklist fase 0 + revisi kriteria fase 1
- `b72b592` docs: fase 1 detail plan (9 task)
- `12c8eca` docs: detektor dipilih YOLO26s nms=False (benchmark task tetap di fase 1)
- `d315f4e` docs: fase 0 selesai - bukti bring-up server
- `cbcec9b` fix: probe returns path without credentials (zero-secret)
- `94b95c9` fix: explicit setuptools packages (flat-layout ambiguity app+alembic)
- `1bd50bb` docs: fase 0 progress checkpoint di roadmap
- `8b7ebf4` fix: final review wave (logout endpoint, probe persistence, nav route, cookie_secure, jwt guard)
- `7af1f41` fix: alembic run path in bootstrap + soft env file in unit
- `c4a2e95` chore: deploy configs (go2rtc, mosquitto, systemd) + bootstrap script
- `05d3750` feat: cameras page with probe wizard
- `3699c88` fix: logout redirect, route-aware placeholder, api client opt merge
- `6a97216` feat: frontend scaffold (carbon g100, i18n id/en, app shell, login)
- `53e10e9` feat: rtsp probe service (ffprobe + vendor path candidates)
- `866bc87` feat: nodes + cameras CRUD API
- `35fb4e9` fix: user API validation (password length, role enum) + bootstrap cleanup
- `d7157a0` feat: auth API + user management + first-run admin bootstrap
- `27602c0` feat: password hashing + JWT auth helpers
- `51bf9f5` feat: fase0 models (user, node, camera, setting) + initial migration
- `8d87aa6` feat: backend core (settings, db, alembic, health endpoint)
- `f39cddb` chore: monorepo scaffolding (backend, vision stub, frontend placeholder)
- `4d7bd05` docs: roadmap dengan checkpoint per fase
- `1540e91` docs: master plan + fase 0 detail plan + milestone briefs (fase 1-5, edge)
- `6e4e363` docs: specify face match threshold default
- `f493b95` docs: I-Sentinel design spec + approved UI mockups

### Highlights

- **Backend**: FastAPI + SQLAlchemy 2 + Alembic; JWT httpOnly cookie auth, role admin/viewer; CRUD kamera/nodes; probe RTSP (ffprobe, path vendor Hikvision/Dahua/generic) dengan hasil persist; ingest event internal idempotent-ready.
- **Frontend**: React + TS + @carbon/react theme g100 dark, bilingual ID/EN, sidebar collapsible; login; halaman kamera + wizard probe; tanpa emoji (Carbon icons).
- **Deploy**: systemd units (api/web), go2rtc + mosquitto configs, bootstrap script; zero-secret (kredensial kamera via env, path RTSP saja di DB).
- **Keputusan model AI**: detektor YOLO26s TensorRT FP16 `nms=False` (spec §2.7); benchmark validasi di Fase 1.

## [0.3.0] — 2026-09-15 · Fase 2: Zona, Events, Clips, Web Inbox

Zona digambar di UI → vision-node eksekusi intrusion → event dengan clip mainstream + snapshot diputar di web inbox. 24 kamera NVR terdaftar.

### Commits (ringkas)

- `2bdaf71` feat: zone model + api (polygon validation, schedule)
- `88947ef` feat: mqtt config push (retained per node)
- `e41b8d5`/`c3bda0d` feat: intrusion analyzer + config apply (hot reload)
- `1fc3ed5`/`b20d138` feat: event recorder (clip via go2rtc mp4 + snapshot, blob upload)
- `d4b50c1` feat: blob storage + media streaming api + media topic consumer
- `9fcfbee` fix: live endpoint rewrites go2rtc host to request host
- `3ec0d3a`/`604afa8` feat: zone editor (click-to-draw polygon) + events master-detail inbox
- `0f979a0`/`75b75aa`/`3973e00` fix: config push zone key id, _config_q order, detector model path resolution
- `0a31dd8` fix: blob endpoint accepts node name (vision contract)
- `e03acfa` feat: person_detect events opt-in (debug), zones are the real signal

### Highlights

- **Zona**: model + editor polygon (klik-titik min 3, tutup start-point, drag handle, koordinat norm 0–1) + validasi absensi/direction
- **Config push MQTT retained** per node — hot-reload worker di vision tanpa restart
- **Intrusion analyzer** (ray-casting, jadwal, re-entry) + registry analyzer untuk fitur berikutnya
- **Recorder**: snapshot dari ring JPEG, clip mp4 via go2rtc, upload blob background + retry
- **Media API** auth + traversal guard + range request (video seek)
- **Web inbox** master-detail dengan player clip + snapshot + unduh

## [0.4.0] — 2026-09-15 · Fase 3: Loitering, Running, Alerting Foundation

Analyzer loitering + running (kalibrasi per kamera), alerting foundation: alert model, rate-limit, Telegram graceful-fail. Integrasi chatID menyusul (low priority).

### Commits (ringkas)

- `d0b6f16`/`18fae0f` feat: loitering analyzer (dwell per zone) + zone filter fix
- `9918933`/`8c6b163` feat: running analyzer (calibrated m/s) + anisotropic fix
- `dd9a72b` feat: alert model + zone analyzer params + camera calibration
- `cd353c9` feat: alerting service (rate-limit, telegram foundation)
- `2e05633`/`a69ad96` feat: alerts api + inbox badge + telegram status chip

### Highlights

- **LoiteringAnalyzer**: dwell akumulatif per track di polygon, reset saat keluar/hilang, gap >10s reset
- **RunningAnalyzer**: m/s via meters_per_pixel per kamera (xy anisotropik benar), EMA, cooldown 5s, skip tanpa kalibrasi
- **Alerting**: severity gate, toggle per zona, rate-limit window (camera:zone:type), retry 3×, status sent|failed|rate_limited|not_configured
- **Telegram**: sendMessage foundation, token env-only, tanpa token/chat → not_configured tanpa network call
- **UI**: badge status alert di event detail, chip status Telegram di inbox header

## [0.5.0] — 2026-09-15 · Fase 4: Absensi Wajah

Siklus absensi penuh: enrollment wajah → gate attendance → rekap dengan shift & status → export/import CSV. InsightFace buffalo_l di server, vision hanya crop.

### Commits (ringkas)

- `8acd420`/`c2aa341` feat+fix: attendance domain models (employee, shift, embedding, attendance) + FK guards + index parity
- `acd68e3` feat: face service (insightface wrapper, gallery, cosine match)
- `8892af4`/`092a6fb` feat+fix: face enrollment api (min 3 pose, pdp purge, gallery wiring) + upload cap
- `f3dc67a`/`1f4b1ec` feat+fix: face gate analyzer (crop + upload) + visit semantics
- `e2ef747`/`fe9dc99` feat+fix: attendance logic (match, aggregate, override, csv, close-days)
- `79532e2`/`ded189e` feat+fix: attendance + enrollment + gates UI + admin gating
- `41695a1` feat: gate crop from mainstream frame (face resolution)

### Highlights

- **Face pipeline server-side**: SCRFD+ArcFace, gallery <100 in-memory cosine, threshold knob; tanpa model → `not_configured` graceful
- **Enrollment**: upload image min 3 pose, quality gate, max 5; hapus biometrik per karyawan (PDP)
- **Attendance**: zona absensi + arah; agregasi harian ontime/late/waiting/no_exit/absent; close-days; override admin dengan catatan audit
- **CSV**: export (tanpa biometrik, anti-injection) + import upsert idempotent
- **Vision**: face_gate crop dari MAINSTREAM (resolusi wajah) + upload blob; error isolation

[Unreleased]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.3...HEAD
[0.5.3]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/LyKhan77/I-Sentinel/commits/v0.1.0
