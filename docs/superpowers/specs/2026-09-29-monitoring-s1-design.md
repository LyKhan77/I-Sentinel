# Spec — Monitoring Resource S1 (data kesehatan + node offline/pulih + halaman Monitoring)

Status: **DISETUJUI di chat (2026-09-29)**, menunggu review spec tertulis.
Branch: `feat/monitoring-s1` (dari `main` @ `7656c13`).
Checkpoint: `.cooper/context/next-features.md`.

---

## 1. Latar

Usulan user: halaman baru **Monitoring Resource** di grup menu **System** (bukan tab Konfigurasi) untuk memantau
kesehatan per kamera, kesehatan inferensi AI, dan hardware (CPU/GPU/RAM). Saran yang disetujui ikut masuk: status
node + event offline/pulih, kesehatan layanan, grafik tren, ambang & alert.

Dipecah **3 siklus** (keputusan user); spec ini hanya **S1**:

| Siklus | Isi |
|---|---|
| **S1 (spec ini)** | Pengumpulan data (heartbeat vision diperluas), monitor node offline/pulih (event + Telegram + banner), pemeriksaan layanan, halaman Monitoring kondisi **saat ini** |
| S2 | Penyimpanan sampel + grafik tren 1–24 jam |
| S3 | Ambang yang bisa diatur + alert kamera/GPU/latensi (event `system` → lonceng/TV/Telegram) |

### Kondisi kode (`main` @ `7656c13`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Heartbeat vision tiap `heartbeat_s = 10` s: `cpu_percent` = **`os.getloadavg()[0]`** (bukan persen), `gpu_mem: None`, `cameras: [id]`, `hw` = NVML (nama, VRAM, util, proses), `modules.detector` (`ms_per_frame` = **rata-rata kumulatif sejak start**, `detect_n`), `modules.face` (`loaded`, `detect_n`, `embed_n`). | `vision/vision/node.py:476-510`, `vision/vision/hardware.py` |
| 2 | Backend menyimpan dari heartbeat hanya `node.status="online"`, `last_seen`, `hw`, `modules` (JSON, tanpa riwayat); `cameras`/`cpu_percent` dibuang. | `backend/app/services/events_consumer.py:86-100` |
| 3 | `camera.status` hanya diisi probe manual → praktis statis; tidak ada kesehatan runtime per kamera. | `backend/app/api/probe.py:113` |
| 4 | `FrameSource` (per kamera): reader thread + reconnect backoff 1→30 s; `cap.read()` bisa **menggantung** tanpa gagal (RTSP macet). Tidak ada counter yang dilaporkan. | `vision/vision/pipeline/source.py` |
| 5 | Node offline: (a) LWT MQTT (crash/putus) → `status="offline"` + event `system {node, reason:"lwt"}` — tanpa broadcast WS, tanpa Telegram; (b) stop rapi tidak mengirim LWT (`mqtt.py:91`) → offline hanya bila ada yang memanggil `GET /nodes` (`mark_stale_nodes`, 35 s) dan **tanpa event**; (c) node hidup lagi → tanpa event. | `events_consumer.py:101-115`, `models/node.py:6`, `api/nodes.py:17` |
| 6 | **Bug terverifikasi:** LWT dipublikasikan `retain=True` dan tidak pernah dibersihkan → setiap API restart (consumer subscribe ulang) menerima LWT lama → event `system` "offline" **palsu**. Bukti server (read-only): hanya 2 event `system` di DB, `2026-09-29 11:39:32` dan `15:04:02` = tepat waktu start `isentinel-api`. | `vision/vision/transport/mqtt.py:28-30` |
| 7 | Antrean store-and-forward vision `DiskQueue.size()` ada, tidak dilaporkan. | `vision/vision/transport/queue.py:63` |
| 8 | Pola monitor latar + Telegram sekali per perpindahan sudah ada: `DiskAlertMonitor` (thread, sesi DB sendiri, stop rapi, `_send` via `telegram.deliver`). | `backend/app/services/disk_alert.py` |
| 9 | go2rtc: `stream_names()` / `/api/streams` (stream `cam_<id>`, `cam_<id>_main`); vision membaca kamera lewat go2rtc. | `backend/app/services/go2rtc.py` |
| 10 | Notifikasi web (lonceng/toast/chip) memperlakukan semua event `system` sebagai "Node X offline" 30 s. | `frontend/src/features/notifications/*` |
| 11 | Deployment kini: API + vision di satu host (`gspe-ai3`, node `server`); rencana Fase E memisah node ke Jetson. | `AGENTS.md`, ROADMAP |

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Halaman baru **System › Monitoring** (route `/monitoring`), terpisah dari Konfigurasi. |
| K2 | Cakupan fitur (lintas siklus): kamera, inferensi AI, hardware, status node + offline/pulih, layanan, tren (S2), ambang & alert (S3). |
| K3 | **3 siklus**; S1 = data + node offline/pulih + halaman kondisi saat ini. |
| K4 | Halaman dapat dibuka **semua user** (viewer read-only; tidak ada aksi). |
| K5 | Node offline/pulih: event `system` + broadcast WS + **Telegram** sekali per perpindahan + **banner persisten** di AppShell dan mode TV selama node offline. Ambang offline **35 s**. |
| K6 | Tanpa dependensi baru, tanpa migrasi DB. Deploy S1: restart **vision + API** + HMR frontend. |

## 3. Desain

### 3.1 Vision — heartbeat diperluas (stdlib saja)

Field lama tetap (kompatibel); tambahan:

- **Per kamera** (`FrameSource` + `CameraWorker`/`FaceGateWorker`): heartbeat `cameras` menjadi daftar objek
  (field lama `cameras: [id]` diganti — backend menerima kedua bentuk, §3.2):
  ```json
  {"id": 3, "worker": "detect", "state": "streaming", "fps": 4.9, "target_fps": 5.0,
   "last_frame_age_s": 0.2, "reconnects_1h": 0, "motion_skip_pct": 62.0}
  ```
  - Satu entri **per worker**: `worker = "detect"` (`CameraWorker`, substream) atau `"face"` (`FaceGateWorker`,
    main stream, `motion_skip_pct: null`). Kamera gerbang absensi bisa punya dua entri; backend menggabungkan per
    `id` dengan mengambil kondisi **terburuk** (state terburuk, fps rasio terendah, reconnect terbanyak, umur frame
    terlama).
  - `FrameSource` mencatat: `last_frame_mono` (frame terakhir dari reader), `opened` (hasil open/reconnect
    terakhir), `reconnect_times` (monotonic, dipangkas > 1 jam), `started_mono`.
  - `state`: `starting` (belum ada frame dan < 30 s sejak start) · `reconnecting` (reader dalam backoff / open
    gagal) · `stalled` (terbuka tetapi frame terakhir > 10 s — RTSP macet) · `streaming` (lainnya).
  - `fps` = frame yang diproses worker di jendela sejak heartbeat sebelumnya (dibagi lama jendela);
    `target_fps` = `ai_fps` kamera; `motion_skip_pct` = persen frame jendela yang dilewati motion gate (`null`
    bila gate mati).
- **Inferensi**: `modules.detector` + `ms_avg`, `ms_max`, `infer_fps` untuk **jendela sejak heartbeat
  sebelumnya** (counter kumulatif lama tetap untuk kompatibilitas); `modules.face` + `queue` (jumlah `_pending_events.qsize()`
  semua `FaceGateWorker`); `mqtt_backlog` = `DiskQueue.size()`.
- **Hardware**: `hw.host = {cpu_pct, ram_used_mb, ram_total_mb, disk_used_pct, disk_free_gb}` — CPU dari selisih
  `/proc/stat` antar heartbeat (panggilan pertama `null`), RAM dari `/proc/meminfo` (`MemTotal − MemAvailable`),
  disk = `shutil.disk_usage(data_dir)`; non-Linux → field `null`. `hw.gpus[*]` + `temp_c` (NVML temperature),
  `power_w` (NVML power usage / 1000); gagal per field → `null`.
- **LWT retained dibersihkan (fix #6)**: di `_on_connect`, node mempublikasikan `{"status":"online"}` ke topik
  LWT dengan `retain=True, qos=1` (menimpa pesan offline lama). Backend mengabaikan payload LWT dengan
  `status != "offline"`.

### 3.2 Backend — `node_health` (monitor + transisi) dan `monitoring` (agregasi)

**`app/services/node_health.py`**
- `mark_offline(db, node, reason, now=None) -> bool` / `mark_online(db, node, now=None) -> bool`: **satu-satunya**
  jalur perubahan status node. Hanya bila status berubah: set status, `ingest_event` `system`
  (`{"node", "reason"}`; offline `warning` dengan `reason ∈ {"lwt","timeout"}`, pulih `info` dengan
  `reason:"online"`), broadcast WS (pola `events_consumer`), kirim Telegram
  ("⚠️ Node {node} offline ({reason}) — deteksi AI berhenti" / "✅ Node {node} pulih — offline {durasi}").
  Status `unknown` → `online` (node baru / DB lama) **tidak** membuat event.
- `check(db, now=None) -> int`: node `online` dengan `last_seen` lebih tua dari `HEARTBEAT_TIMEOUT_S = 35` →
  `mark_offline(reason="timeout")`; kembalikan jumlah.
- `NodeHealthMonitor` (pola `DiskAlertMonitor`): thread latar tiap `CHECK_INTERVAL_S = 15`, sesi DB sendiri,
  exception dicatat tanpa mematikan thread, stop rapi di lifespan.
- Pemanggil yang diubah: handler LWT (`status=="offline"` → `mark_offline(reason="lwt")`), handler heartbeat
  (`mark_online` bila sebelumnya `offline`), `GET /nodes` **tidak lagi** memanggil `mark_stale_nodes`,
  `POST /internal/maintenance/mark-stale` → `node_health.check`. `mark_stale_nodes` dihapus.
- Telegram: helper `telegram.send_text(db, text) -> bool` (dipindah dari `disk_alert._send`; `disk_alert` ikut
  memakainya). Tanpa token/grup → tidak mengirim, transisi tetap tercatat.

**Heartbeat handler**: simpan `hw` (termasuk `host`) apa adanya; `modules` disimpan dengan tambahan
`modules.cameras` (dari field top-level `cameras`) dan `modules.mqtt_backlog` (dari top-level `mqtt_backlog`) —
tanpa kolom baru. Bentuk lama `cameras: [id]` dinormalkan menjadi `[{"id": id}]` (tanpa statistik → `no_data`).

**`app/services/monitoring.py`** — `snapshot(db, now=None) -> dict` + aturan kesehatan (konstanta modul):

| Konstanta | Nilai |
|---|---|
| `FRAME_STALE_S` | 30 |
| `LOW_FPS_RATIO` | 0.8 |
| `RECONNECT_WARN` | 3 (per jam) |
| `GPU_TEMP_WARN_C` | 85 |
| `VRAM_WARN_PCT` / `RAM_WARN_PCT` / `CPU_WARN_PCT` | 90 |
| `SWEEP_STALE_H` | 26 |
| `SERVICE_CACHE_S` | 10 |

- **Kamera** (hanya `enabled`; nonaktif dihitung terpisah `disabled`), `issues` berupa kode:
  - `critical`: `node_offline` (node kamera offline) · `not_running` (kamera ber-`node_id` tetapi tidak ada di
    heartbeat node) · `no_frames` (`state ∈ {reconnecting, stalled}` atau `last_frame_age_s > 30`).
  - `warning`: `low_fps` (`fps < 0.8 × target_fps`, tidak berlaku saat `starting`) · `reconnects`
    (`reconnects_1h ≥ 3`) · `stream_missing` (`cam_<id>` tidak terdaftar di go2rtc) · `no_data` (heartbeat
    node belum membawa statistik kamera — vision lama).
  - kamera tanpa `node_id` (tidak dianalisis): `ai = null`, hanya aturan `stream_missing`.
- **Node**: `critical` `offline`; `warning` `gpu_hot` / `vram_high` / `ram_high` / `cpu_high` / `mqtt_backlog`
  (> 0) / `heartbeat_late` (> 2 × `heartbeat_s` = 20 s tetapi belum 35 s).
- **Layanan** (`key`, `health`, `detail`, `latency_ms`), di-cache 10 s:
  - `database` — `SELECT 1` + latensi; gagal → `critical`.
  - `go2rtc` — `GET /api/streams` + latensi + jumlah stream; gagal → `critical`.
  - `mqtt` — status koneksi consumer (flag `connected` di `EventConsumer`, diset di `on_connect` /
    `on_disconnect`); terputus → `critical`.
  - `retention` — `retention_last_sweep`; > 26 jam / belum pernah → `warning`.
  - `telegram` — belum dikonfigurasi → `unknown` (tidak dihitung); alert terakhir `failed` → `warning`;
    `detail` = status + waktu alert terakhir + jumlah antrean `queued`.
  - `disk` — `disk_alert.over` → `warning`.
- **Server** (host API): `cpu_pct`, `ram_used_mb`, `ram_total_mb` (helper `/proc` yang sama logikanya dengan
  vision; `# ponytail:` duplikasi kecil lintas paket karena vision tidak boleh bergantung pada backend) +
  `disk` `STORAGE_ROOT` (pakai `retention.disk_usage`).
- **Ringkasan**: status keseluruhan = terburuk dari kamera/node/layanan; hitungan `ok/warning/critical` per
  kelompok (+ `disabled` kamera).

**API** `GET /api/v1/monitoring` (router baru `app/api/monitoring.py`, `get_current_user` — semua role), schema
Pydantic `app/schemas/monitoring.py`:

```json
{
  "generated_at": "2026-09-29T08:00:00Z",
  "summary": {"health": "warning",
              "cameras": {"ok": 10, "warning": 1, "critical": 0, "disabled": 2},
              "nodes": {"ok": 1, "warning": 0, "critical": 0},
              "services": {"ok": 5, "warning": 1, "critical": 0}},
  "server": {"cpu_pct": 23.0, "ram_used_mb": 12000, "ram_total_mb": 64000,
             "disk_used_pct": 65.0, "disk_free_gb": 310.2},
  "nodes": [{"id": 1, "name": "server", "status": "online", "last_seen": "...", "age_s": 3.1,
             "health": "ok", "issues": [],
             "host": {"cpu_pct": 41.0, "ram_used_mb": 9000, "ram_total_mb": 64000,
                      "disk_used_pct": 65.0, "disk_free_gb": 310.2},
             "gpus": [{"idx": 0, "name": "RTX", "util_pct": 55, "vram_used_mb": 5000,
                       "vram_total_mb": 12000, "temp_c": 61, "power_w": 120.5}],
             "inference": {"detector": {"model": "yolo26s.engine", "device": "0", "ms_avg": 7.9,
                                        "ms_max": 15.2, "infer_fps": 48.0},
                           "face": {"loaded": true, "queue": 0},
                           "mqtt_backlog": 0}}],
  "cameras": [{"id": 3, "name": "CAM-03", "location": "Gudang", "node_id": 1, "node_name": "server",
               "enabled": true, "health": "warning", "issues": ["low_fps"],
               "ai": {"state": "streaming", "fps": 3.1, "target_fps": 5.0, "last_frame_age_s": 0.4,
                      "reconnects_1h": 0, "motion_skip_pct": 60.0},
               "stream": {"registered": true}}],
  "services": [{"key": "database", "health": "ok", "detail": null, "latency_ms": 1.2}]
}
```

`NodeOut` (`GET /nodes`) ditambah `last_seen` (untuk banner).

### 3.3 Frontend

- **Menu**: grup `nav.group.system` mendapat item **Monitoring** (`/monitoring`, ikon Carbon `Activity`, **tanpa**
  `adminOnly`), di atas Konfigurasi. Route di `main.tsx` di dalam AppShell; `SEGMENT_TO_KEY` + kunci
  `nav.monitoring`.
- **`src/api/monitoring.ts`**: `getMonitoring(): Promise<Monitoring>` + tipe.
- **`features/monitoring/MonitoringPage.tsx`** (polling **10 s**, fetch gagal → pesan error, data terakhir tetap
  tampil dengan waktu "diperbarui"):
  1. **Ringkasan**: tile status keseluruhan (Sehat / Peringatan / Kritis) + tile kamera / node / layanan (jumlah
     per status) + waktu diperbarui.
  2. **Node** (kartu per node + kartu **Server pusat**): status + umur heartbeat, CPU %, RAM, disk, per GPU
     (util, VRAM, suhu, daya), inferensi (model, device, ms rata-rata/maks, fps inferensi, antrean face, backlog
     MQTT), daftar issue.
  3. **Kamera** (DataTable Carbon): nama, lokasi, node, status (tag warna), state AI, fps aktual/target, umur
     frame terakhir, reconnect 1 jam, skip motion %, stream go2rtc; urut kritis → peringatan → sehat → nama;
     toggle **"Hanya bermasalah"**; issue ditampilkan sebagai teks i18n. 390 px: tabel bisa di-scroll horizontal
     di dalam kontainernya sendiri (halaman tidak overflow).
  4. **Layanan**: daftar key → status + detail + latensi.
- **Warna status** konsisten dengan `ev-dot` (critical `#fa4d56`, warning `#f1c21b`, ok hijau `#42be65`,
  unknown abu-abu).
- **`components/NodeOfflineBanner.tsx`**: polling `listNodes()` tiap **15 s**; setiap node `offline` →
  InlineNotification error "Node {name} offline sejak {jam} — deteksi AI berhenti" (tanpa tombol tutup; hilang
  sendiri saat node online). Dipasang di **AppShell** (di atas konten semua halaman) dan **`LiveTvPage`** (fixed
  di atas wall, tidak tertutup toolbar). `listNodes` gagal → tanpa banner.
- **Notifikasi (penyesuaian)**: event `system` dengan `payload.reason === "online"` → toast/lonceng berlabel
  "Node {node} pulih" (severity info), **tidak** membuat chip offline dan **menghapus** chip offline node itu.
  `reason` lain tetap "Node {node} offline".
- Semua string lewat `i18n.tsx` (id + en), termasuk label kode `issues`, `state`, dan `key` layanan.

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| Heartbeat vision lama (tanpa statistik baru) | Kamera `warning` `no_data`; node tetap tampil dari field lama |
| NVML / `/proc` tidak tersedia | Field `null` → UI "—"; tidak mengubah health |
| go2rtc / DB / MQTT gagal dicek | Layanan `critical` dengan `detail`; endpoint tetap 200 |
| `GET /monitoring` gagal di UI | Pesan error; data terakhir tetap tampil |
| LWT offline retained lama saat API start | Tidak ada lagi: vision menimpa dengan `online` saat connect; payload non-offline diabaikan |
| Node berkedip (offline ↔ online cepat) | Satu event + satu Telegram per perpindahan; tanpa debounce di S1 (tercatat untuk S3) |
| Telegram belum dikonfigurasi / gagal | Transisi & event tetap; kegagalan dicatat tanpa token |
| API restart saat node offline | Status offline tersimpan di DB → banner tetap; tidak ada event ganda |

## 5. Pengujian

- **Vision** (`vision/tests`): state kamera `starting/streaming/reconnecting/stalled` + `reconnects_1h` +
  pemangkasan 1 jam (clock monotonic disuntik); fps jendela & `motion_skip_pct`; detector `ms_avg/ms_max/infer_fps`
  jendela; host stats dari file `/proc` palsu (CPU null di panggilan pertama); heartbeat memuat field baru +
  `mqtt_backlog`; `_on_connect` mempublikasikan LWT `online` retained.
- **Backend**: `node_health` — timeout → offline + event + Telegram sekali; heartbeat → online + event pulih +
  Telegram; LWT offline → satu event (tidak dobel dengan timeout); LWT `online`/retained non-offline diabaikan;
  `unknown → online` tanpa event; `GET /nodes` tidak mengubah status; monitor thread berhenti rapi.
  `monitoring.snapshot` — tiap aturan issue kamera/node/layanan, heartbeat lama → `no_data`, kamera tanpa node,
  nonaktif → `disabled`, ringkasan = terburuk; endpoint 200 untuk viewer, 401 tanpa login; layanan gagal (DB/go2rtc
  dipalsukan) → `critical`. `disk_alert` tetap hijau setelah pindah ke `telegram.send_text`.
- **Frontend**: MonitoringPage (ringkasan, urutan & filter "Hanya bermasalah", label issue, error fetch
  mempertahankan data), menu Monitoring terlihat untuk viewer, NodeOfflineBanner (tampil/hilang, di TV),
  notifikasi `reason:"online"` (label pulih, chip offline hilang), 390 px.
- Baseline `main` `7656c13`: backend 491, vision 223 (3 deselected), frontend 203, build 0.

## 6. Verifikasi lapangan (butuh izin user)

Deploy: pull, restart **vision** (fix LWT retained + heartbeat baru) dan **API**, HMR frontend; tanpa migrasi.
Uji: halaman Monitoring menampilkan node `server`, GPU, semua kamera + layanan; restart API → **tidak ada** event
"Node offline" palsu; hentikan vision sebentar (dengan izin) → ≤ ~50 s banner + event + Telegram offline,
nyalakan → event + Telegram pulih, banner hilang; putus satu kamera (bila memungkinkan) → kamera kritis `no_frames`.

## 7. Di luar scope S1

Riwayat & grafik (S2); ambang yang bisa diatur, alert kamera/GPU/latensi, debounce flapping (S3); aksi restart /
kontrol dari UI; health host go2rtc/Postgres di mesin terpisah; per-proses GPU di UI (sudah ada di Konfigurasi →
Nodes).

## 8. Rollback

`git revert` merge + restart vision & API + build frontend. Tanpa migrasi; field JSON tambahan di `node.hw` /
`node.modules` diabaikan kode lama. Catatan: kode lama kembali membawa bug LWT retained (event offline palsu saat
API restart) kecuali pesan retained `online` dari node baru masih ada di broker.
