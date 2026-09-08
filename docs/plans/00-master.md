# I-Sentinel — Master Plan

> **For agentic workers:** Rencana ini dipecah per milestone. Kerjakan SATU file
> milestone sampai selesai (semua checkbox `[x]` + bukti), lalu kembangkan brief
> milestone berikutnya menjadi plan detail sebelum mengerjakannya.
> REQUIRED SUB-SKILL: superpowers:subagent-driven-development atau superpowers:executing-plans.

**Goal:** AI surveillance CCTV (absensi wajah, person tracking, behavior, zona,
clip/snapshot, alert Telegram, UI Carbon dark) untuk 30+ kamera, server GPU + edge Jetson.

**Architecture:** Lihat spec `docs/plans/2026-09-08-isentinel-design.md` §2 — go2rtc
gerbang RTSP tunggal; vision-node (custom Python: YOLO11s TensorRT FP16 + ByteTrack +
analyzer modular); event via MQTT QoS1 (Mosquitto); FastAPI + PostgreSQL + disk media;
React + TS + @carbon/react (Gray-100 dark, bilingual, tanpa emoji).

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy 2 + Alembic / paho-mqtt /
Ultralytics + TensorRT / ByteTrack / InsightFace / go2rtc / Mosquitto /
React 18 + TypeScript + Vite + @carbon/react / pytest / vitest.

**Spec:** `docs/plans/2026-09-08-isentinel-design.md`

## Global Constraints

- Semua keputusan requirement terkunci di spec §1; perubahan = update spec dulu.
- UI: IBM Carbon Gray-100 dark, Plex Sans, corner 0px, tanpa emoji, sidebar collapsible, bahasa ID/EN toggle.
- AI dari substream (default 5 FPS, override per kamera); mainstream hanya untuk clip event (pre 8s / post 30s default).
- Logic inti backend & vision HARUS testable tanpa GPU/RTSP (model & stream di-mock).
- Vision-node tidak boleh depend ke FastAPI/SQLAlchemy — kontrak hanya MQTT + HTTP upload.
- Zero-secret: kredensial kamera/Telegram hanya via env/config file; tidak pernah di commit/DB plaintext.
- Conventional Commits; setiap task berakhir dengan commit; test harus pass sebelum commit.
- Workflow dev: device coding = Windows ini (smoke test CPU saja); test GPU/RTSP di
  `gspe-ai3` via SSH (git pull → jalankan). GitHub = source of truth, tidak ada copy manual.
- Zona polygon tersimpan ternormalisasi 0–1; min 3 titik; editor tutup via klik titik awal.

## Struktur Proyek (monorepo)

```
isentinel/
├── backend/                  # FastAPI server pusat
│   ├── app/
│   │   ├── main.py
│   │   ├── api/              # routers: auth, cameras, zones, nodes, gates,
│   │   │                     #   detection, employees, attendance, events, alerts,
│   │   │                     #   telegram, users, settings
│   │   ├── core/             # config(env), security(jwt), db
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic
│   │   ├── services/         # probe, attendance, alerting, face, events_consumer,
│   │   │                     #   recorder, retention
│   │   └── ws/               # websocket hub
│   └── tests/
├── vision/                   # vision-node (deployable ke Jetson, minimal deps)
│   ├── node.py
│   ├── pipeline/             # source(go2rtc) → detector(YOLO) → tracker(ByteTrack) → emit
│   ├── analyzers/            # intrusion.py, loitering.py, running.py, face_gate.py
│   ├── transport/            # mqtt client + disk queue store-and-forward
│   └── tests/
├── frontend/src/
│   ├── app/                  # shell, routing, i18n
│   ├── features/             # dashboard, live, events, attendance, enrollment, config
│   ├── components/
│   └── api/                  # REST client + WS
├── deploy/
│   ├── go2rtc/go2rtc.yaml
│   ├── mosquitto/mosquitto.conf
│   ├── systemd/              # isentinel-api.service, isentinel-recorder.service,
│   │                         #   vision-node.service, isentinel-retention.service
│   └── sql/                  # alembic migrations
├── docs/plans/               # spec + rencana per milestone (file ini + anak-anaknya)
├── mockup-ui/                # mockup disetujui
└── README.md
```

## Kontrak Vision ↔ Backend (kunci — didefinisikan sekali di Fase 0)

### MQTT (Mosquitto, host server)

| Topic | Arah | Payload |
|---|---|---|
| `isentinel/events` | vision → backend | EventEvent JSON (di bawah), QoS 1 |
| `isentinel/nodes/{node_id}/heartbeat` | vision → backend | `{ts, cpu, gpu_mem, cameras: [id…]}` tiap 10 s |
| `isentinel/nodes/{node_id}/lwt` | broker otomatis | LWT: `{"status":"offline"}` (retained) |
| `isentinel/config/{node_id}` | backend → vision | config penuh node (kamera+zona+analyzer), retained |

### Event JSON (skema tunggal, semua analyzer)

```json
{
  "event_id": "uuid4",
  "type": "intrusion | loitering | running | attendance | system",
  "node_id": "server",
  "camera_id": 7,
  "zone_id": 12,
  "severity": "critical | warning | info",
  "ts_event": "2026-09-08T08:31:22.412+07:00",
  "payload": {
    "track_id": 13,
    "confidence": 0.95,
    "speed_mps": 3.2,
    "duration_s": 31.5,
    "direction": "entry",
    "employee_id": 44,
    "face_score": 0.87,
    "bbox_norm": [0.42, 0.31, 0.55, 0.78],
    "snapshot_crop": "crops/2026/09/08/<event_id>.jpg"
  },
  "dedup_key": "<camera_id>:<zone_id>:<type>:<track_id>:<ts_bucket>"
}
```

### HTTP blob upload (vision → backend, dengan API key per node)

```
POST /internal/nodes/{node_id}/blobs?kind=crop|clip|face
  Authorization: Bearer <NODE_API_KEY>
  body: binary (jpeg/mp4), header X-Event-Id untuk asosiasi
  → 200 {"path": "crops/2026/09/08/<uuid>.jpg"}   # path relatif storage root
```

- Backend menyimpan file ke path tahun/bulan/hari (retensi 30 hari mudah di-sweep).
- Idempotensi: `events.event_id` UNIQUE; duplikat QoS1 → ignored (bukan error).

### Storage layout (disk server)

```
/data/isentinel/clips/YYYY/MM/DD/<event_id>.mp4
/data/isentinel/snapshots/YYYY/MM/DD/<event_id>.jpg
/data/isentinel/crops/YYYY/MM/DD/<event_id>.jpg
/data/isentinel/faces/<employee_id>/<uuid>.jpg
```

### Env vars (`.env`, di-gitignore; template di `.env.example`)

```
DATABASE_URL=postgresql+psycopg://isentinel:...@localhost/isentinel
JWT_SECRET=...
NODE_API_KEY=...
TELEGRAM_BOT_TOKEN=...
CAM_USERNAME=...            # kredensial kamera default (override per kamera bisa)
CAM_PASSWORD=...
STORAGE_ROOT=/data/isentinel
MQTT_URL=localhost:1883
GO2RTC_URL=http://localhost:1984
RETENTION_DAYS=30
```

## Workflow Dev & Testing

- **Lokal (Windows ini):** kode + unit test CPU (`pytest backend/tests`, `pytest vision/tests`
  tanpa `-m gpu`, `vitest frontend`). Smoke test saja — tidak ada GPU/RTSP.
- **Server dev (`gspe-ai3`):** semua test integrasi (TensorRT, RTSP, go2rtc, MQTT end-to-end).
  Alur: commit+push → `ssh gspe-ai3` → `git pull` → jalankan test/layanan → hasil dilaporkan.
- Marker pytest: `@pytest.mark.gpu` untuk test yang butuh CUDA; default run = CPU-only.
- Setiap milestone berakhir dengan demo di server dev + catatan bukti di plan milestone.

## Milestone Index

| File | Isi | Status |
|---|---|---|
| `01-fase-0-skeleton.md` | Monorepo + backend skeleton + auth + kamera CRUD/probe + frontend shell/login/kamera + deploy configs | **PLAN DETAIL SIAP** |
| `02-fase-1-vision-inti.md` | Pipeline deteksi+tracking, MQTT event, live view, dashboard tile | brief |
| `03-fase-2-zona-events.md` | Zona + editor polygon, intrusion, clips/snapshots, web inbox | brief |
| `04-fase-3-analyzers-alerting.md` | Loitering, running, Telegram + rate-limit | brief |
| `05-fase-4-absensi.md` | Enrollment, face match, gate entry/exit, shift/telat, export/import | brief |
| `06-fase-5-hardening.md` | Retensi 30 hari, uji beban 30 stream sintetis, docs | brief |
| `07-edge-jetson.md` | Migrasi vision-node ke Orin Nano, store-and-forward nyata | brief (nanti) |

Brief → dikembangkan jadi plan detail (format sama dengan Fase 0) saat milestone
sebelumnya selesai. Alasan: keputusan implementasi dari fase sebelumnya mengubah
detail fase berikutnya; plan yang ditulis terlalu awal pasti basi.
