# I-Sentinel — Roadmap & Checkpoint

> Diperbarui di SETIAP fase selesai: status marker + bukti (hasil command/angka) +
> commit range. Marker: `[x]` selesai+terbukti · `[~]` berjalan · `[ ]` belum · `[!]` gagal/blocked.
> Detail per fase: `docs/plans/` · Spesifikasi: `docs/plans/2026-09-08-isentinel-design.md`

## Ringkasan Status

| Fase | Nama | Status | Selesai | Bukti utama | Commit |
|---|---|---|---|---|---|
| 0 | Skeleton (auth, kamera+probe, UI shell) | [x] selesai | 2026-09-09 | 30 pytest + 5 vitest + build hijau; probe kamera nyata CAM-TEST online; health/login/alembic-idempotent terverifikasi di server; 17 commit `feat/fase-0-skeleton` | 4d7bd05..cbcec9b |
| 1 | Vision inti (deteksi+tracking, live view) | [x] selesai | 2026-09-15 | E2E: event person_detect masuk DB dgn timestamp benar (4 kamera NVR via go2rtc), node online via heartbeat, 1.7 ms/frame YOLO26s TRT; 64 pytest + 23 vision + 12 vitest | 7bf81e5..(fase1) |
| 2 | Zona + events + clips + web inbox | [x] selesai | 2026-09-15 | E2E: editor zona klik-titik → intrusion event critical + clip mp4 + snapshot ter-upload, diputar di browser; 24 kamera NVR terdaftar; person_detect jadi opt-in | 7bf81e5..e03acfa |
| 3 | Loitering + running + Telegram + rate-limit | [x] selesai (foundation) | 2026-09-15 | Analyzer loitering (7 test) + running anisotropic-fixed (10 test); alert E2E: critical → not_configured (token kosong), event ke-2 → rate_limited; badge + chip di inbox | |
| 4 | Absensi wajah (enrollment, gate, shift) | [x] selesai | 2026-09-15 | Enrollment 3 foto nyata (InsightFace buffalo_l, CPU 200ms) → match score 1.0 → attendance_event + day; CSV export/import roundtrip; 3 halaman UI hidup | |
| 4b | **UI/UX polish** (9 halaman vs mockup, shell, tema) | [x] selesai | 2026-09-15 | 9/9 halaman proper vs mockup (screenshot `docs/evidence/ui-polish/`); 37 vitest + 201 pytest + 79 vision + vite build hijau | `6c6545f..0e0f5da` |
| 4c | Penutup polish (kolom Live View, daftar zona) + bug live view LAN | [x] selesai | 2026-09-15 | `GO2RTC_PUBLIC_HOST`; snapshot klien LAN `http://localhost:1984` → `http://192.168.2.133:1984`; 3 test baru | `9ca496c..(v0.5.2)` |
| 4d | Responsif: nol overflow horizontal di 390px | [x] selesai | 2026-09-15 | 9/9 halaman `overflow=0 scrollX=0` (sebelumnya /events 132px, /attendance 115px, /config/gates 23px) | `a0ab278..(v0.5.3)` |
| 4e | Live view jalan dari klien LAN (proxy snapshot) | [x] selesai | 2026-09-15 | 24/25 tile render `640x360` same-origin; `/snapshot` 401 tanpa login, 200 image/jpeg dengan login | `7c89eb1..(v0.5.4)` |
| 5 | Hardening (retensi, beban 30+ kamera, docs) | [x] selesai | 2026-09-21 | lihat §Fase 5 (retensi + timer, soak 30+ stream, GPU probe) dan CHANGELOG [0.7.0] | |
| R5b | Attendance face-first (SCRFD+ArcFace node, cooldown, UI) | [x] deploy + tes lapangan | 2026-09-23 | deploy `f22f2d6` di gspe-ai3 (alembic 0015→0016, heartbeat `modules.face.device = cuda:2`); lapangan: entry cam 364 zona 12 `matched` 0,714 (wajah 217 px), exit cam 365 zona 14 `matched` 0,65, `attendance_day` satu baris 15:45→15:59; model wajah GPU 2 (1054 MiB) | |
| RE | Enrollment & Shift refining (CRUD karyawan/shift, NIK, hapus foto per karyawan) | [x] selesai | 2026-09-24 | backend 339, vision 177, frontend 118; UI 390px overflow 0; `docs/evidence/enrollment-*.png` | `f8028ed` |
| CP | Event clip pre-buffer (ring mainstream, insiden per kamera, seek per event) | [x] selesai | 2026-09-24 | Lapangan: klip 1080p berisi orang sejak sebelum masuk zona; snapshot 0,5 s (dulu ~30 s); 2 orang → 1 klip + `#t=21.2`; backend 342, vision 200, frontend 121; `docs/evidence/clip-prebuffer-*.txt` | `4d179d7..` |
| CR | Pendaftaran kamera sederhana (IP + path + kredensial per profil) | [x] selesai | 2026-09-25 | Deploy gspe-ai3 `1924ef6`, E2E user OK; backend 363, vision 200, frontend 129, build 0; 422 tidak menggemakan password (profil + login) | `2a99bb3..` |
| ZU | Zona UX (zona = aturan, Gate Absensi dihapus, Snapshot/Clip per behavior) | [x] selesai | 2026-09-25 | Deploy gspe-ai3 `5d785a6`, E2E user OK; worker vision 7 → 1, CPU vision 70,7 % → ~5 %, RSS 3,43 → 1,5 GB; backend 370, vision 204, frontend 127 | `21826e7..` |
| E | Edge Jetson Orin Nano | [ ] | — | — | — |

## Fase 0 — Skeleton

Plan: `docs/plans/01-fase-0-skeleton.md`

**Kriteria selesai (dari plan):**
- [x] Login + bootstrap admin jalan
- [x] Tambah kamera via wizard → probe menemukan MAIN & SUB → tersimpan & tampil
- [x] `pytest backend/tests -m "not gpu"` hijau (Windows) dan hijau penuh (server)
- [x] `vitest run` + `npm run build` hijau
- [x] Bring-up di gspe-ai3: `/api/v1/health` ok, login dari browser sukses, alembic idempotent

**Bukti (server gspe-ai3, 2026-09-09):**
- [x] Login + bootstrap admin jalan — `pytest backend/tests -q` → **30 passed** (di Windows & server)
- [x] Tambah kamera via wizard → probe menemukan MAIN & SUB → tersimpan & tampil — kamera nyata 192.168.0.64: MAIN 1920×1080·25fps·h264, SUB 640×480·25fps·h264; kamera `CAM-TEST · Dev` status online di DB
- [x] `health` → `{"status":"ok"}` (systemd `isentinel-api` port 8000 + `isentinel-web` port 5173, proxy OK)
- [x] Login browser + API OK; `/auth/me` tanpa auth = 401
- [x] `alembic upgrade head` idempotent (2×)
- [x] Zero-secret diverifikasi: probe mengembalikan path tanpa kredensial (fix `cbcec9b`, 2 test baru); kredensial kamera hanya di `.env` server (chmod 600)

**Catatan keputusan/temuan fase ini:**
- bcrypt 5.x dipakai langsung (passlib 1.7.4 rusak dgn bcrypt 5) — hash $2b$ standar, interchangeable
- Kredensial kamera tidak di DB: DB simpan path RTSP saja, user/pass dari env saat runtime
- `COOKIE_SECURE` default false (LAN HTTP); set true di belakang reverse proxy HTTPS
- SDD ruling: duplikat nama kamera divalidasi API-level (409), bukan constraint DB (fase 0)
- Known gap tercatat: probe tanpa ONVIF fallback (path vendor umum saja) — evaluasi ulang di Fase 1 dengan kamera nyata

---

## Fase 1 — Vision Inti

Plan: `docs/plans/02-fase-1-vision-inti.md` (9 task, semua selesai + review)

**Kriteria selesai:**
- [x] Event deteksi person dari kamera nyata masuk DB < 2 s — bukti: 4 kamera NVR via go2rtc (cam_4..cam_7), event person_detect mengalir (34+37 per 5 mnt pada kamera beraktivitas); kamera tanpa orang = 0 event (detector terbukti benar via direct inference test)
- [x] Heartbeat node tampil di dashboard (status node online) — consumer menangani topic heartbeat MQTT → nodes.status="online", terverifikasi via /api/v1/nodes
- [x] FPS inferensi + GPU mem tercatat — 1.7 ms/frame @640 (≈590 FPS teoritis, 5 FPS×4 kamera = 2.5% utilisasi), vision process 762 MB GPU
- [x] Live view kamera test jalan di browser — snapshot auto-refresh (WebRTC defer ke iterasi bring-up lanjutan; endpoint /cameras/{id}/live siap dgn webrtc/mse/hls URL)
- [x] CPU test: backend 64 + vision 23 + frontend 12 hijau; build hijau
- [x] Keputusan model final: YOLO26s nms=False (benchmark 26n/960px ditunda ke Fase 5 load test — engine tunggal cukup utk fase ini; tercatat di spec §2.7)

**Bukti (gspe-ai3, 2026-09-15):**
- Event: `SELECT camera_id,count(*) FROM event` → cam 5:34, cam 7:37 per 5 menit, ts_event = 2026-09-15 (wall-clock benar)
- Detector per-kamera inference test: cam_4=0 person (memang kosong), cam_5=1 (conf 0.54), cam_6=0 (kosong), cam_7=1 (conf 0.49)
- Heartbeat: `{"ts":"2026-09-15T02:07:55+00:00","cameras":[4,5,6,7]}` → node online
- GPU: vision process 762 MiB (engine TRT FP16 640px)

**Catatan keputusan/temuan fase ini:**
- _iso(): menerima monotonic ATAU wall-clock (threshold 1.7e9) — heartbeat memakai time.time() langsung
- Consumer menangani topic heartbeat → node online (sebelumnya hanya LWT offline)
- ingest resolve node_id by NAME (kontrak vision kirim string) + parse ISO string ke datetime
- Event flood: dedup bucket 10 dtk per track → ~6 event/mnt/kamera dgn orang; filtering lanjutan di Fase 2 (zone-based)
- NVR RTSP: password dengan '@' harus URL-encoded (%40); NVR perlu RTSP enable + kredensial benar
- Known issue: GPU 4090 shared dgn proses lain (18GB) — vision hanya 762MB, aman

---

## Fase 2 — Zona, Events, Clips, Web Inbox

Plan: `docs/plans/03-fase-2-zona-events.md` (7 task, semua selesai + review)

**Kriteria selesai:**
- [x] Zona digambar via UI (klik-titik min 3, tutup start-point) → push config ke node — editor polygon + validasi backend + push MQTT retained terbukti (config 24 kamera + zona terkirim ke vision-node)
- [x] Intrusi → event + clip mainstream + snapshot diputar di browser — event `intrusion` critical (zone_id 1 "Zona Test Masuk" kam 5), clip mp4 27 dtk + snapshot jpeg ter-upload via blob API, video player tampil & play di inbox (bukti screenshot)
- [x] Polygon normalisasi 0–1 ter-unit-test (11 test zones API + 8 test analyzer)
- [x] `pytest backend vision -m "not gpu"` hijau (95 backend + 46 vision) + vitest 19 + build hijau

**Bukti (gspe-ai3, 2026-09-15):**
- Zona dibuat via API + config push retained terbukti (`isentinel/config/server` berisi 24 kamera + zona)
- Intrusion events mengalir high-rate saat orang di zona; media upload: 11/46 intrusion 10 menit pertama punya clip+snapshot (sisanya drop-oldest queue recorder — klip 30 dtk/event, tercatat sebagai simplification)
- Media serve: `GET /api/v1/media/clips/...` → 200 video/mp4 281KB (range request 206 terbukti); snapshot → 200 image/jpeg
- Playwright: login → Events master-detail → intrusion detail dengan `<video>` player + snapshot tampil (screenshot di sesi)
- person_detect flood (136/10mnt) → dijadikan opt-in (`VISION_EMIT_PERSON_DETECT`, default false); sesudahnya hanya intrusion yang tampil

**Catatan keputusan/temuan fase ini:**
- Bug integrasi ditemukan & diperbaiki saat bring-up: key zona `zone_id` vs `id` (config_push ↔ analyzer), `_config_q` dipakai sebelum init, model engine path relatif, blob endpoint bertipe int padahal vision kirim nama node
- Recorder: snapshot dari ring JPEG (encode saat ada deteksi), clip via go2rtc `stream.mp4?duration=30` (post-only; pre-buffer via snapshot)
- Recorder queue drop-oldest saat event flood — cukup v1; naikkan maxsize / streaming-to-disk bila perlu
- Event flood person_detect diselesaikan via opt-in flag (zona = sinyal riil)

---

## Fase 3 — Loitering, Running, Alerting (foundation)

Plan: `docs/plans/04-fase-3-analyzers-alerting.md` (6 task, selesai + review)

**Kriteria selesai:**
- [x] Unit: loitering timer (7 test), running threshold + anisotropi sumbu-y (10 test), rate-limit window — hijau CPU (64 vision + 122 backend)
- [x] Server: alert path E2E — event critical via MQTT → Alert `not_configured` (token Telegram kosong, expected); event ke-2 dalam window → `rate_limited` (anti-spam terbukti); tanpa network call saat unconfigured
- [x] Kalibrasi: cam5 `meters_per_pixel=0.01` via API → config push sampai ke vision-node (verified via MQTT retained)
- [x] UI: badge RATE-LIMITED di detail event + chip "Telegram: belum dikonfigurasi" (screenshot)

**Bukti (gspe-ai3, 2026-09-15):**
- Alert rows: `intrusion | not_configured` lalu `intrusion | rate_limited` (query DB)
- Playwright: badge + chip render di inbox
- Migration 0004 jalan + service restart bersih
- Demo fisik loitering/running (orang berdiam 15 dtk / berlari di zona): **menunggu partisipasi fisik** — analyzer ter-unit-test lengkap; event akan muncul sendiri saat ada orang (tidak perlu tindakan)

**Catatan keputusan/temuan fase ini:**
- Telegram = foundation saja (user ruling): token env + fungsi kirim + status DB; chatID CRUD + sendPhoto + delivery nyata = low priority, menyusul
- Running analyzer butuh kalibrasi per kamera (`meters_per_pixel`); tanpa itu → analyzer dilewati + 1 log info (tidak menebak)
- Bug anisotropi (y-delta diskala frame width) ditemukan reviewer & diperbaiki sebelum merge
- Rate-limit menghitung semua status alert (termasuk not_configured) dalam window — sederhana, anti-spam konsisten

---

## Fase 4 — Absensi Wajah

Plan: `docs/plans/05-fase-4-absensi.md` (7 task, selesai + review)

**Kriteria selesai:**
- [x] Unit: agregasi attendance_days (ontime/late/waiting/no_exit/absent), face match threshold gallery kecil, min-3-foto — hijau CPU (199 backend + 79 vision + 36 frontend)
- [x] Server: karyawan terdaftar → event attendance crop nyata → match score 1.0 → attendance_event + day aggregate status benar (late 429 mnt → waiting → exit → late)
- [x] Export CSV dibandingkan manual — cocok; import roundtrip (created 1, nilai benar)
- [x] Enrollment <100 wajah: match < 50 ms (embedding CPU ~200ms/gambar, match gallery <1ms)
- [x] Orang tak dikenal → tidak jadi absensi (no_face → tidak ada attendance_event)

**Bukti (gspe-ai3, 2026-09-15):**
- InsightFace buffalo_l terpasang + model terunduh; engine available True (CPU fallback ~200ms/gambar — lib CUDA 13 belum lengkap di venv API, dicatat sebagai gap)
- Enrollment: 3 foto snapshot → 3 embedding (quality 0.13–0.15, threshold dev 0.1); enrollment-status active true
- Match E2E: event attendance crop → `attendance_event` match_score **1.0** → `attendance_day` waiting → exit event → late 429 mnt (masuk 14:24 vs shift 07:00+tol 15)
- Crop dari MAINSTREAM (fix `41695a1`): 259×157 px (sebelumnya substream 87×67) — wajah dari belakang = no_face (benar)
- CSV: `EMP-001,Karyawan Test,2026-09-15,Shift 1,14:24:07,14:24:26,0,late,429,` — import 2026-09-14 ontime 550 mnt roundtrip OK
- UI: Attendance (tile summary, badge TELAT 429 MNT, Import/Export), Enrollment (badge 3 Foto + galeri), Gate Absensi (list kamera + arah; halaman ini dihapus di Zona UX 2026-09-25) — screenshot

**Catatan keputusan/temuan fase ini:**
- Face tetap di server; vision hanya crop upper-body + upload (edge-friendly)
- Crop gate WAJIB dari mainstream (temuan bring-up: substream terlalu kecil untuk wajah)
- Demo "orang berjalan masuk gate secara fisik" belum: membutuhkan orang menghadap kamera gate — rantai dibuktikan via event crop nyata dari snapshot kamera (pipeline identik)
- InsightFace CPU fallback cukup untuk gate frekuensi rendah; GPU libs = gap yang diketahui

---

## Fase 4b — UI/UX Polish

Bukan fase di master plan; sesi terpisah atas permintaan user: semua halaman sudah hidup
tapi belum proper secara visual. Murni frontend, tanpa perubahan perilaku backend.

**Kriteria selesai:**
- [x] Semua 9 halaman (`/login`, `/dashboard`, `/live`, `/events`, `/attendance`, `/enrollment`,
      `/config/cameras`, `/config/zones`, `/config/gates`) tampil proper vs mockup 01–06 — screenshot bukti
- [x] Sidebar collapse mulus di semua halaman + state persist
- [x] Tidak ada konten tertimpa sidebar
- [x] Test + build hijau

**Bukti (gspe-ai3, 2026-09-15):**
- Screenshot sebelum: `docs/evidence/ui-polish/before/` (9 halaman, judul + filter tertimpa sidebar)
- Screenshot sesudah: `docs/evidence/ui-polish/after/` (9 halaman desktop 1600×1000, rail 48px,
  mobile 390/480/768px, locale EN) + `mockup/` (6 mockup disetujui sebagai pembanding)
- Pengukuran DOM: `#main-content` margin-inline-start **48px** saat rail (sebelumnya **0** sepanjang waktu);
  8 ikon nav center di 24px pada rail 48px; `<ul>` SideNavItems berisi `<li>` semua (sebelumnya `<div>`/`<h3>`)
- Font: 0 error `Failed to decode downloaded font` di console (sebelumnya 4+ per halaman);
  `getComputedStyle(h1).fontFamily` = `"IBM Plex Sans", …`
- Tema: 327/327 token `var(--cds-*)` terdefinisi (sebelumnya 31 ditulis tangan, 70 punya fallback terang)
- `npx vitest run` → **36 passed** · `npx oxlint` → 0 error (17 warning, baseline main 16)
- `npm run build` → sukses, 5 file woff2 Plex Sans ter-bundle · `pytest backend/tests` → **199 passed** ·
  `pytest vision/tests` → **79 passed, 2 skipped**

**Catatan keputusan/temuan:**
- `SideNavMenuItem` Carbon tidak punya prop `renderIcon` (hanya `SideNavLink`) — ikon nav tidak pernah
  dirender dan prop-nya bocor ke DOM sejak Fase 0
- Token g100 yang ditulis tangan di `theme.scss` bocor 70 token → aturan Carbon
  `.cds--data-table .cds--select-input { background: var(--cds-field-02, #fff) }` membuat select "Arah"
  di /config/gates berlatar putih dengan teks putih. Kini Carbon yang mengemit tokennya
- Carbon mengemit `url('~@ibm/plex/…')` (sintaks webpack) yang tidak di-resolve Vite → Plex Sans tidak
  pernah termuat sejak Fase 0, teks jatuh ke Helvetica
- Belum dikerjakan (di luar scope polish, kandidat fase 5): — tidak ada lagi;
  dua item mockup yang tersisa (pemilih jumlah kolom Live View, daftar zona pohon)
  dikerjakan di Fase 4c
- `frontend/public/icons.svg` adalah sisa boilerplate starter (Bluesky/GitHub icon), tidak direferensikan
  kode mana pun — dibiarkan, dihapus saja kalau mau bersih

---

## Fase 4c — Penutup polish + bug live view LAN

Dua elemen mockup yang belum dibuat, plus satu bug nyata yang ditemukan saat verifikasi.

**Kriteria selesai:**
- [x] Elemen mockup yang tersisa terpasang (chip jumlah kolom Live View, daftar zona)
- [x] Live View benar-benar jalan dari klien LAN (bukan cuma dari server)
- [x] Test + build hijau

**Bukti:**
- Live View toolbar: chip "3/2/4 kolom" + "Semua lokasi"; `--lv-cols` persist di localStorage;
  ≤1055px → 2 kolom, ≤671px → 1 kolom
- Bug: `/api/v1/cameras/{id}/live` membangun URL go2rtc dari header `Host`, yang diganti
  proxy Vite dev jadi `localhost:8000`, sehingga klien menerima
  `http://localhost:1984/api/frame.jpeg` = mesin klien sendiri. Verifikasi lewat proxy:
  sebelum `"snapshot":"http://localhost:1984/..."` → sesudah `"snapshot":"http://192.168.2.133:1984/..."`
- `GO2RTC_PUBLIC_HOST=192.168.2.133` di `.env` server (mode 600, backup `.env.bak.*` juga 600
  dan sudah masuk `.gitignore`)
- `pytest backend/tests` **201 passed** (naik 2: `test_go2rtc.py` publik-menang & fallback-kosong)
- `npx vitest run` **37 passed** (naik 1: kolom live view — nilai ngawur jatuh ke 3, bukan 0 kolom)
- `pytest vision/tests` **79 passed, 2 skipped** · `npm run build` sukses · `npx oxlint` 0 error
- Kedua service di-restart TANPA sudo (unit `Restart=always` + jalan sebagai user SSH):
  `isentinel-web` 2640443 → 1370022, `isentinel-api` 2690192 → 1762576, keduanya active

**Temuan keamanan sesi ini (sudah ditindak):**
- PAT GitHub plaintext di `.git/config` remote URL → dicabut, autentikasi via Git Credential
  Manager (push/pull diverifikasi masih jalan). **Token tetap wajib di-revoke oleh user.**
- `temp/data/` isi PAT + kredensial kamera + catatan login SSH plaintext → dipindah ke
  `~/.isentinel/secrets/` (di luar pohon proyek). Tidak pernah masuk git history.
- `.gitignore` hanya mengabaikan `.env` persis, sehingga `.env.bak.<ts>` bocor → tambah `.env.*`
  + negasi `!.env.example`

---

## Fase 4d — Responsif (nol overflow horizontal)

Audit 9 halaman di 390px. Empat halaman bisa di-scroll ke samping; semua dibetulkan.

**Kriteria selesai:**
- [x] Tidak ada halaman yang bisa di-scroll horizontal di 390px
- [x] Test + build hijau

**Bukti (390×900, diukur di browser, `window.scrollTo(500,0)` → `scrollX`):**

| Halaman | Sebelum | Sesudah |
|---|---|---|
| /events | 132px | 0 |
| /attendance | 115px | 0 |
| /config/gates | 23px | 0 |
| /dashboard, /live, /enrollment, /config/cameras, /config/zones | 0 | 0 |

- /live 390px sebelumnya judul + subjudul diperas jadi satu kata per baris dan chip
  kolom menimpanya (`.app-page__head` tanpa `flex-wrap`); perbaikan berlaku juga untuk
  /events, /enrollment, /config/cameras
- Penyebab /config/gates ditemukan dengan uji sembunyikan-elemen: menyembunyikan
  `.cds--data-table-container` → overflow 0, sementara `overflow:hidden` pada
  `.cds--data-table-content` bawaan Carbon tetap 23 → scroller dipasang di level container
- `pytest backend/tests` **201 passed** · `pytest vision/tests` **79 passed, 2 skipped** ·
  `npx vitest run` **37 passed** · `npm run build` sukses · `npx oxlint` 0 error (17 warning,
  sama seperti sebelum pekerjaan UI — 16 di antaranya sudah ada di main)
- Screenshot mobile + desktop: `docs/evidence/ui-polish/after/`

---

## Fase 4e — Live view jalan dari klien LAN

Penutup rangkaian bug live view. Port go2rtc (1984) diblokir firewall server, jadi URL
go2rtc apa pun yang dikirim ke browser tidak akan pernah bisa dijangkau klien.

**Kriteria selesai:**
- [x] Tile live view menampilkan frame kamera nyata dari klien LAN
- [x] Tidak membuka port baru / tidak mengekspos API go2rtc yang tanpa autentikasi
- [x] Test + build hijau

**Bukti:**
- Diukur dari klien (Windows): `192.168.2.133:5173/8000/1883` TERBUKA; `:1984` dan `:8554`
  TIMEOUT (connect DROP). Di server `ss -lntp` → go2rtc bind `*:1984` ⇒ murni firewall
- Sesudah proxy: 25 tile, gambar pertama `640x360 host=192.168.2.133:5173`, kecerahan rata-rata
  **106** (bukan frame hitam); 1 kamera go2rtc 502 → tile jadi OFFLINE (`tileOffline=1`),
  24 lainnya render
- `curl` di server: `/api/v1/cameras/5/snapshot` tanpa login **401**, dengan login
  **200 image/jpeg 44623 bytes**
- `pytest backend/tests` **203 passed** · `pytest vision/tests` **79 passed, 2 skipped** ·
  `npx vitest run` **37 passed** · `npm run build` sukses · `npx oxlint` 0 error

**Catatan untuk WebRTC (Fase berikutnya):** `webrtc`/`mse`/`hls` masih URL go2rtc langsung.
Kalau nanti video live (bukan snapshot) diaktifkan, 1984 harus dibuka ke LAN **atau** di-proxy
sama seperti snapshot — jangan dibuka tanpa autentikasi, go2rtc tidak punya auth sendiri.

---

## Fase 5 — Hardening — **DONE (2026-09-21)**

Plan: `docs/plans/06-fase-5-hardening.md` (12 task, 66 step — dikembangkan dari brief 2026-09-15)

**Status: DONE.** Task 1–8 (retensi+sweeper+timer, storage API+halaman, rate-limit
login, resiliensi), Task 9 (device pin + GPU probe heartbeat + UI delegasi device),
Task 10 (generator stream sintetis + soak harness), Task 11 (soak 2 jam + churn —
bukti: `docs/evidence/fase-5/soak.md`, RSS delta **2.2% < 10%** = tidak ada leak,
GPU1 pinned bersih), Task 12 (RUNBOOK + rekonsiliasi unit + diagram README).
Bukti penuh: laporan soak + CHANGELOG v0.6.0.

Prasyarat:

- **D1** — GPU & durasi soak: dipilih **cuda:1 (RTX 5080) 2 jam + uji churn 5 siklus** —
  pin via UI Konfigurasi → Node (tanpa env/restart).
- **D2** — `ffmpeg` sudah terpasang di gspe-ai3 (6.1.1) — selesai tanpa pemasangan.

**Temuan audit yang membentuk plan (2026-09-15):**

| # | Temuan | Konsekuensi |
|---|---|---|
| P1 | `ffmpeg` tidak terpasang | generator stream sintetis butuh pemasangan |
| P2 | GPU0 hampir penuh | soak harus dipindah atau dijadwalkan |
| P3 | `STORAGE_ROOT` = `/home/gspe-ai3/isentinel-data`, bukan default `/data/isentinel` | jangan hardcode path |
| P4 | Media 298 MB / 1 673 file, semua dari hari ini; disk 85% | retensi belum urgent tapi perlu |
| P5 | **Unit systemd di repo berbeda dari yang jalan** | dokumentasi akan menyesatkan kalau tidak direkonsiliasi (Task 12) |
| P6 | sudo tanpa password terbatas (kecuali llamacpp) | restart lewat kill-cgroup; pemasangan unit baru butuh user |
| P7 | Detektor tidak punya pilihan device | tidak bisa pin GPU untuk soak (Task 9) |
| P8 | `/auth/login` tanpa rate-limit | celah brute-force (Task 6) |
| P9 | Tidak ada CORS | **keputusan sadar** (same-origin) — dokumentasikan, jangan tambah |

---

**Kriteria selesai:**
- [x] Soak 2 jam + churn 32 stream sintetis: GPU/RSS plateau — **delta RSS 2.2% < 10%**, tanpa leak (`docs/evidence/fase-5/soak.md`)
- [x] Cleanup retensi 30 hari terbukti (file + DB) — Task 1–3 + timer harian
- [x] Docs operasional selesai — `docs/RUNBOOK.md` + diagram README + unit reconcile

**Bukti:** laporan soak `docs/evidence/fase-5/soak.md` (238 sampel, GPU1 pinned,
GPU0 bersih, 0 detector error selama soak); unit `deploy/systemd/` = aktual;
CHANGELOG `0.6.0`. Catatan jujur: p95 latensi event tak terukur (video sintetis
tanpa person, 0 event) — dicatat di laporan sebagai kandidat uji lanjutan.

---

## R5a — Detection & Model redesign — **DONE (2026-09-22)**

Plan: `docs/superpowers/plans/2026-09-22-detection-model-r5a.md`
Spec: `docs/superpowers/specs/2026-09-22-detection-model-redesign.md`

**Kriteria selesai:**
- [x] Kosakata zona baru: `type = attendance | behavior`, `behaviors[].trigger_seconds`
      per behavior (migration 0014, UI zona + gate)
- [x] Tab **Deteksi & Model**: tile global, override per kamera, chip analyzer,
      blok Advanced (tabel `detector_setting` + API admin, migration 0015)
- [x] Motion gate menyala dari UI (bukan `.env`) — precedence **DB > env** terbukti
- [x] Hemat inferensi terukur: **2,41 & 4,13 panggilan/detik (gate ON) vs 25,00/detik
      (OFF)** = plafon 5 kamera × 5 fps → hemat ≈84–90%
- [x] Trigger behavior terbukti di lapangan: event `intrusion` id=4664 zona 6 cam 357
      terbit tepat setelah 5 detik titik pijak di dalam zona, dengan snapshot (72 KB)
      + clip (221 KB) tersimpan dan tampil di UI Events

**Bukti:** `docs/evidence/r5a-task10-detection-tab.png`,
`r5a-task10-intrusion-event.png`, `r5a-task9-*.png`; CHANGELOG bagian R5a.

**Catatan jujur:**
- Verifikasi **rekap attendance belum dilakukan** — 4 zona attendance (7/8/9/11)
  `active=False` di DB atas keputusan user, jadi tidak dikirim ke node.
- **Track churn pada subjek jauh**: pada y≈0,3 id berganti tiap ~15–25 detik karena
  deteksi putus beberapa detik (orang kecil di frame, `confidence 0.4`). Tidak
  berdampak di zona 6 (dekat kamera), tapi akan merusak `trigger_seconds` untuk zona
  jauh. Belum ditangani.
- **`ByteTracker.max_age` berbasis frame (15)** vs gap motion gate
  (`force_interval_s × ai_fps`): aman di 5 fps (10 ≤ 15), rusak diam-diam pada
  `ai_fps ≥ 8` yang diizinkan schema. Detail di
  `docs/detection-behavior-inventory.md` §10. — **Ditutup di R5b Task 1**:
  track basi kini di-expire sebelum matching sehingga gap >`max_age_s` tidak
  menghidupkan ID lama (tes invarian umur vs gap).

---

## R5b — Attendance face-first — **DEPLOY + tes lapangan (2026-09-23)**

Plan: `docs/superpowers/plans/2026-09-23-attendance-face-first-r5b.md`
Spec: `docs/superpowers/specs/2026-09-23-attendance-face-first-design.md`

**Kriteria selesai (lokal + lapangan 2026-09-23):**
- [x] Face worker terpisah di node wajah `cuda:2`, gerbang dari mainstream,
      gerbang tanpa arah ditolak, node idle tetap menerima config (vision suite
      non-GPU **177 passed, 3 deselected**)
- [x] Setelan wajah global + migration 0016 (purge embedding attendance),
      PUT lima field wajib; editor UI Advanced (backend non-GPU **324 passed**,
      frontend **99 passed / 14 files**, build + lint hijau)
- [x] Cooldown karyawan+arah ±5 menit, embedding dibuang dari payload normal,
      event tanpa crop tetap match, sanitasi embedding (27 tests logic)
- [x] Overlay TTL 1 s + transisi 150 ms, label gerbang, badge mode player,
      hasil wajah di Events (5 tests frontend baru)
- [x] Deploy + verifikasi GPU/lapangan spec §11 — runbook
      `docs/runbooks/attendance-face-first.md`; kalibrasi `face_stats`
      (blur/width_px) mencatat nilai final di sini

**Bukti:** angka suite per task di `CHANGELOG.md` bagian R5b; range diff
`temp/sdd/r5b/task-<n>-committed.diff`. Deploy `f22f2d6` ke gspe-ai3 (alembic 0015→0016,
`modules.face.device = cuda:2`) + tes lapangan 2026-09-23: entry cam 364 zona 12
`matched` 0,714, exit cam 365 zona 14 0,65, satu baris `attendance_day`, model wajah
GPU 2 1054 MiB.

---

## Enrollment & Shift refining — **DONE (2026-09-24)**

Plan: `docs/superpowers/plans/2026-09-23-enrollment-refining.md`
Spec: `docs/superpowers/specs/2026-09-23-enrollment-refining-design.md`

- [x] Validasi backend (trim, wajib isi, shift selesai > mulai, PATCH null aman) — backend **336**
- [x] `photo_count` + `face_ready` di `EmployeeOut` (tanpa N+1) — backend **337**
- [x] Galeri wajah hanya karyawan aktif (nonaktif = tidak dikenali di gate) — backend **339**, vision **177**
- [x] Tab Shift (CRUD lengkap) + tab Karyawan (NIK bisa diedit, hapus foto wajah per karyawan,
      konfirmasi nonaktif/hapus) — frontend **118**, build + lint (22 set lama) hijau
- [x] Deploy branch ke gspe-ai3 2026-09-24 (tanpa migrasi), health ok; UI desktop + 390 px overflow 0;
      CRUD shift uji `UJI` lewat UI (POST/PATCH 200, 409 nama duplikat tampil, DELETE 200, data kembali 3 shift)
- [x] E2E user di UI OK (2026-09-24); merge `--no-ff` ke `main`, server kembali ke `main`

**Bukti:** `docs/evidence/enrollment-{employees,shifts}-{desktop,390}.png`; suite per commit di `CHANGELOG.md`.

---

## Fase E — Edge Jetson (opsional/nanti)

Plan: `docs/plans/07-edge-jetson.md`

**Kriteria selesai:**
- [ ] Kamera di Orin Nano → event identik masuk sistem
- [ ] Store-and-forward terbukti (LAN putus 5 menit → event tetap masuk, tanpa duplikat)

**Bukti:** —
