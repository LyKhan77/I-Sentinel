# ARCHITECTURE — I-Sentinel

Gambaran komponen, alur data, dan batas tanggung jawab. Detail fitur per halaman ada di
`README.md`; prosedur operasional di `docs/RUNBOOK.md` dan `docs/runbooks/`; riwayat perubahan
di `CHANGELOG.md`.

## 1. Topologi

```
                         Browser (LAN) — React + Carbon
                                  │  HTTP :7700 (Vite, proxy /api → :7701)
                                  │  WebSocket /api/v1/ws/events
                                  ▼
   go2rtc :7702 ◄──── API FastAPI :7701 ────► PostgreSQL
   (API/WebRTC :7703/     │   ▲       ▲           (semua state)
    RTSP :7705 loopback)  │   │       │
       ▲                  │   │ MQTT  │ HTTP /internal/nodes/{id}/…
       │ RTSP             │   │ :7704 │ (event, blob clip/snapshot/crop)
   Kamera / NVR           ▼   │       │
        │           Mosquitto ◄──────┤
        └──────────► vision-node (GPU) ──► Telegram Bot API (via API, keluar LAN)
                    YOLO26s TRT + ByteTrack + analyzer + face_worker
```

Peta port (referensi repo & instalasi baru): `7700` web · `7701` API · `7702` go2rtc API ·
`7703` go2rtc WebRTC (tcp+udp, LAN) · `7704` MQTT · `7705` go2rtc RTSP (hanya `127.0.0.1`).
Server dev `gspe-ai3` masih memakai port lama (`5173/8000/1984/8554/1883`) sampai cutover
Docker (`docs/superpowers/specs/2026-10-01-docker-deploy-design.md`).

Satu server (`gspe-ai3`) menjalankan semua komponen saat ini. Fase E memindahkan sebagian
vision-node + go2rtc ke Jetson Orin Nano (`docs/plans/07-edge-jetson.md`); server tetap pusat
DB, alert, dan UI.

| Komponen | Unit systemd | Peran |
|---|---|---|
| API | `isentinel-api.service` | REST + WebSocket, konsumen MQTT, thread latar, proxy snapshot |
| Frontend | `isentinel-web.service` | Vite dev server `:7700` (`API_URL=http://localhost:7701`, `--strictPort`) |
| Vision node | `vision-node.service` | Decode stream, deteksi, tracking, analyzer, wajah, rekam klip |
| Retensi | `isentinel-retention.timer` → `.service` | Sweep media harian 03:00 |
| go2rtc | `go2rtc` | Bridge RTSP → WebRTC/MSE/snapshot untuk UI dan vision |
| Mosquitto | `mosquitto` | Event, heartbeat, config push, LWT |

`isentinel-recorder.service` masih stub; perekaman klip ada di vision-node (`recorder.py`).

## 2. Backend (`backend/app/`)

Lapisan: `api/` (router per domain, tanpa SQL) → `services/` (logika bisnis) → `models/`
(SQLAlchemy) ; kontrak di `schemas/` (Pydantic v2) ; setting hanya dari `core/config.py`.

| Domain | Router (`api/`) | Service (`services/`) |
|---|---|---|
| Auth & user | `auth`, `users` | JWT HS256 di cookie httpOnly, `token_version` untuk cabut sesi, rate-limit login |
| Kamera | `cameras`, `stream_sources`, `credential_profiles`, `location_groups`, `probe`, `live` | `probe`, `stream_endpoint`, `go2rtc`, `secret_store` |
| Node & deteksi | `nodes`, `detector_settings` | `config_push`, `node_health`, `host_stats` |
| Zona & event | `zones`, `events` | `ingest`, `events_consumer`, `annotate`, `event_stats` (`GET /api/v1/events` menerima `camera_id`, `type` berulang, `severity` berulang, `since`, `limit` ≤ 200, `offset` 0–10000 (paginasi halaman berikutnya, di luar rentang → 422) — semuanya difilter di server; urutan `ts_event DESC, id DESC` (pemutus seri deterministik antar-halaman); `GET /api/v1/events/stats/today` → `EventStatsOut`: `total`, `by_type`, `by_severity` tiga kunci selalu ada, `by_hour`/`critical_by_hour` 24 angka jam lokal; tipe `attendance` dikecualikan dari semua angka; `GET /api/v1/events/{id}` → `EventOut` per id, 404 `"event not found"` untuk deep link `/events?event=<id>`) |
| Alert | `alerts`, `telegram` | `alerting`, `alert_dispatcher`, `telegram` |
| Absensi | `employees`, `shifts`, `enrollment`, `attendance` | `face`, `attendance` |
| Storage | `storage` | `retention`, `storage_settings`, `disk_alert` |
| Monitoring | `monitoring` | `monitoring`, `monitoring_history` (`GET /api/v1/monitoring/history` dua mode: `range` relatif (`1h`/`6h`/`24h`/`7d`, default `6h`, bucket 60–1800 dtk) atau jendela eksplisit `from`/`to` ISO + `node_id` opsional — jendela bucket tetap 60 dtk, `range: "custom"`, maksimum 6 jam, diluar retensi 7 hari → seri kosong; `range` bersama `from`/`to`, hanya salah satu, `to <= from`, atau > 6 jam → 422), `health_rules`, `health_alerts` |

### Thread latar (dimulai/dihentikan di lifespan `main.py`)

| Thread | Interval | Tugas |
|---|---|---|
| `events_consumer` | kontinu | Subscribe MQTT, simpan event/heartbeat/LWT/media, broadcast WS |
| `alert_dispatcher` | antrean | Kirim Telegram di luar thread MQTT, broadcast status alert |
| `disk_monitor` | 10 menit | Ambang disk → banner + Telegram (pengingat maks 1×/24 jam) |
| `node_monitor` (`NodeHealthMonitor`) | 15 s | Heartbeat > 35 s → node offline; pulih → online |
| `history_sampler` (`HistorySampler`) | 60 s | Bucket per menit → `monitoring_sample`, lalu evaluasi `health_alerts` |
| `attendance_closer` (`AttendanceCloser`) | 15 menit | Tutup hari: `absent` / `no_exit`, catch-up 7 hari saat start |

### Data utama (PostgreSQL, migrasi Alembic `0001`–`0020`)

- **Kamera**: `camera`, `stream_source`, `credential_profile` (hanya referensi `env:`/`store:`),
  `location_group`, `node`.
- **Deteksi**: `zone` (polygon, behavior, jadwal, toggle Snapshot/Clip/Telegram),
  `detector_setting`, `setting` (key-value JSON: `storage`, `health_rules`, …).
- **Event**: `event` (type, severity, payload JSON, path media), `alert` (status kirim Telegram),
  `telegram_chat`.
- **Absensi**: `employee`, `shift`, `face_embedding`, `attendance_event`, `attendance_day`
  (status + `override_note`).
- **Monitoring**: `monitoring_sample` (7 hari), `health_alert`.
- **User**: `user` (role `admin`/`viewer`, `token_version`).

## 3. Vision node (`vision/vision/`)

```
go2rtc (substream) → pipeline/source → pipeline/detector (YOLO26s TensorRT, pin GPU)
                   → pipeline/tracker (ByteTrack) → analyzers/* → event
mainstream ring (clipring) ──────────────────────────────► recorder (klip pra-buffer + snapshot)
go2rtc frame.jpeg (main) → face_worker (SCRFD + ArcFace, GPU terpisah) → event attendance + embedding
```

- Satu worker per kamera yang punya **zona aktif**; kamera tanpa zona hanya tampil di Live View.
- Analyzer: `intrusion`, `loitering`, `running`, `idle_zone`, `crowd`; wajah lewat `face_worker`
  pada zona attendance (gerbang kualitas: lebar, skor, yaw, blur).
- `transport/`: klien MQTT + antrean disk store-and-forward (event tidak hilang saat broker/API
  putus; backlog dilaporkan di heartbeat).
- Dependensi minimal dan bisa di-import tanpa CUDA; kode GPU/RTSP di balik marker `gpu`.

## 4. Kontrak antar-komponen

### MQTT

| Topik | Arah | Isi |
|---|---|---|
| `isentinel/config/{node}` | API → node, retained | Kamera, zona, jadwal, setting detektor/wajah (config push) |
| `isentinel/nodes/{node}/heartbeat` | node → API, 10 s | Statistik per kamera, host `/proc`, GPU, jendela inferensi, `mqtt_backlog` |
| `isentinel/nodes/{node}/lwt` | node → API, retained | `online` saat connect, `offline` oleh broker saat putus |
| `isentinel/events` | node → API | Event behavior/absensi |
| `isentinel/events/media` | node → API | Path clip/snapshot setelah upload selesai |
| `isentinel/detections/{node}` | node → API → WS | Kotak deteksi live untuk debugger |

### HTTP internal (node → API, `Authorization: Bearer NODE_API_KEY`)

- `POST /internal/nodes/{id}/events` — ingest event.
- `POST /internal/nodes/{id}/blobs?kind=clip|snapshot|crop|face` — upload media (maks 200 MB).
- `POST /internal/nodes/{id}/heartbeat`.

### WebSocket `/api/v1/ws/events` (API → browser)

- Event baru (`EventOut`): Inbox, lonceng notifikasi, outline tile Live View, banner node offline.
- `{kind: "alert", event_id, status}`: status Telegram realtime di Inbox.
- `{type: "detections", …}`: overlay debugger Live View.

### `payload.evidence` pada event `system` (v1, permanen)

Event system baru (health firing/resolved, node offline) membawa seri menit terkait di `payload.evidence`
(frame WS `EventOut` ikut membesar ± 1–3 KB); panel Bukti Inbox menggambar langsung darinya tanpa fetch dan
tanpa batas 7 hari. Event lama tanpa kunci ini tetap memakai `GET /api/v1/monitoring/history` (retensi 7 hari).

- Skema: `{"v":1,"from":"<iso Z>","step_s":60,"series":{…}}` — titik ke-`i` berwaktu `from + i·step_s`, `null` = tanpa sampel.
- Health: `series.value` = nilai metrik per menit (FPS dalam persen target), ≤ 360 titik.
- Node offline: `series.cpu_pct` + `series.infer_fps` (rata-rata 30 menit terakhir); payload juga memuat
  `last_seen`; event pulih memuat `down_s`.

## 5. Alur utama

1. **Konfigurasi**: admin menambah kamera (probe RTSP) → API menulis konfigurasi go2rtc →
   admin menggambar zona → `config_push` publish retained ke node → node menerapkan konfigurasi baru (worker kamera ditambah/diubah/dihentikan).
2. **Event behavior**: analyzer memicu event → node upload snapshot/clip (pra-buffer mainstream) →
   `ingest` menyimpan + dedup → WS broadcast → `alerting` memeriksa toggle, severity, dan rate-limit
   → `alert_dispatcher` mengirim foto + caption ke grup Telegram.
3. **Absensi**: `face_worker` mengumpulkan frame wajah bagus → embedding dikirim di payload →
   API mencocokkan ke galeri `face_embedding` (cosine ≥ `FACE_MATCH_THRESHOLD`) →
   `attendance_event` → `recompute_day` → `attendance_day`. `AttendanceCloser` membuat
   `absent`/`no_exit` setelah batas (selesai shift + `NO_EXIT_GRACE_MIN`).
4. **Enrollment**: 3 foto per karyawan diunggah → API meng-embed dengan InsightFace
   `buffalo_l` → `face_embedding` → galeri di-refresh.
5. **Monitoring**: heartbeat → `node.hw`/`node.modules` (kondisi saat ini) → `HistorySampler`
   (tren 7 hari) → `health_alerts` (alert kesehatan, event `system` `payload.kind="health"`).
6. **Retensi**: sweep harian menghapus media sesuai `clip_days`/`snapshot_days`/`attendance_days`;
   event yang kehilangan media terakhirnya ikut dihapus (kecuali `system`).

## 6. Frontend (`frontend/src/`)

- `app/`: AppShell (header, side-nav, banner node offline), routing, `i18n.tsx` (id/en), `theme.scss`.
- `features/`: `dashboard` (status-first: `useDashboardData` polling 15 dtk kegagalan-per-sumber dari
  `/monitoring`, `/monitoring/alerts`, `/events/stats/today`, `/attendance`, `/storage/stats`; strip status,
  4 tile tautan, chart per jam, event terbaru via `useEventAlerts` — tanpa langganan realtime kedua;
  masalah aktif; node ringkas), `live` (grid + mode TV kiosk), `events` (Inbox master-detail),
  `attendance`, `enrollment`, `config` (kamera, zona, deteksi, node, storage, notifikasi, user),
  `monitoring` (kondisi, tren SVG, aturan & alert), `notifications` (`EventAlertsProvider`).
- `api/`: satu klien REST per domain + `useWs.ts`. Komponen memakai Carbon; tidak ada akses
  REST di luar `src/api/`.

## 7. Keamanan & penyimpanan

- **Zero-secret di DB/API**: kredensial kamera dan token Telegram hanya di `.env` atau file rahasia
  `CAMERA_SECRETS_FILE` (`0600`, di luar `STORAGE_ROOT`); DB menyimpan referensi.
- Snapshot live di-proxy same-origin dan wajib login; go2rtc tidak dibuka ke browser langsung.
- Role `admin` (konfigurasi, enrollment, koreksi, cleanup) dan `viewer` (read-only).
- `STORAGE_ROOT`: `clips/`, `snapshots/`, `crops/`, `faces/`, `faces_models/`, `models/`.
  Data runtime server di `I-Sentinel-data/{api,vision}` (di luar repo).
- Paparan: aman untuk LAN; tidak ada komponen yang boleh dibuka ke publik.
