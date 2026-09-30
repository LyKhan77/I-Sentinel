# Runbook — Monitoring Resource S1

Halaman **System › Monitoring** (`/monitoring`) dan endpoint `GET /api/v1/monitoring`
menampilkan kesehatan **saat ini** (tanpa riwayat — grafik tren menyusul di S2).

- Sumber data: heartbeat vision tiap 10 detik → `node.hw` / `node.modules` (JSON, tanpa migrasi).
- Halaman & endpoint membaca DB + go2rtc; cek layanan di-cache 10 detik. Semua user login boleh membuka.
- Status keseluruhan = terburuk dari kamera + node + layanan; layanan `unknown` (mis. Telegram belum
  dikonfigurasi) tidak dihitung.

## Kode masalah

### Kamera (`issues`)

| Kode | Arti | Langkah |
|---|---|---|
| `node_offline` (kritis) | Kamera terhubung ke node yang sedang offline | Lihat bagian Node di bawah |
| `not_running` (kritis) | Kamera punya zona aktif ber-behavior, node mengirim heartbeat, tetapi kamera ini tidak ada di daftar worker | Cek model wajah (zona absensi butuh face loaded) dan log vision; jalankan sync konfigurasi ke node (Konfigurasi → Kamera → simpan). Kamera **tanpa zona aktif** tidak dianalisis (live view saja) dan tampil "Tanpa zona aktif", bukan masalah. |
| `no_frames` (kritis) | Sumber AI `reconnecting`/`stalled` atau frame terakhir > 30 s | Cek NVR/kamera dan stream go2rtc (`/api/streams`); cek log vision `journalctl -u isentinel-vision` |
| `low_fps` (peringatan) | fps aktual < 80% target, bukan saat `starting` | Cek beban GPU/CPU node, bitrate/kualitas substream, atau NVR yang membatasi fps |
| `reconnects` (peringatan) | ≥ 3 reconnect sumber dalam 1 jam | Cek kestabilan jaringan/NVR dan kredensial stream |
| `stream_missing` (peringatan) | `cam_<id>` tidak terdaftar di go2rtc | Konfigurasi → Kamera → **Sync go2rtc** |
| `no_data` (peringatan) | Node belum mengirim statistik kamera (vision versi lama) | Deploy/restart `isentinel-vision` versi ini |

Kamera dengan `ai = null` berarti tidak punya node (tidak dianalisis): hanya `stream_missing` yang diperiksa.
Kamera nonaktif ditandai `disabled` dan dihitung terpisah dari ringkasan.

### Node

| Kode | Arti | Langkah |
|---|---|---|
| `offline` (kritis) | LWT MQTT diterima atau heartbeat terakhir > 35 s | `systemctl status isentinel-vision` + `journalctl -u isentinel-vision`; cek koneksi broker MQTT; cek GPU/driver |
| `heartbeat_late` (peringatan) | Heartbeat terakhir 20–35 s (belum offline) | Jaringan/broker lambat atau proses vision tersendat; pantau — bila > 35 s berubah `offline` |
| `gpu_hot` (peringatan) | Suhu GPU ≥ 85 °C | Cek pendinginan/airflow; turunkan beban (jumlah kamera aktif) |
| `vram_high` (peringatan) | VRAM ≥ 90% | Kecilkan `imgsz`/batch atau kurangi kamera aktif |
| `ram_high` / `cpu_high` (peringatan) | RAM/CPU host ≥ 90% | Cek proses lain di host node |
| `mqtt_backlog` (peringatan) | Antrean store-and-forward node > 0 | Cek broker MQTT dan jaringan node→API; event akan terkirim saat pulih |

### Layanan (di halaman Monitoring)

| Layanan | Kritis bila | Catatan |
|---|---|---|
| Database | `SELECT 1` gagal | Cek Postgres; endpoint tetap 200 dengan `detail` jenis error |
| go2rtc | `/api/streams` tidak terjawab | Live view & sumber vision ikut terdampak |
| Broker MQTT | Consumer API terputus dari broker | Cek `journalctl -u isentinel-api` |
| Sweep retensi | > 26 jam sejak `retention_last_sweep` atau belum pernah | Cek timer retensi |
| Telegram | Status alert terakhir `failed` | Cek token/grup di Konfigurasi → Notifikasi (token tidak pernah tampil di log) |
| Disk | Pemakaian ≥ ambang disk alert | Sama dengan pengaturan Retensi & Storage |

## Node offline ↔ pulih

- Transisi status hanya lewat `app/services/node_health.py`; satu event `system` + satu Telegram per perpindahan
  (`online → offline`: severity `warning`, `reason: lwt|timeout`; `offline → online`: severity `info`,
  `reason: online`). `unknown → online` tidak membuat event.
- Banner persisten muncul di AppShell dan mode TV selama node offline; hilang saat node online.
- **LWT retained**: broker menyimpan pesan terakhir per topik. Vision mempublikasikan `{"status":"online"}`
  retained qos 1 setiap kali connect sehingga retained `offline` lama tidak lagi membuat event palsu saat API
  restart; backend mengabaikan payload LWT non-offline (dan payload kosong).
- Bila node sengaja dimatikan (maintenance): matikan juga via LWT/stop rapi — setelah 35 detik status menjadi
  `offline` dengan `reason: timeout` dan Telegram terkirim (sekali saja).

## Operasi

- Restart monitor menempel pada lifespan API; tidak ada unit terpisah, tidak ada migrasi DB.
- Uji cepat: `curl -s -b <cookie> localhost:8000/api/v1/monitoring | head -c 400`.
- Rollback: `git revert` rentang commit S1 + build frontend + restart vision & API; field JSON tambahan pada
  `node.hw`/`node.modules` diabaikan kode lama (tanpa migrasi).
