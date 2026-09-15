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
| 5 | Hardening (retensi, beban 30+ kamera, docs) | [ ] | — | — | — |
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
- UI: Attendance (tile summary, badge TELAT 429 MNT, Import/Export), Enrollment (badge 3 Foto + galeri), Gate Absensi (list kamera + arah) — screenshot

**Catatan keputusan/temuan fase ini:**
- Face tetap di server; vision hanya crop upper-body + upload (edge-friendly)
- Crop gate WAJIB dari mainstream (temuan bring-up: substream terlalu kecil untuk wajah)
- Demo "orang berjalan masuk gate secara fisik" belum: membutuhkan orang menghadap kamera gate — rantai dibuktikan via event crop nyata dari snapshot kamera (pipeline identik)
- InsightFace CPU fallback cukup untuk gate frekuensi rendah; GPU libs = gap yang diketahui

---

## Fase 5 — Hardening

Plan: `docs/plans/06-fase-5-hardening.md`

**Kriteria selesai:**
- [ ] Soak 24 jam 32 stream sintetis: GPU/RSS plateau, tanpa leak
- [ ] Cleanup retensi 30 hari terbukti (file + DB)
- [ ] Docs operasional selesai

**Bukti:** —

---

## Fase E — Edge Jetson (opsional/nanti)

Plan: `docs/plans/07-edge-jetson.md`

**Kriteria selesai:**
- [ ] Kamera di Orin Nano → event identik masuk sistem
- [ ] Store-and-forward terbukti (LAN putus 5 menit → event tetap masuk, tanpa duplikat)

**Bukti:** —
