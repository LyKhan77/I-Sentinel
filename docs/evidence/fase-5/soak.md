# Soak Test Fase 5 — 32 Stream Sintetis + Churn

Tanggal: 2026-09-18 16:43–18:45 (±119 menit) · Host: gspe-ai3
Perangkat: 32 stream ffmpeg file (testsrc2 640×360 @15 FPS, 2 jam) → go2rtc →
vision-node (YOLO26s TensorRT, pin **cuda:1** via config push) · 32 kamera
`SYNTH-01..32` · churn 3 siklus penuh remove+add 32.

## Ringkasan metrik (CSV, sampler 30 s — 238 sampel)

| Metrik | Nilai | Kriteria | Status |
|---|---|---|---|
| vision RSS 30m pertama (avg) | 3 235 MB | — | — |
| vision RSS 30m terakhir (avg) | 3 306 MB | delta < 10% | **delta 2.2% — LULUS** |
| vision RSS range | 2 956–3 307 MB | plateau, bukan naik monoton | **LULUS** |
| API RSS range | 128–155 MB | stabil | **LULUS** |
| GPU1 (cuda:1, pinned) util | avg 26.7%, max 100% | terpakai, stabil | LULUS |
| GPU1 mem | avg 1 719 MB (puncak 4 147 saat churn) | tak lepas kontrol | LULUS |
| GPU0 (4090, project lain) | 19 194–19 894 MB | vision tidak menambah | **pin bersih** |
| Detector error selama soak | 0 (journal 18 Sep) | 0 | **LULUS** |
| Node status | `online` + heartbeat `cuda:1` penuh durasi | — | LULUS |

Tren RSS per ~30 m: 2 956 → 3 268 → 3 286 → 3 298 → 3 302 → 3 304 → 3 306 → 3 307 MB
(naik cepat di warmup awal, lalu flat — pola plateau yang diharapkan).

Tren mem GPU1: 3 943 → 4 147 (churn rebuild) → 2 930 → 3 885 → **294 MB** pada
fase akhir — lihat "yang tidak tercapai".

## Churn

4 siklus remove+add 32 kamera (3 penuh sukses + 1 restart churn). Setiap siklus
memicu config push → rebuild worker (4 ↔ 36) tanpa downtime node.

## p95 latensi event

**Tidak terukur** — `events_total` = 0 sepanjang soak: video `testsrc2` tidak
memuat orang, sehingga `person_detect` tidak pernah terbentuk (per desain Task 10:
beban decode/deteksi tetap penuh). Bukti latensi event memerlukan video dengan
orang bergerak — dicatat sebagai kandidat lanjutan, bukan blocker Fase 5.

## Yang tidak tercapai / catatan jujur

1. **Fase ~20 menit terakhir**: GPU1 util 0% + mem turun 4 100 → 294 MB —
   producer/worker synth berhenti setelah churn terakhir. Tidak mempengaruhi
   validitas data plateau RSS (fase stabil sudah 100+ menit), tapi mengurangi
   durasi efektif deteksi aktif ±100 menit.
2. **0 event** — p95 latensi tidak terukur (video sintetis tanpa person).
3. **Post-soak (21 Sep 08:00)**: engine `yolo26s.engine` (dibangun 10 Sep untuk
   compute 12.0/5080) mulai gagal dimuat oleh runtime saat ini
   (`expecting compute 12.0 got 8.9`) — error muncul pada config push pertama
   setelah soak, bukan selama soak. Tindak lanjut: rebuild engine per-device
   (engine tidak lintas-device) + fail-fast load di detector.

## Rollback/ulang

Harness: `deploy/loadtest/{make-streams,soak,soak-churn}.sh` + `register-cams.py`
(semua di main). CSV mentah: server `~/isentinel-data/loadtest/soak.csv`.
