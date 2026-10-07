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
Sejak cutover 2026-10-02 server dev `gspe-ai3` menjalankan peta ini lewat Docker; tabel unit systemd di bawah adalah topologi
legacy (dinonaktifkan, dipakai untuk rollback).

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

### Topologi Docker (aktif di `gspe-ai3` sejak 2026-10-02)

Diagram dan tabel systemd di atas adalah topologi legacy (rollback). Stack `docker/compose.yml` (project `isentinel`)
menjalankan tujuh layanan pada jaringan internal Compose:

```text
Browser → web:7700 (nginx static SPA) → api:7701 (HTTP + WebSocket)
Browser → go2rtc:7702 / :7703 TCP+UDP
Kamera/NVR → go2rtc → vision (RTSP go2rtc:7705, internal)
vision → mosquitto:7704 → api → postgres:5432 (internal)
vision → api (media) → DATA_DIR/api
retention (image API) → postgres + DATA_DIR/api, sweep 03:00 TZ
```

| Layanan | Image | Host port / data |
|---|---|---|
| `postgres` | `postgres:16-alpine` | Tidak dipublikasikan; named volume `pgdata` |
| `mosquitto` | `eclipse-mosquitto:2.0.22` | `7704`; passwd + persistence di DATA_DIR |
| `go2rtc` | `alexxit/go2rtc:1.9.9` | `7702`, `7703` TCP/UDP; `/config` bind rw, YAML `0600` |
| `api` | `isentinel-api:local`, Python 3.12 + face CPU | `7701`; migrasi sebelum uvicorn; API/secrets bind |
| `vision` | `isentinel-vision:local`, CUDA 13 + lock | Profile `vision`; semua GPU terlihat, pin per node di UI |
| `web` | `isentinel-web:local`, Node build → nginx | `7700`; proxy `/api/` variabel + resolver `127.0.0.11` |
| `retention` | Image API | Loop Python harian; tidak menjalankan migrasi |

Semua layanan memakai `restart: unless-stopped`, `TZ`, log json-file maksimum
`10m` × 5. UID/GID host dipakai selain postgres dan web. API tidak mendapat GPU;
vision memakai `shm_size=VISION_SHM_SIZE` (default sementara `2gb`) untuk ring klip.
Healthcheck tersedia untuk postgres, mosquitto, go2rtc, API, dan web; status vision
dibuktikan lewat heartbeat node `online` dan event, bukan sekadar container running.

`${DATA_DIR}/models` dipasang `/models` (bobot + engine YOLO); wajah API berada di
`api/faces_models` dan dibaca vision read-only `/faces`. `${DATA_DIR}/secrets`
dipasang `/secrets`, di luar STORAGE_ROOT. YAML runtime go2rtc berisi kredensial
RTSP dan dipertahankan antarrun. PostgreSQL named volume adalah pengecualian dari
bind mount UID host. Nomor port internal sama dengan publish; `7705` dan `5432`
tidak dipublikasikan. Browser tetap mendapat hostname LAN melalui GO2RTC_PUBLIC_HOST.


## 2. Backend (`backend/app/`)

Lapisan: `api/` (router per domain, tanpa SQL) → `services/` (logika bisnis) → `models/`
(SQLAlchemy) ; kontrak di `schemas/` (Pydantic v2) ; setting hanya dari `core/config.py`.

| Domain | Router (`api/`) | Service (`services/`) |
|---|---|---|
| Auth & user | `auth`, `users` | JWT HS256 di cookie httpOnly, `token_version` untuk cabut sesi, rate-limit login |
| Kamera | `cameras`, `stream_sources`, `credential_profiles`, `location_groups`, `probe`, `live` | `probe`, `stream_endpoint`, `go2rtc`, `secret_store` |
| Node & deteksi | `nodes`, `detector_settings` | `config_push`, `node_health`, `host_stats` |
| Zona & event | `zones`, `events` | `ingest`, `events_consumer`, `annotate`, `event_stats` (`GET /api/v1/events` menerima `camera_id`, `type` berulang, `severity` berulang, `since`, `limit` ≤ 200, `offset` 0–10000 (paginasi halaman berikutnya, di luar rentang → 422) — semuanya difilter di server; urutan `ts_event DESC, id DESC` (pemutus seri deterministik antar-halaman); `GET /api/v1/events/stats/today` → `EventStatsOut`: `total`, `by_type`, `by_severity` tiga kunci selalu ada, `by_hour`/`critical_by_hour` 24 angka jam lokal; tipe `attendance` dikecualikan dari semua angka; `GET /api/v1/events/{id}` → `EventOut` per id, 404 `"event not found"` untuk deep link `/events?event=<id>`) |
| Alert | `alerts`, `telegram` | `alerting`, `alert_dispatcher`, `alert_ai`, `telegram` |
| AI advisory (opsional) | `ai`, `ai_settings` (admin) | `ai_worker`, `ask_ai`, `llm_client`, `llm_config`, `ai_media`, `ai_prompts`; tidak terlibat dalam keputusan alert; caption `ok` diedit ke alert Telegram oleh `alert_ai` |
| Absensi | `employees`, `shifts`, `enrollment`, `attendance` | `face`, `attendance` |
| Storage | `storage` | `retention`, `storage_settings`, `disk_alert` |
| Monitoring | `monitoring` | `monitoring`, `monitoring_history` (`GET /api/v1/monitoring/history` dua mode: `range` relatif (`1h`/`6h`/`24h`/`7d`, default `6h`, bucket 60–1800 dtk) atau jendela eksplisit `from`/`to` ISO + `node_id` opsional — jendela bucket tetap 60 dtk, `range: "custom"`, maksimum 6 jam, diluar retensi 7 hari → seri kosong; `range` bersama `from`/`to`, hanya salah satu, `to <= from`, atau > 6 jam → 422), `health_rules`, `health_alerts` |

### Thread latar (dimulai/dihentikan di lifespan `main.py`)

| Thread | Interval | Tugas |
|---|---|---|
| `events_consumer` | kontinu | Subscribe MQTT, simpan event/heartbeat/LWT/media, broadcast WS |
| `alert_dispatcher` | antrean | Kirim Telegram di luar thread MQTT, simpan `message_id`, sinkronkan caption AI setelah status `sent`, broadcast status alert |
| `disk_monitor` | 10 menit | Ambang disk → banner + Telegram (pengingat maks 1×/24 jam) |
| `node_monitor` (`NodeHealthMonitor`) | 15 s | Heartbeat > 35 s → node offline; pulih → online |
| `history_sampler` (`HistorySampler`) | 60 s | Bucket per menit → `monitoring_sample`, lalu evaluasi `health_alerts` |
| `attendance_closer` (`AttendanceCloser`) | 15 menit | Tutup hari: `absent` / `no_exit`, catch-up 7 hari saat start |
| `ai_worker` (`AiWorker`) | antrean | Caption snapshot, dedupe caption per event, throttle per zona, recovery pending saat start; caption `ok` memicu sinkronisasi alert Telegram |

### Data utama (PostgreSQL, migrasi Alembic `0001`–`0022`)

- **Kamera**: `camera`, `stream_source`, `credential_profile` (hanya referensi `env:`/`store:`),
  `location_group`, `node`.
- **Deteksi**: `zone` (polygon, behavior, jadwal, toggle Snapshot/Clip/Telegram),
  `detector_setting`, `setting` (key-value JSON: `storage`, `health_rules`, …).
- **Event**: `event` (type, severity, payload JSON, path media), `alert` (status kirim Telegram,
  `message_id`/`message_photo`/`ai_synced` untuk edit caption AI), `telegram_chat`.
- **Absensi**: `employee`, `shift`, `face_embedding`, `attendance_event`, `attendance_day`
  (status + `override_note`).
- **Monitoring**: `monitoring_sample` (7 hari), `health_alert`.
- **AI**: `event_ai` (caption/ask, pending/ok/failed, prompt, jawaban, model, actor, latency);
  `zone.ai_caption` default false dan `zone.ai_prompt` nullable (bawaan/kustom).
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
- Deteksi/tracking wajah tetap pada seluruh frame; polygon menyaring pusat bbox, bukan ROI crop.
  Motion gate bangun karena gerak dan terus memproses frame diam selama wajah masih terlihat.
  Ambang cosine dan gerbang kualitas tidak berubah pada siklus face gate refine.
- `transport/`: klien MQTT + antrean disk store-and-forward (event tidak hilang saat broker/API
  putus; backlog dilaporkan di heartbeat).
- Config push adalah snapshot penuh. Node membandingkan `CameraCfg` per kamera:
  `source_url`, `ai_fps`, `zones`, `confidence`, `motion`, dan `meters_per_pixel`.
  Config identik mempertahankan objek worker dan recorder yang hidup, kecuali kamera yang punya
  worker mati: kamera itu dimulai ulang (keadaan nyata ikut dibandingkan); kamera tanpa zona
  tetap dicatat sebagai diterapkan meskipun tidak memiliki worker.
- Kamera berubah memulai ulang worker detect dan face bersama recorder/ClipRing kamera itu;
  kamera lain tidak disentuh. Kamera dihapus dihentikan; kamera baru dimulai bila memiliki zona aktif.
  Stream kamera yang dimulai ulang tersambung kembali: terukur di `gspe-ai3` (2026-10-07) kamera dengan
  worker face saja kembali `streaming` pada heartbeat berikutnya (<10 detik); kamera dengan worker detect
  (memuat engine TensorRT) belum diukur. Clip aktif kamera tersebut dapat terpotong.
- Restart penuh berlaku pada config pertama, perubahan model/nms/conf/imgsz/`device` detector,
  perubahan `device` face, atau galat tak terduga dalam diff. Perubahan `FaceSettings`
  (lebar, skor, yaw, blur, jumlah frame) hanya merestart kamera yang memiliki worker face.
- Kamera yang gagal dimulai pada diff tidak dicatat di `_applied`, sehingga push berikutnya
  mencoba kembali, termasuk jika config kembali ke nilai sebelumnya. Antrean snapshot yang
  sudah tersedia digabung: hanya snapshot terakhir diterapkan, bukan setiap pesan satu per satu.
- Jalur diff mencatat `config applied: restarted [..], added [..], removed [..], unchanged N`
  dengan ID terurut. Jalur penuh tetap mencatat `started N worker(s) for M camera(s)`.
  Kontrak MQTT, heartbeat, dan `_camera_stats` tidak berubah. Status: kode lokal selesai,
  BELUM diuji di server nyata.
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

### Attendance evidence dan flag zona

Flag `record` dan `telegram_unknown` disimpan sebagai boolean di JSON behavior `attendance`,
tanpa migrasi. Key hilang atau `behaviors=null` memakai true; `direction` tetap wajib.
Backend memberi `employee_id`, `employee_name`, `face_score`, dan `match_reason` setelah
menghapus embedding dari payload tersimpan.

- `matched`: pencatatan baru, caption CHECK IN/OUT.
- `already_in`: entry kedua pada hari lokal yang sama, di luar cooldown **dan** karyawan tidak terlihat
  (event attendance mana pun, zona mana pun, ± `attendance_cooldown_min`) sebelumnya; bila masih terlihat
  → `cooldown` tanpa alert (anti-spam untuk orang yang menetap di area kamera). Payload memuat
  `first_entry_ts` ISO lokal dan `exit_ts` hanya bila ada exit dengan
  `first_entry_ts < exit_ts <= ts_event`. Tidak membuat AttendanceEvent/rekap baru;
  caption SUDAH CHECK IN.
- `detected`: wajah cocok di zona `record=false`, tanpa AttendanceEvent/recompute_day;
  dedup Event per (karyawan, zona), hanya evidence `detected` dalam jendela cooldown.
  Prafilter DB ±1 hari, waktu tepat dibandingkan di Python lewat `_local` agar SQLite
  naive dan Postgres aware konsisten. Caption TERDETEKSI — MASUK/KELUAR.
- `cooldown`: event tetap ada, tanpa alert. `no_match`: Unknown tetap Inbox;
  `telegram_unknown=false` menahan alert setelah saklar Telegram induk.

`matched`, `already_in`, dan `detected` melewati rate-limit generik; Unknown tetap
memakai bucket `attendance_unknown`. Tautan semua caption: `Lihat event`.

### Corong heartbeat face

Entri worker `face` pada heartbeat `cameras[]` membawa `funnel` per jendela:
`faces`, `rejects{zone,small,score,yaw,blur}`, `tracks_emitted`, `tracks_silent`,
`ttfg_median_s`. Faces/rejects dihitung per wajah yang dilacak per frame.
Silent hanya track yang pernah masuk zona tetapi tidak memiliki embedding lolos.
TTFG adalah median detik sejak track pertama masuk zona hingga embedding bagus pertama,
dibulatkan dua desimal; tanpa sampel bernilai null.

Reset menukar dictionary tanpa lock; selisih satu hitungan antar-thread diterima.
`fps` dan `motion_skip_pct` tetap pada entri yang sama, skip kini tersedia untuk face.
Worker detect tidak membawa funnel. API meneruskan dictionary pertama yang valid ke
`cameras[].ai.funnel` di `/api/v1/monitoring`; heartbeat lama tanpa field → null.
Tidak ada UI corong atau perubahan protokol event wajah dua fase.


### HTTP internal (node → API, `Authorization: Bearer NODE_API_KEY`)

- `POST /internal/nodes/{id}/events` — ingest event.
- `POST /internal/nodes/{id}/blobs?kind=clip|snapshot|crop|face` — upload media (maks 200 MB).
- `POST /internal/nodes/{id}/heartbeat`.

### WebSocket `/api/v1/ws/events` (API → browser)

- Event baru (`EventOut`): Inbox, lonceng notifikasi, outline tile Live View, banner node offline.
- `{kind: "alert", event_id, status}`: status Telegram realtime di Inbox.
- `{kind: "ai", event_id, status}`: detail event memuat ulang caption/riwayat; tidak memicu notifikasi alert.
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
4. **Caption AI → Telegram**: dispatcher menyimpan `message_id` saat alert `sent`, lalu
   `alert_ai.sync_ai_caption` (idempoten, dipanggil dispatcher dan `AiWorker`) mengedit
   caption alert ber-foto untuk menambah baris `🤖 AI:`; urutan apa pun menghasilkan tepat
   satu edit, tanpa mengubah status alert/caption/antrean.
4. **Enrollment**: 3 foto per karyawan diunggah → API meng-embed dengan InsightFace
   `buffalo_l` → `face_embedding` → galeri di-refresh.
5. **Monitoring**: heartbeat → `node.hw`/`node.modules` (kondisi saat ini) → `HistorySampler`
   (tren 7 hari) → `health_alerts` (alert kesehatan, event `system` `payload.kind="health"`).
6. **Retensi**: sweep harian menghapus media sesuai `clip_days`/`snapshot_days`/`attendance_days`;
   event yang kehilangan media terakhirnya ikut dihapus (kecuali `system`).
   Retensi/cleanup menghapus `event_ai` → `alert` → `event` secara eksplisit, tanpa cascade FK AI.

### AI advisory: caption otomatis dan Tanya AI

`events_consumer` hanya menambah dua hook: setelah event/alert diproses dan setelah path snapshot
di-commit. Hook terisolasi `try/except`; antrean/thread AI tidak menghalangi ingest, broadcast, atau Telegram.
Caption membutuhkan global enabled, tipe didukung, zona on, snapshot tersedia, belum ada caption,
dan lolos throttle zona. Antrean penuh membuang pekerjaan tanpa baris pending. Thread memakai Session
sendiri per item; idle tidak membuka DB. Recovery mengantre ulang pending ≤10 menit, sisanya failed.

`GET /api/v1/ai/status` memberi enabled, preset, dan prompt bawaan tanpa rahasia.
`GET /api/v1/events/{id}/ai` memberi caption dan 20 ask terbaru.
`POST /api/v1/events/{id}/ask` memakai auth semua role, id positif int4, tepat satu question/preset,
history ≤6 giliran, q/a ≤2000 karakter. `ask_ai` memeriksa enabled → tipe → input → media →
cache preset sukses → kuota user → frame → slot LLM → chat. Cache tidak memakai kuota.
Klip hilang/gagal jatuh ke snapshot (`frames_used=0`), kecuali preset temporal (409 `clip_unavailable`).
Respons successful/failed diaudit di `event_ai`; hasil ask tidak memperbarui caption.

`llm_client` mengirim chat OpenAI-compatible, timeout 60/120 detik, dan semaphore bersama default 2
(acquire maksimal 5 detik). Error/konten/model diredaksi dari kunci. `ai_media` membatasi path ke
STORAGE_ROOT termasuk symlink, JPEG sisi terpanjang ≤960; ffprobe/ffmpeg tanpa shell dan deadline
ekstraksi total 15 detik. Klip ≤30 detik menghasilkan 6 frame, selebihnya 12.
System prompt advisory, metadata allowlist, instruksi tipe/kustom, dan batas format selalu dikirim.

Satu proses API saja: admission lock, throttle, semaphore, dan kuota 6/menit/user tidak lintas proses.
Nilai awal `LLM_*`/`AI_QUEUE_MAX` berasal dari `secrets/llm.env`, diteruskan hanya ke `api`, tidak ke
retention atau vision. `llm_config` menyimpan override non-rahasia di `setting.llm` dan kunci
`llm_api_key` di `secret_store`; prioritas DB > env > default, tanpa migrasi. `apply(db)` dipanggil
saat startup (sebelum recovery AI) dan sesudah PUT untuk menimpa singleton `settings`. Hanya field
yang ada di DB/secret_store dan field yang pernah ditimpa disentuh; override yang dihapus kembali
ke nilai awal `_BASE`, DB kosong yang belum menimpa apa pun adalah no-op. Multi-worker perlu
memuat ulang per worker; konkurensi semaphore dan ukuran antrean tidak hot-reload.

`GET/PUT /api/v1/ai/settings` dan `POST /api/v1/ai/settings/test` memerlukan admin.
PUT parsial memvalidasi seluruh nilai efektif sebelum efek samping; `null` menghapus override.
Kunci tulis-saja tidak masuk DB/respons/log; audit hanya actor dan nama field. GET menampilkan
sumber DB/Env/Default serta batas restart-only. `llm_client.Connection` mengisolasi tes form
dari konfigurasi worker: teks lalu JPEG sintetis 64×64, timeout 30 detik per panggilan, tanpa slot
worker dan tanpa simpan. Galat meredaksi kunci form maupun tersimpan; teks berhasil dan vision
ditolak dilaporkan terpisah (`ok=true`, `vision_ok=false`).
Global disabled tidak membuat panggilan caption/ask, status false, ask 503; tes koneksi admin
tetap dapat mencoba form yang belum diaktifkan. Endpoint LLM menerima gambar; kebijakan
penyimpanan/pelatihan pemilik wajib dikonfirmasi sebelum produksi.

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
