# Spec — Monitoring Resource S3 (ambang & alert kesehatan)

Status: **DISETUJUI di chat (2026-09-30)**, menunggu review spec tertulis.
Branch: `feat/monitoring-s3` (dari `main` @ `a3693db`).
Checkpoint: `.cooper/context/next-features.md`.
Siklus sebelumnya: S1 (`2026-09-29-monitoring-s1-design.md`, merge `c5fa3a6`), S2 (`2026-09-30-monitoring-s2-design.md`,
merge `a3693db`).

---

## 1. Latar

S1 memberi kondisi saat ini dengan aturan kesehatan **konstanta di kode** yang hanya tampil sebagai warna/issue di
halaman. S2 menyimpan sampel per menit 7 hari. S3 mengubah pelanggaran yang **berlangsung N menit** menjadi **alert**
(web + Telegram opsional) dengan ambang yang bisa diatur, dan menyatukan ambang halaman S1 dengan ambang alert.

### Kondisi kode (`main` @ `a3693db`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Konstanta aturan S1: `FRAME_STALE_S = 30`, `LOW_FPS_RATIO = 0.8`, `RECONNECT_WARN = 3`, `GPU_TEMP_WARN_C = 85`, `VRAM_WARN_PCT = RAM_WARN_PCT = CPU_WARN_PCT = 90`, `HEARTBEAT_LATE_S = 20`. | `backend/app/services/monitoring.py:25-32` |
| 2 | Sampel per menit per node di `monitoring_sample.data` (agregat: `cpu_pct{avg,max}`, `ram_pct{avg,max}`, `gpus.<idx>.{util_pct{avg,max}, vram_pct{max}, temp_c{max}}`, `ms_avg{avg}`, `ms_max{max}`, `infer_fps{avg}`, `mqtt_backlog{max}`, `cameras.<id>.{fps{min,avg}, target_fps, frame_age_s{max}, state}`). `HistorySampler.run_once` (tiap 60 s): `flush` → `write` → prune per jam. | `backend/app/services/monitoring_history.py` |
| 3 | Kamera "dianalisis" = punya zona `active` dengan `behaviors` tidak kosong (logika sama dengan vision). | `monitoring.py` (`analyzed_ids`) |
| 4 | Node offline/pulih: `node_health` (event `system` `{node, reason}`, Telegram `telegram.send_text`, banner). Arsir offline grafik S2 hanya dari `reason ∈ {lwt, timeout}`. | `services/node_health.py`, `monitoring_history._offline` |
| 5 | Pola pengaturan di tabel `setting` dengan nilai efektif + batas: `storage_settings.get/put` (`_bounded`). | `services/storage_settings.py` |
| 6 | Notifikasi web: `EventAlertsProvider` (`NOTIFY_TYPES` termasuk `system`), label via `labels.ts` (`eventTitleKey`, `eventWhere`, `isNodeOnline`); chip node offline hanya dari event `system` offline/pulih. | `frontend/src/features/notifications/*` |
| 7 | Monitoring UI: `MonitoringPage` bertab (`current`, `trend`), `CurrentTab`, `TrendTab`; Live View `CameraTile` (outline event 30 s). | `frontend/src/features/monitoring/*`, `features/live/LiveWall.tsx` |
| 8 | Migrasi terakhir `0019_monitoring_sample`. | `backend/alembic/versions/` |

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Aturan S3: **kamera tanpa frame**, **FPS kamera rendah**, **hardware node** (GPU suhu, VRAM, RAM, CPU), **inferensi & antrean** (latensi, backlog MQTT). |
| K2 | Notifikasi **web selalu** (lonceng/toast/bunyi); **Telegram per aturan** (bisa on/off). Pesan saat menyala **dan** saat pulih. |
| K3 | **Tanpa pengingat ulang** selama alert menyala. |
| K4 | Pengaturan + daftar alert di **tab ketiga Monitoring "Aturan & alert"** (edit admin, viewer read-only). |
| K5 | Live View / TV: **badge di tile** kamera selama alert kamera aktif. |

## 3. Desain

### 3.1 Katalog aturan + pengaturan

Service `app/services/health_rules.py`. Katalog tetap (kunci, target, satuan, batas ambang, default):

| `rule` | Target | Kondisi per sampel menit (melanggar bila …) | `threshold` default (batas) | `duration_min` default | Severity default | Telegram default |
|---|---|---|---|---|---|---|
| `camera_no_frames` | kamera dianalisis | `cameras.<id>` tidak ada di sampel node, **atau** `frame_age_s.max > threshold` | 30 s (10–600) | 2 | critical | ON |
| `camera_low_fps` | kamera dianalisis | `fps.min < threshold% × target_fps` (lewati bila `target_fps` kosong / `state == "starting"`) | 50 % (10–100) | 10 | warning | OFF |
| `gpu_temp` | GPU (`node:idx`) | `temp_c.max ≥ threshold` | 85 °C (50–110) | 5 | critical | ON |
| `gpu_vram` | GPU | `vram_pct.max ≥ threshold` | 90 % (50–100) | 10 | warning | OFF |
| `node_ram` | node | `ram_pct.avg ≥ threshold` | 90 % (50–100) | 10 | warning | OFF |
| `node_cpu` | node | `cpu_pct.avg ≥ threshold` | 90 % (50–100) | 10 | warning | OFF |
| `infer_latency` | node | `ms_avg.avg ≥ threshold` | 50 ms (5–2000) | 5 | warning | OFF |
| `mqtt_backlog` | node | `mqtt_backlog.max > threshold` | 0 (0–10000) | 5 | warning | ON |

- Semua aturan default **aktif**. Per aturan bisa diubah: `enabled: bool`, `threshold: number` (dalam batas),
  `duration_min: int` (1–60), `severity: "warning" | "critical"`, `telegram: bool`.
- Disimpan di `setting` key **`health_rules`** `{<rule>: {partial}}`; `get(db) -> dict[rule, effective]` menggabungkan
  default + nilai tersimpan yang valid (nilai rusak → default); `put(db, patch) -> dict` memvalidasi (kunci tak
  dikenal / di luar batas → `ValueError` → 422).
- **Satu sumber ambang untuk halaman S1**: `monitoring.snapshot` membaca `health_rules.get(db)`:
  `FRAME_STALE_S` ← `camera_no_frames.threshold`, `LOW_FPS_RATIO` ← `camera_low_fps.threshold / 100`,
  `GPU_TEMP_WARN_C` ← `gpu_temp.threshold`, `VRAM_WARN_PCT` ← `gpu_vram.threshold`, `RAM_WARN_PCT` ←
  `node_ram.threshold`, `CPU_WARN_PCT` ← `node_cpu.threshold` (aturan nonaktif tetap memakai ambangnya untuk warna
  halaman — status saat ini tetap informatif). `RECONNECT_WARN`, `HEARTBEAT_LATE_S` tetap konstanta.

### 3.2 Alert: tabel + evaluasi

- Migrasi **`0020_health_alert`**: tabel `health_alert` — `id` PK, `rule` String(32), `target` String(64)
  (`"cam:363"`, `"gpu:1:0"`, `"node:1"`), `node_id` FK `node.id` `ON DELETE CASCADE` (nullable untuk kamera tanpa
  node — tidak terjadi karena hanya kamera dianalisis), `camera_id` Integer nullable (tanpa FK; kamera terhapus
  tetap tercatat), `label` String(128) (mis. `"Lorong Server"`, `"GPU 0 · server"`), `severity` String(16),
  `value` Float nullable, `threshold` Float, `started_at` DateTime tz, `resolved_at` DateTime tz nullable,
  `normal_count` Integer default 0. Index `(resolved_at)`; **partial unique** aktif per `(rule, target)` diganti
  pemeriksaan di kode + unique `(rule, target, started_at)` (portabel SQLite/Postgres).
- `health_alerts.evaluate(db, now) -> dict` dipanggil `HistorySampler.run_once` **setelah** `write` (satu transaksi
  terpisah; exception dicatat, tidak menggagalkan sampler):
  1. Muat aturan efektif, node, kamera dianalisis (`node_id` + zona aktif ber-behavior), sampel
     `ts >= now − max(duration_min) − 2 menit` per node, urut waktu.
  2. **Node offline → tahan**: node `status == "offline"` tidak dievaluasi (alert kamera/GPU/node tidak menyala; yang
     aktif tidak dipulihkan — dibiarkan sampai node online lagi dan sampel normal).
  3. Untuk tiap (aturan aktif, target): ambil **N = duration_min** menit terakhir yang sudah selesai
     (`now − N menit … now`, per menit). **Menyala** bila **setiap** menit dalam jendela punya sampel node **dan**
     melanggar. Menit tanpa sampel node = bukan pelanggaran (tidak menyala) — kecuali `camera_no_frames`: menit
     dengan sampel node tetapi tanpa `cameras.<id>` = pelanggaran.
  4. Target dengan alert aktif: menit terakhir normal → `normal_count += 1`; melanggar → `normal_count = 0`, perbarui
     `value`. **Pulih** bila `normal_count ≥ RESOLVE_MIN = 2` → `resolved_at = now`.
  5. Aturan dinonaktifkan / kamera tidak lagi dianalisis / target hilang (GPU dicabut) → alert aktif target itu
     **ditutup** (`resolved_at = now`) tanpa pesan Telegram "pulih" (event web `resolved` tetap dibuat agar lonceng
     konsisten).
  6. Idempoten: evaluasi dua kali pada menit yang sama tidak membuat alert/event ganda (cek alert aktif
     `(rule, target)` sebelum insert).
- Prune: alert `resolved_at < now − 7 hari` dihapus bersama prune sampel (per jam).

### 3.3 Event + Telegram

- Saat **menyala**: event `system` severity sesuai aturan, `node_id` node target,
  `camera_id` bila kamera, `payload = {"kind": "health", "rule", "target", "label", "value", "threshold",
  "unit", "duration_min", "state": "firing"}`; broadcast WS (pola `node_health._emit`). Telegram bila
  `telegram == true`: `"⚠️ {judul}: {label} — {value}{unit} ({op} {threshold}{unit} selama {N} menit)"`.
- Saat **pulih**: event `system` severity `info`, payload sama dengan `"state": "resolved"`, `value` terakhir,
  `"lasted_min"`; Telegram bila `telegram == true`: `"✅ {judul} normal: {label} — {lasted} menit"`.
- Judul Telegram (id): Kamera tanpa frame, FPS kamera rendah, GPU panas, VRAM GPU tinggi, RAM node tinggi, CPU node
  tinggi, Latensi inferensi tinggi, Event tertahan di node.
- Event `system` kesehatan **tidak** memengaruhi: arsir offline S2 (whitelist `lwt`/`timeout`), banner node offline
  (dari status node), chip node offline (hanya event dengan `payload.reason`).
- `ingest` / retensi: tipe `system` sudah diizinkan dan dikecualikan dari "event tanpa media".

### 3.4 API (router `app/api/monitoring.py`)

- `GET /api/v1/monitoring/rules` (semua user) → `[{rule, enabled, threshold, duration_min, severity, telegram,
  unit, min, max, target}]` (urutan katalog).
- `PUT /api/v1/monitoring/rules` (admin, `require_admin`) body `{<rule>: {enabled?, threshold?, duration_min?,
  severity?, telegram?}}` parsial; validasi Pydantic (`extra="forbid"`) + batas → 422; response = daftar efektif
  baru. Perubahan dicatat `logger.info("health rules updated by %s: %s", username, rules)`.
- `GET /api/v1/monitoring/alerts` (semua user) → `{"active": [...], "recent": [...]}`; item `{id, rule, target,
  label, node_id, camera_id, severity, value, threshold, unit, started_at, resolved_at}`; `active` urut severity lalu
  `started_at`; `recent` = 50 terakhir yang sudah `resolved`, urut `resolved_at` turun.

### 3.5 Frontend

- **`MonitoringPage`**: tab ketiga **"Aturan & alert"** (`?tab=alerts`), di-mount hanya saat aktif.
- **`features/monitoring/AlertsTab.tsx`** (+ `src/api/monitoring.ts`: `getHealthRules`, `putHealthRules`,
  `getHealthAlerts`):
  - **Alert aktif** (polling 30 s): tabel aturan (label i18n), target (`label`), severity tag, nilai + ambang, sejak
    (jam + durasi berjalan); kosong → "Tidak ada alert aktif".
  - **Riwayat**: 50 terakhir (aturan, target, mulai, selesai, durasi).
  - **Aturan**: tabel per aturan — Toggle aktif, NumberInput ambang (satuan, min/max dari API), NumberInput durasi
    (menit 1–60), Select severity, Toggle Telegram; tombol **Simpan** (hanya admin; viewer semua kontrol
    `disabled` / read-only) → toast sukses / notifikasi error 422. Keterangan singkat: "Alert menyala bila kondisi
    berlangsung sepanjang durasi; pulih setelah 2 menit normal."
- **Live View / TV — badge kamera**: hook `useCameraHealthAlerts()` (polling `GET /monitoring/alerts` tiap 30 s,
  sekali per `LiveWall`) → `CameraTile` menampilkan badge kecil di pojok kiri bawah di atas bar nama, mis.
  **"⚠ Tanpa frame"** (critical merah) / **"⚠ FPS rendah"** (warning kuning), selama alert aktif; tidak bentrok
  dengan outline event S1 (outline = event baru, badge = kondisi kesehatan). Gagal fetch → tanpa badge.
- **Notifikasi**: `labels.ts` — event `system` dengan `payload.kind === "health"`: judul = label aturan
  (`health.rule.<rule>`), `firing` → "…", `resolved` → "… normal"; keterangan = `payload.label`. Tidak membuat
  outline/chip node; toast mengikuti severity event.
- i18n id + en untuk semua label aturan, satuan, status. 390 px tanpa overflow (tabel scroll di kontainer).

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| Sampel menit kosong (API baru restart, node offline) | Tidak menyala; alert aktif tidak dipulihkan kecuali ada sampel normal |
| Evaluasi gagal (DB error) | Dicatat; sampler tetap menulis sampel; dicoba lagi menit berikutnya |
| Telegram belum dikonfigurasi / gagal | Alert & event tetap; kegagalan dicatat tanpa token |
| PUT aturan di luar batas / kunci tak dikenal / viewer | 422 / 422 / 403 |
| `health_rules` rusak di DB | Nilai rusak diganti default saat dibaca |
| Kamera dihapus saat alert aktif | Alert ditutup pada evaluasi berikutnya (target hilang) |
| Restart API saat alert aktif | Alert tetap aktif (DB); tidak ada event ganda |

## 5. Pengujian

- **Backend**:
  - `health_rules`: default, merge nilai tersimpan, nilai rusak → default, PUT parsial + batas + kunci tak dikenal.
  - `evaluate` per aturan (sampel buatan, jam disuntik): menyala tepat setelah N menit melanggar; satu menit normal di
    jendela → tidak menyala; menit tanpa sampel → tidak menyala; `camera_no_frames` untuk kamera hilang dari sampel;
    `camera_low_fps` lewati `starting`/tanpa target; pulih setelah 2 menit normal (1 menit normal belum); node
    offline → ditahan; aturan dinonaktifkan / kamera tak lagi dianalisis → ditutup tanpa Telegram; idempoten
    (evaluasi ganda); event payload + severity; Telegram hanya bila flag ON (menyala & pulih).
  - Hook sampler: `run_once` memanggil `evaluate`; error evaluasi tidak menggagalkan penulisan sampel.
  - Prune alert > 7 hari.
  - `monitoring.snapshot` memakai ambang dari `health_rules` (ubah `gpu_temp.threshold` → issue `gpu_hot` ikut).
  - API: rules GET (viewer 200), PUT (admin 200, viewer 403, 422), alerts GET (active/recent).
  - Migrasi 0020 upgrade/downgrade + cascade node.
- **Frontend**:
  - AlertsTab: alert aktif & riwayat tampil; simpan aturan (payload parsial benar, toast); 422 → pesan; viewer
    read-only; `?tab=alerts`.
  - Badge Live View: tile kamera dengan alert aktif menampilkan badge; kamera lain tidak; fetch gagal → tanpa badge.
  - Notifikasi: event health firing/resolved berlabel aturan, tanpa chip node offline.
  - 390 px.
- Baseline `main` `a3693db`: backend 549, vision 233 (3 deselected), frontend 223, build 0.

## 6. Verifikasi lapangan (butuh izin user)

Deploy: pull, `alembic upgrade head` (0020), restart API, HMR; vision tidak. Uji: turunkan sementara ambang
`gpu_temp` di bawah suhu saat ini + durasi 1 menit → ±2–3 menit alert "GPU panas" (lonceng/toast, Telegram bila ON,
tab Aturan & alert) → kembalikan ambang → ±2–3 menit "GPU normal". Uji kamera: nonaktifkan stream satu kamera uji
(bila memungkinkan) → "Kamera tanpa frame" + badge tile di Live View/TV → nyalakan → pulih.

## 7. Di luar scope S3

Ambang per kamera/per node, snooze & jadwal maintenance, eskalasi, email, pengingat ulang, aturan reconnect/heartbeat
terlambat, alert untuk layanan (DB/go2rtc/MQTT).

## 8. Rollback

`git revert` merge + `alembic downgrade 0019` (drop `health_alert`) + restart API + build frontend. Setting
`health_rules` diabaikan kode lama (halaman S1 kembali ke konstanta).
