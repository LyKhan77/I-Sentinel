# Milestone Brief — Fase 3: Loitering, Running, Alerting Telegram

> Brief. Dikembangkan menjadi plan detail setelah Fase 2 selesai.

**Goal:** Analyzer loitering + running aktif; alert terkirim ke Telegram dengan snapshot + rate-limit anti-spam; web inbox menampilkan status Telegram per event. Bukti: demo loitering 30 s → Telegram dapat pesan (foto + teks), event duplikat dalam window rate-limit tidak spam.

**Prasyarat:** Fase 2 done (zona, clip, inbox).

## Scope

1. **Analyzer loitering** (`loitering.py`): track diam di zona > N detik (velocity < ε) → event; watch lanjut; event ulang hanya setelah keluar-masuk lagi. Parameter durasi per zona.
2. **Analyzer running** (`running.py`): kecepatan track (m/s, skala pixel→meter per kamera via garis referensi di config zona/kamera) > threshold di zona aktif → event. Kalibrasi per kamera disimpan di camera config (`meters_per_pixel_est` + titik referensi).
3. **Alerting service** (`services/alerting.py`): consume event → rate-limit (key kamera+zone+tipe, window per zona, default dari settings) → kirim Telegram (text + snapshot) ke chat aktif → simpan status `alert` (sent/failed/rate_limited); retry 3× backoff.
4. **Telegram UI** (tab Notifikasi sesuai mockup): chat target CRUD, uji kirim, token dari env (tidak di DB).
5. **Events inbox** tambah: badge TELEGRAM TERKIRIM/RATE-LIMITED, filter severity.

## Kriteria bukti

- [ ] Unit: loitering timer, running threshold, rate-limit window (freeze time) — hijau CPU.
- [ ] Server: demo 3 jenis event → Telegram diterima dengan snapshot; rate-limit terbukti di log + tabel alert.
- [ ] Kecepatan running dalam m/s masuk akal pada kamera terkalibrasi (±30%).

## Risiko

- Kecepatan m/s dari pixel butuh kalibrasi — knob per kamera (jangan auto-kalibrasi; YAGNI).
- Telegram flood/error → retry + status di DB; tanpa queue permanen (fire-and-forget sesuai requirement).
