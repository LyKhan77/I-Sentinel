# Runbook — Monitoring Resource S1–S3

Halaman **System › Monitoring** (`/monitoring`) menampilkan **Kondisi saat ini**,
**Tren** (riwayat 7 hari), dan **Aturan & alert** (aturan kesehatan; admin mengedit).

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
| `no_frames` (kritis) | Sumber AI `reconnecting`/`stalled` atau frame terakhir > ambang aturan `camera_no_frames` (default 30 s) | Cek NVR/kamera dan stream go2rtc (`/api/streams`); cek log vision `journalctl -u isentinel-vision` |
| `low_fps` (peringatan) | fps aktual < ambang aturan `camera_low_fps` (default 50 % target), bukan saat `starting` | Cek beban GPU/CPU node, bitrate/kualitas substream, atau NVR yang membatasi fps |
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

## Tab Tren (S2 — riwayat & grafik)

**Cara membaca grafik:**

- **fps kamera** = garis `aktual (min)` terhadap garis putus-putus **target** — fps diambil nilai
  **terendah** antar worker (detect/face) per menit, jadi fluktuasi ke bawah normal saat dua worker
  berjalan; fps di bawah target terus-menerus berarti sumber kamera atau GPU terlalu berat.
- **Umur frame** = maksimum `last_frame_age_s` antar worker; lonjakan sesekali wajar (keyframe/gangguan
  jaringan), nilai tinggi menetap = frame macet (cek tabel kamera di tab Kondisi saat ini).
- **Latensi inferensi**: `ms rata-rata` menunjukkan beban GPU rata-rata, `ms maks` menangkap lonjakan
  (mis. objek banyak). Naik terus di jam yang sama tiap hari = pertimbangkan penjadwalan ulang beban.
- **Arsir merah** = periode node **offline** (dari event `system` `reason: lwt|timeout`); **celah putus
  pada garis** = tidak ada sampel (node offline, atau API restart — bucket menit berjalan hilang, ≤ 1 menit).
- Rentang 24 jam digabung per 5 menit, 7 hari per 30 menit: nilai yang tampil adalah rata-rata/maks/min
  dari menit-menit di dalam bucket.

**Operasional:**

- Riwayat tersimpan **7 hari** di tabel `monitoring_sample` (±1.440 baris/node/hari); dipangkas tiap jam
  oleh `HistorySampler` (thread `monitoring-history`, interval 60 detik) — restart API aman.
- Cek isi tabel: `psql ... -c "SELECT count(*), min(ts), max(ts) FROM monitoring_sample;"` — bila kosong
  setelah ±2 menit API berjalan, cek apakah heartbeat vision diterima (`node.last_seen` bergerak) dan
  `journalctl -u isentinel-api | grep "monitoring history"`.
- Belum ada sampel sama sekali (baru deploy) → tab Tren menampilkan teks "Belum ada data riwayat …".
- API: `curl -s -b <cookie> "localhost:8000/api/v1/monitoring/history?range=6h" | head -c 400`.
- **Mode jendela** (dipakai panel Bukti event system): `…/monitoring/history?from=<iso>&to=<iso>&node_id=<id>`.
  Bucket tetap 60 dtk dan `range` di respons = `"custom"`, tanpa downsample. Batas maksimum 6 jam; jendela di luar
  retensi 7 hari mengembalikan seri kosong (bukan error). `range` **tidak boleh** digabung dengan `from`/`to`, `from`
  dan `to` harus berpasangan, `to > from`, dan rentang ≤ 6 jam — pelanggaran → **422**. Naive = UTC.
  Cek:
  `curl -s -b <cookie> "localhost:8000/api/v1/monitoring/history?from=2026-10-01T07:00:00Z&to=2026-10-01T08:00:00Z&node_id=1" | head -c 400`.
- Selisih jam server dan timestamp event: jendela memakai waktu **server**, jadi event dengan `ts_event` jauh di masa
  depan/masa lalu (jam node salah) bisa jatuh di luar jendela dan panel Bukti menampilkan “Tidak ada data tren pada
  jendela ini” — cek `date -u` di node saat kejadian seperti itu.
- Migrasi: `0019_monitoring_sample` (FK `node` ON DELETE CASCADE). Rollback: `alembic downgrade 0018`
  (tabel di-drop; riwayat terkumpul hilang — data turunan, terkumpul ulang dalam 7 hari) + `git revert`
  rentang commit S2 + build frontend + restart API. Vision **tidak** berubah dan tidak perlu restart.

## Tab Aturan & alert (S3)

Semua aturan default aktif. Pengaturan global per aturan: ambang, durasi 1–60 menit,
severity `warning|critical`, aktif, dan Telegram. Tabel berikut memuat default;
tab Kondisi saat ini memakai ambang kamera/hardware yang sama (aturan nonaktif
tetap memberi informasi warna). Default FPS S1 berubah 80 % menjadi 50 % target.

Batas ambang: tanpa frame 10–600 s, FPS 10–100 %, suhu GPU 50–110 °C, VRAM/RAM/CPU
50–100 %, latensi 5–2000 ms, backlog 0–10000. Durasi selalu bilangan bulat.

| Aturan | Pelanggaran per menit | Durasi | Severity / Telegram | Tindakan |
|---|---|---|---|---|
| `camera_no_frames` | Kamera dianalisis hilang dari sampel node, atau umur frame maks > 30 s | 2 menit | critical / ON | Cek kamera, NVR, jaringan dan go2rtc |
| `camera_low_fps` | fps min < 50 % target; `starting` atau tanpa target dilewati | 10 menit | warning / OFF | Cek beban GPU/CPU dan substream |
| `gpu_temp` | Suhu GPU maks ≥ 85 °C | 5 menit | critical / ON | Cek pendinginan dan beban GPU |
| `gpu_vram` | VRAM maks ≥ 90 % | 10 menit | warning / OFF | Kurangi beban/model dan cek proses lain |
| `node_ram` | RAM rata-rata ≥ 90 % | 10 menit | warning / OFF | Cek proses dan penggunaan memori |
| `node_cpu` | CPU rata-rata ≥ 90 % | 10 menit | warning / OFF | Cek proses node dan host |
| `infer_latency` | Latensi inferensi rata-rata ≥ 50 ms | 5 menit | warning / OFF | Cek GPU, model, jumlah kamera |
| `mqtt_backlog` | Backlog maks > 0 | 5 menit | warning / ON | Cek broker dan jaringan node→API |

**Semantik operasional:**

- Evaluasi stateless dari sampel S2 tiap menit; setiap menit selesai dalam durasi
  harus ada dan melanggar. Menit kosong tidak dihitung sebagai pelanggaran/normal.
- Pulih setelah dua menit terakhir normal. Node offline atau tanpa sampel sama
  sekali di lookback menahan alert aktif, termasuk setelah API restart.
  Satu node mati tidak menyalakan alert tambahan untuk seluruh kamera/GPU.
- Aturan dimatikan, kamera tidak lagi dianalisis/dihapus, atau GPU hilang dari
  sampel terbaru: tutup dengan event resolved, tanpa Telegram. Penahanan node
  offline/tanpa sampel tetap didahulukan.
- Web selalu menerima event `system`, `payload.kind=health`, state firing/resolved.
  Telegram per aturan pada kedua transisi, **tanpa pengingat ulang**; resolved
  severity info. Event kesehatan tidak membuat chip node offline atau arsir S2.
- Transisi DB dan event disimpan atomik; kegagalan insert event membatalkan transisi
  sehingga evaluator dapat mencoba lagi. Pengiriman WS/Telegram best-effort,
  tanpa outbox/retry durable: gangguan transport atau crash setelah commit dapat
  kehilangan notifikasi langsung, tetapi event tersimpan tetap tersedia di web.
  Uji lock Postgres nyata belum dilakukan pada sesi implementasi; tes memakai
  dua koneksi SQLite dan kompilasi SQL Postgres.
- Badge kamera aktif muncul di Live View/TV, polling 30 detik. Riwayat resolved
  dipangkas setelah 7 hari; API mengembalikan 50 terbaru.
- PUT admin-only (viewer 403), invalid/kunci tak dikenal 422; seluruh patch
  divalidasi sebelum disimpan. DB `health_rules` rusak memakai default field.

**Uji setelah deploy (dengan izin operator):**

1. Catat setting `gpu_temp` lama. Set ambang di bawah suhu saat ini (tetap dalam
   batas 50–110 °C), durasi 1 menit, Telegram ON bila grup uji sudah siap.
2. Tunggu ±2–3 menit: satu alert GPU panas, lonceng/toast, dan satu Telegram.
   Jalankan ulang evaluator/polling tanpa menghasilkan pesan tambahan.
3. Kembalikan setting lama sehingga suhu normal; tunggu dua menit normal →
   event info dan Telegram pulih. Pastikan tidak ada chip node offline.
4. Bila diizinkan, hentikan stream kamera uji: badge tanpa frame di `/live` dan
   `/live/tv`; pulihkan stream dan periksa badge hilang setelah dua menit normal.

**Deploy/rollback S3:**

- Deploy dilakukan sesi terpisah: `alembic upgrade head` (0020; muat env dari
  `.env` tanpa mencetak nilainya), restart `isentinel-api`, frontend HMR/build.
  Vision **tidak** berubah dan tidak perlu restart.
- Rollback: revert commit S3, `alembic downgrade 0019`, restart API dan
  HMR/build frontend. **Downgrade menghapus tabel `health_alert` beserta seluruh
  riwayatnya secara permanen.** Setting `health_rules` diabaikan kode lama;
  default FPS halaman kembali 80 %. Sampel S2 tetap ada.

## Operasi S1

- Restart monitor menempel pada lifespan API; tidak ada unit terpisah, tidak ada migrasi DB.
- Uji cepat: `curl -s -b <cookie> localhost:8000/api/v1/monitoring | head -c 400`.
- Rollback: `git revert` rentang commit S1 + build frontend + restart vision & API; field JSON tambahan pada
  `node.hw`/`node.modules` diabaikan kode lama (tanpa migrasi).
