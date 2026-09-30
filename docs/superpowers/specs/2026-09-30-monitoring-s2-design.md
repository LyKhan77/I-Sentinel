# Spec — Monitoring Resource S2 (riwayat & grafik tren)

Status: **DISETUJUI di chat (2026-09-30)**, menunggu review spec tertulis.
Branch: `feat/monitoring-s2` (dari `main` @ `c5fa3a6`).
Checkpoint: `.cooper/context/next-features.md`.
Siklus sebelumnya: S1 `docs/superpowers/specs/2026-09-29-monitoring-s1-design.md` (merge `c5fa3a6`).

---

## 1. Latar

Monitoring Resource dipecah 3 siklus; S1 (kondisi saat ini + node offline/pulih) selesai. S2 menambah **riwayat dan
grafik tren** agar pola terlihat (mis. GPU penuh tiap pagi, fps kamera turun di jam tertentu). S3 (ambang & alert)
menyusul.

### Kondisi kode (`main` @ `c5fa3a6`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Heartbeat vision tiap 10 s (MQTT `isentinel/nodes/<name>/heartbeat`) disimpan **hanya nilai terakhir**: `node.hw` (`gpus[*]` util/VRAM/suhu/daya, `host` cpu/ram/disk) dan `node.modules` (`detector` ms_avg/ms_max/infer_fps per jendela 10 s, `face`, `mqtt_backlog`, `cameras[*]` per worker: state/fps/target_fps/last_frame_age_s/reconnects_1h/motion_skip_pct). Tidak ada riwayat. | `backend/app/services/events_consumer.py` (cabang heartbeat), `vision/vision/node.py` `_heartbeat_loop` |
| 2 | Heartbeat HTTP internal (`/internal/nodes/{id}/heartbeat`) mengabaikan body — hanya MQTT yang membawa metrik. | `backend/app/api/events.py` |
| 3 | Periode node offline tercatat sebagai event `system` `{node, reason}` (offline `lwt`/`timeout`, pulih `online`) lewat `node_health`. | `backend/app/services/node_health.py` |
| 4 | Pola thread latar + stop rapi di lifespan: `DiskAlertMonitor`, `NodeHealthMonitor`; conftest mematikan interval monitor node. | `services/disk_alert.py`, `services/node_health.py`, `tests/conftest.py` |
| 5 | Migrasi terakhir `0018_user_status`. | `backend/alembic/versions/` |
| 6 | Frontend tanpa library grafik (hanya Carbon/React/Router/Sass); SVG buatan sendiri sudah dipakai (overlay zona/bbox). Pola tab + URL: `ConfigurationPage` (`Tabs` Carbon + `useSearchParams`). | `frontend/package.json`, `features/config/ConfigurationPage.tsx` |
| 7 | Halaman Monitoring S1: `features/monitoring/MonitoringPage.tsx` (polling 10 s, `.app-page`). | |

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Rentang grafik **1 jam / 6 jam / 24 jam / 7 hari**; riwayat disimpan **7 hari**. |
| K2 | Grafik **SVG buatan sendiri** — tanpa dependensi baru. |
| K3 | Metrik: **hardware node** (CPU/RAM, per GPU util/VRAM/suhu), **inferensi AI** (ms rata-rata/maks, fps inferensi, backlog MQTT), **per kamera** (fps aktual vs target, umur frame). Server pusat **tidak** masuk. |
| K4 | Tempat: **tab "Tren"** di halaman Monitoring (tab lain "Kondisi saat ini" = S1), URL `?tab=trend`. |
| K5 | Semua user login dapat melihat (sama dengan S1). |

## 3. Desain

### 3.1 Agregasi per menit (backend, memori)

Modul baru `app/services/monitoring_history.py`.

- `record(node_id: int, hw: dict | None, modules: dict | None, now: datetime | None = None) -> None` dipanggil
  handler heartbeat MQTT setelah `db.commit()`; menambahkan nilai ke **bucket menit berjalan** node itu
  (`bucket = now` dibulatkan ke bawah per 60 s, UTC). Thread-safe (`threading.Lock`), tidak pernah raise (nilai
  bukan angka diabaikan).
- Ringkasan per bucket (satu `dict` per node):

| Kunci | Sumber | Agregasi |
|---|---|---|
| `cpu_pct` | `hw.host.cpu_pct` | `avg`, `max` |
| `ram_pct` | `hw.host.ram_used_mb / ram_total_mb × 100` | `avg`, `max` |
| `gpus[idx].util_pct` | `hw.gpus[*].util_pct` | `avg`, `max` |
| `gpus[idx].vram_pct` | `vram_used_mb / vram_total_mb × 100` | `max` |
| `gpus[idx].temp_c` | `hw.gpus[*].temp_c` | `max` |
| `ms_avg` | `modules.detector.ms_avg` | `avg` |
| `ms_max` | `modules.detector.ms_max` | `max` |
| `infer_fps` | `modules.detector.infer_fps` | `avg` |
| `mqtt_backlog` | `modules.mqtt_backlog` | `max` |
| `cameras[id].fps` | `modules.cameras[*].fps` (entri detect/face digabung: fps terendah) | `min`, `avg` |
| `cameras[id].target_fps` | `target_fps` | nilai terakhir |
| `cameras[id].frame_age_s` | `last_frame_age_s` (terbesar antar worker) | `max` |
| `cameras[id].state` | `state` | terburuk (`reconnecting` > `stalled` > `starting` > `streaming`) |

- Nilai `null` tidak ikut dihitung; metrik tanpa satu pun nilai tidak ditulis (bukan 0).
- `flush(before: datetime) -> list[tuple[int, datetime, dict]]`: mengeluarkan & menghapus bucket yang **selesai**
  (bucket < menit berjalan). Bucket berjalan saat API restart hilang (≤ 1 menit data) — diterima.

### 3.2 Penyimpanan + sampler

- Migrasi **`0019_monitoring_sample`**: tabel `monitoring_sample` — `id` PK, `ts` (DateTime tz, awal menit UTC),
  `node_id` FK `node.id` `ON DELETE CASCADE`, `data` JSON; index `(node_id, ts)`; unique `(node_id, ts)`.
  Model `app/models/monitoring_sample.py`.
- Bentuk `data` (hasil agregasi, angka dibulatkan 1 desimal):

```json
{"cpu_pct": {"avg": 20.1, "max": 35.0}, "ram_pct": {"avg": 18.3, "max": 18.4},
 "gpus": {"0": {"util_pct": {"avg": 40.0, "max": 70.0}, "vram_pct": {"max": 21.0}, "temp_c": {"max": 61}}},
 "ms_avg": {"avg": 8.1}, "ms_max": {"max": 19.3}, "infer_fps": {"avg": 39.5}, "mqtt_backlog": {"max": 0},
 "cameras": {"363": {"fps": {"min": 4.8, "avg": 5.0}, "target_fps": 5.0, "frame_age_s": {"max": 0.3},
                     "state": "streaming"}}}
```

- `HistorySampler` (thread, pola `NodeHealthMonitor`): tiap **60 s** → `flush(now)` → insert satu baris per
  (node, bucket) (duplikat `(node_id, ts)` diabaikan), commit; **sekali per jam** hapus baris `ts < now − 7 hari`.
  Konstanta `SAMPLE_INTERVAL_S = 60`, `RETENTION_DAYS = 7`, `PRUNE_EVERY_S = 3600`. Sesi DB sendiri; exception
  dicatat tanpa mematikan thread; berhenti rapi di lifespan (flush terakhir saat stop). Conftest mematikan interval
  sampler seperti monitor node.
- Node dihapus → sampelnya ikut terhapus (cascade).

### 3.3 API

`GET /api/v1/monitoring/history?range=1h|6h|24h|7d` (router `app/api/monitoring.py`, `get_current_user`; nilai
lain → 422). Resolusi downsample:

| `range` | Rentang | `bucket_s` | Titik maks |
|---|---|---|---|
| `1h` | 1 jam | 60 | 60 |
| `6h` | 6 jam | 60 | 360 |
| `24h` | 24 jam | 300 | 288 |
| `7d` | 7 hari | 1800 | 336 |

- Service `monitoring_history.query(db, range_key, now=None) -> dict`: ambil sampel `ts >= now − rentang`,
  kelompokkan ke `bucket_s` (awal bucket), gabungkan: `avg` → rata-rata, `max` → maks, `min` → min,
  `target_fps` → terakhir, `state` → terburuk. Bucket tanpa sampel **tidak** dikirim (frontend menggambar celah).
- Response:

```json
{
  "range": "6h", "bucket_s": 60, "from": "2026-09-30T02:00:00Z", "to": "2026-09-30T08:00:00Z",
  "nodes": [{
    "id": 1, "name": "server",
    "series": {
      "cpu_pct": [{"t": "2026-09-30T02:00:00Z", "avg": 20.1, "max": 35.0}],
      "ram_pct": [{"t": "...", "avg": 18.3, "max": 18.4}],
      "gpus": {"0": {"util_pct": [{"t": "...", "avg": 40.0, "max": 70.0}],
                     "vram_pct": [{"t": "...", "max": 21.0}], "temp_c": [{"t": "...", "max": 61}]}},
      "ms_avg": [{"t": "...", "avg": 8.1}], "ms_max": [{"t": "...", "max": 19.3}],
      "infer_fps": [{"t": "...", "avg": 39.5}], "mqtt_backlog": [{"t": "...", "max": 0}]
    },
    "cameras": [{"id": 363, "name": "Lorong Server",
                 "fps": [{"t": "...", "min": 4.8, "avg": 5.0}], "target_fps": 5.0,
                 "frame_age_s": [{"t": "...", "max": 0.3}]}],
    "offline": [{"from": "2026-09-30T02:43:45Z", "to": "2026-09-30T02:44:45Z"}]
  }]
}
```

- `offline` per node dari event `system` node itu dalam rentang (+ event offline terakhir sebelum `from` bila node
  masih offline di awal rentang): pasangan offline → online berikutnya; tanpa pasangan → `to` = `null`
  (masih offline). `name` kamera dari tabel `camera` (kamera terhapus → `#<id>`).
- Node tanpa sampel di rentang tetap tampil dengan deret kosong.

### 3.4 Frontend

- **`MonitoringPage`**: Carbon `Tabs` — **"Kondisi saat ini"** (isi S1 apa adanya) dan **"Tren"**; tab sinkron ke
  `?tab=current|trend` (default `current`), pola `ConfigurationPage`. Polling S1 hanya berjalan saat tab current
  aktif; tab trend punya pollingnya sendiri.
- **`features/monitoring/TrendTab.tsx`** (+ `src/api/monitoring.ts` `getMonitoringHistory(range)`):
  - Pemilih rentang (chip `lv-chip` / ContentSwitcher: 1 jam, 6 jam, 24 jam, 7 hari; default 6 jam), tersimpan di
    URL `?tab=trend&range=6h`; pemilih node (Dropdown) bila node > 1; refresh otomatis **60 s**; waktu diperbarui.
  - Kartu grafik (grid responsif, 1 kolom di < 672 px):
    1. **CPU & RAM** (%) — CPU avg, RAM avg; sumbu 0–100.
    2. **GPU {idx}** per GPU — util avg, VRAM max (%); sumbu 0–100.
    3. **Suhu GPU** (°C) — satu garis per GPU (max).
    4. **Latensi inferensi** (ms) — ms rata-rata (avg) & ms maks (max).
    5. **fps inferensi** — avg.
    6. **Backlog MQTT** — max.
    7. **Kamera** — MultiSelect kamera (default: kamera yang punya deret, maks 4; urut nama). Per kamera satu kartu
       berisi dua grafik kecil berdampingan (tanpa sumbu Y kedua): **fps** (min, garis) + target (garis
       putus-putus), dan **umur frame** (max, detik).
  - Setiap grafik menampilkan **arsir merah** untuk periode `offline` node dan **celah** pada bucket tanpa data.
  - Kosong (belum ada sampel, mis. baru deploy) → teks "Belum ada data riwayat — sampel pertama muncul ±1 menit
    setelah node mengirim heartbeat".
- **`components/LineChart.tsx`** (SVG, tanpa dependensi):
  - Props: `series: { key; label; color; points: {t: number; v: number}[]; dashed?: boolean }[]`,
    `from: number`, `to: number`, `bucketMs: number`, `yMin?`, `yMax?` (default auto dari data, min 0),
    `unit?: string`, `shaded?: {from: number; to: number}[]`, `height?` (default 180).
  - Lebar mengikuti kontainer (`ResizeObserver`; fallback 600 di jsdom); sumbu X 4–6 label waktu (format jam:menit
    untuk ≤ 24 jam, tanggal+jam untuk 7 hari, locale aktif); sumbu Y 3–5 label + garis grid tipis.
  - Garis putus (celah) bila jarak antar titik > 1,5 × `bucketMs`.
  - Hover/sentuh: garis vertikal + tooltip (waktu + nilai tiap seri bertanda warna) pada titik bucket terdekat;
    keyboard tidak wajib (grafik bersifat informatif; angka terkini tersedia di tab S1).
  - `role="img"` + `aria-label` ringkasan (judul + nilai terakhir).
  - Warna: palet kategorikal Carbon (`#6929c4`, `#1192e8`, `#005d5d`, `#9f1853`, `#fa4d56`, `#570408`), arsir offline
    `rgba(250,77,86,.15)`.
- Semua string lewat `i18n.tsx` (id + en). 390 px tanpa overflow horizontal halaman.

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| Heartbeat tanpa field baru / nilai bukan angka | Metrik itu dilewati; tanpa exception |
| API restart | Bucket menit berjalan hilang (≤ 1 menit); sampel lama tetap |
| Sampler gagal (DB error) | Dicatat, thread tetap hidup; bucket selesai yang gagal ditulis dibuang (tidak menumpuk memori) |
| Node offline | Tanpa sampel → celah; arsir dari event `system` |
| `range` tidak valid | 422 |
| History gagal dimuat di UI | Pesan error; grafik terakhir tetap tampil |
| Belum ada sampel | Teks "Belum ada data riwayat …" |

## 5. Pengujian

- **Backend**:
  - `monitoring_history.record/flush`: avg/max/min per metrik, persen RAM/VRAM, gabungan worker kamera (fps
    terendah, umur frame terbesar, state terburuk), `null`/tipe ngawur dilewati, bucket berjalan tidak di-flush.
  - Sampler: tulis satu baris per node per menit, duplikat diabaikan, prune > 7 hari tiap jam (clock disuntik),
    thread berhenti rapi + flush terakhir, conftest tidak membiarkan thread jalan.
  - `query`: tiap `range` → `bucket_s` & jumlah titik benar, re-agregasi (avg/max/min/state), bucket kosong tidak
    dikirim, `offline` dari event (pasangan, offline sebelum `from`, masih offline → `to: null`), node tanpa sampel,
    kamera terhapus → `#<id>`.
  - Endpoint: 401 tanpa login, viewer 200, `range=2h` → 422.
  - Handler heartbeat memanggil `record` (heartbeat lama tanpa host/cameras tidak error).
  - Migrasi 0019: upgrade + downgrade (SQLite tes) dan cascade hapus node.
- **Frontend**:
  - `LineChart`: path per seri, celah saat loncatan > 1,5 bucket, garis putus-putus untuk `dashed`, arsir offline,
    tooltip hover menampilkan nilai seri, `aria-label`.
  - `TrendTab`: default 6 jam; ganti rentang → request `range` baru + URL `?tab=trend&range=…`; pilih kamera; data
    kosong → teks "Belum ada data riwayat"; error → pesan + data lama tetap.
  - `MonitoringPage`: tab dari URL (`?tab=trend` membuka Tren), polling S1 berhenti di tab Tren.
  - 390 px tanpa overflow.
- Baseline `main` `c5fa3a6`: backend 532, vision 233 (3 deselected), frontend 211, build 0.

## 6. Verifikasi lapangan (butuh izin user)

Deploy: pull, `alembic upgrade head` (0019, env dari `.env`), restart API, HMR frontend; vision **tidak** perlu
restart. Uji: setelah ±2–3 menit tab Tren (1 jam) menampilkan titik CPU/RAM/GPU/inferensi/kamera; biarkan ±1 jam
lalu cek 6 jam & 24 jam; bekukan vision 60 s (izin) → celah + arsir merah pada rentang itu.

## 7. Di luar scope S2

Grafik server pusat, ekspor CSV, zoom/drag, retensi yang bisa diatur dari UI, perbandingan antar node dalam satu
grafik, ambang & alert (S3).

## 8. Rollback

`git revert` merge + `alembic downgrade 0018` (drop `monitoring_sample`) + restart API + build frontend. Riwayat
yang terkumpul hilang saat downgrade (data turunan, bisa dikumpulkan ulang).
