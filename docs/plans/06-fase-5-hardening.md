# Milestone Brief — Fase 5: Hardening & Load Test

> Brief. Dikembangkan menjadi plan detail setelah Fase 4 selesai.

**Goal:** Sistem stabil untuk produksi: retensi 30 hari otomatis, 30+ kamera sintetis stabil di 4090, dokumentasi operasional. Bukti: 32 stream sintetis 24 jam (atau 2 jam + uji churn) → GPU < 90%, tanpa memory leak, cleanup terbukti menghapus file kadaluarsa.

**Prasyarat:** Fase 4 done.

## Scope

1. **Retensi service**: harian 03:00 — hapus file > RETENTION_DAYS dari clips/snapshots/crops, tandai event expired; halaman Retensi & Storage (path, bar estimasi disk) sesuai mockup 06.
2. **Load test**: generator stream sintetis (ffmpeg loop video pengujian → RTSP ke go2rtc, 32 kamera, dengan "orang" bergerak di video) → 24 jam soak + 1 jam spike (tambah 8 stream); metrik: GPU util/mem, latensi event end-to-end, RSS proses, drop frame.
3. **Resiliensi**: restart API/vision saat jalan (systemd), kill -9 vision → LWT → node offline di dashboard → auto-reconnect + queue flush; kamera mati → status offline + event system.
4. **Dokumentasi**: README operasional (start/stop, backup DB, add camera playbook, troubleshooting), diagram arsitektur final, runbook alert.
5. **Keamanan pass**: rotasi JWT secret, cek CORS, rate-limit endpoint auth (attempt limit), audit override absensi.

## Kriteria bukti

- [ ] Soak 24 jam: graph GPU/RSS stabil (tampak naik lalu plateau).
- [ ] Cleanup: file uji kadaluarsa terhapus, DB entry expired, tidak ada file orphans (checker).
- [ ] 32 kamera: p95 latensi event < 3 s; live view 8 tile tetap jalan.
- [ ] Docs selesai; demo soak dilaporkan.

## Risiko

- 4K substream aneh (ada kamera sub 1080p) → biaya decode naik; mitigasi: cap decode ke 720p (scale oleh go2rtc) bila CPU decode jadi bottleneck.
- ffmpeg generator RAM → spawn per-stream dengan resource limit, jalan di layanan terpisah.
