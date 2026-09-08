# I-Sentinel — Roadmap & Checkpoint

> Diperbarui di SETIAP fase selesai: status marker + bukti (hasil command/angka) +
> commit range. Marker: `[x]` selesai+terbukti · `[~]` berjalan · `[ ]` belum · `[!]` gagal/blocked.
> Detail per fase: `docs/plans/` · Spesifikasi: `docs/plans/2026-09-08-isentinel-design.md`

## Ringkasan Status

| Fase | Nama | Status | Selesai | Bukti utama | Commit |
|---|---|---|---|---|---|
| 0 | Skeleton (auth, kamera+probe, UI shell) | [~] berjalan | — | — | — |
| 1 | Vision inti (deteksi+tracking, live view) | [ ] | — | — | — |
| 2 | Zona + events + clips + web inbox | [ ] | — | — | — |
| 3 | Loitering + running + Telegram + rate-limit | [ ] | — | — | — |
| 4 | Absensi wajah (enrollment, gate, shift) | [ ] | — | — | — |
| 5 | Hardening (retensi, beban 30+ kamera, docs) | [ ] | — | — | — |
| E | Edge Jetson Orin Nano | [ ] | — | — | — |

## Fase 0 — Skeleton

Plan: `docs/plans/01-fase-0-skeleton.md`

**Kriteria selesai (dari plan):**
- [ ] Login + bootstrap admin jalan
- [ ] Tambah kamera via wizard → probe menemukan MAIN & SUB → tersimpan & tampil
- [ ] `pytest backend/tests -m "not gpu"` hijau (Windows) dan hijau penuh (server)
- [ ] `vitest run` + `npm run build` hijau
- [ ] Bring-up di gspe-ai3: `/api/v1/health` ok, login dari browser sukses, alembic idempotent

**Bukti:** (diisi saat selesai — output command, angka, tanggal)

**Catatan keputusan/temuan fase ini:** —

---

## Fase 1 — Vision Inti

Plan: `docs/plans/02-fase-1-vision-inti.md` (brief → dikembangkan menjadi plan detail sebelum mulai)

**Kriteria selesai:**
- [ ] Event deteksi person dari 1 kamera nyata masuk DB < 2 s
- [ ] Heartbeat node tampil di dashboard
- [ ] 4 kamera: FPS inferensi ≥ target, GPU tercatat
- [ ] Live view WebRTC 4 tile, latency < 1 s

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
