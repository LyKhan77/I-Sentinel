# I-Sentinel — Roadmap & Checkpoint

> Diperbarui di SETIAP fase selesai: status marker + bukti (hasil command/angka) +
> commit range. Marker: `[x]` selesai+terbukti · `[~]` berjalan · `[ ]` belum · `[!]` gagal/blocked.
> Detail per fase: `docs/plans/` · Spesifikasi: `docs/plans/2026-09-08-isentinel-design.md`

## Ringkasan Status

| Fase | Nama | Status | Selesai | Bukti utama | Commit |
|---|---|---|---|---|---|
| 0 | Skeleton (auth, kamera+probe, UI shell) | [x] selesai | 2026-09-09 | 30 pytest + 5 vitest + build hijau; probe kamera nyata CAM-TEST online; health/login/alembic-idempotent terverifikasi di server; 17 commit `feat/fase-0-skeleton` | 4d7bd05..cbcec9b |
| 1 | Vision inti (deteksi+tracking, live view) | [ ] | — | — | — |
| 2 | Zona + events + clips + web inbox | [ ] | — | — | — |
| 3 | Loitering + running + Telegram + rate-limit | [ ] | — | — | — |
| 4 | Absensi wajah (enrollment, gate, shift) | [ ] | — | — | — |
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

Plan: `docs/plans/02-fase-1-vision-inti.md` (plan detail 9 task, siap eksekusi)

**Kriteria selesai (dari plan detail — disesuaikan realita: kamera nyata tersedia 1):**
- [ ] Event deteksi person dari kamera nyata 192.168.0.64 masuk DB < 2 s
- [ ] Heartbeat node tampil di dashboard (status node online)
- [ ] FPS inferensi + GPU mem tercatat (log vision-node, YOLO26s e2e @640)
- [ ] Live view WebRTC kamera test jalan di browser (latency < 1 s)
- [ ] CPU test: backend + vision suite hijau; vitest + build hijau
- [ ] (Bench tambahan) benchmark 26n vs 26s e2e-vs-default @ 640/960 tercatat → keputusan model final

**Bukti:** —

---

## Fase 2 — Zona, Events, Clips, Web Inbox

Plan: `docs/plans/03-fase-2-zona-events.md`

**Kriteria selesai:**
- [ ] Zona digambar via UI (klik-titik min 3, tutup start-point) → push config ke node
- [ ] Intrusi → event + clip mainstream + snapshot diputar di browser
- [ ] Polygon normalisasi 0–1 ter-unit-test

**Bukti:** —

---

## Fase 3 — Loitering, Running, Alerting

Plan: `docs/plans/04-fase-3-analyzers-alerting.md`

**Kriteria selesai:**
- [ ] Demo 3 jenis event → Telegram terima snapshot; rate-limit terbukti
- [ ] Loitering/running/rate-limit ter-unit-test (CPU)

**Bukti:** —

---

## Fase 4 — Absensi Wajah

Plan: `docs/plans/05-fase-4-absensi.md`

**Kriteria selesai:**
- [ ] Siklus penuh: enrollment (min 3 foto) → gate entry/exit → rekap status benar
- [ ] Export CSV cocok dengan rekap; import roundtrip
- [ ] Face match < 50 ms pada gallery < 100

**Bukti:** —

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
