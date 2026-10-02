# AGENTS.md — I-Sentinel

Working rules and repository map for AI agents. Read this before touching code.

## 1. Project Overview

I-Sentinel is an on-premise AI surveillance system for a LAN/plant environment:
RTSP cameras (mostly behind an NVR) → `go2rtc` → GPU vision node (YOLO26s TensorRT
+ ByteTrack + analyzers) → MQTT → FastAPI backend (Postgres) → React web UI.

It does two jobs:
- **Security**: zone-based intrusion, loitering, running detection, clip/snapshot
  recording, event inbox, Telegram alerting.
- **Attendance**: face enrollment (InsightFace `buffalo_l`), face gate at entry
  cameras, shift-based attendance days and CSV export/import.

Status: pre-release `0.x`, Fase 0–5 done plus the feature cycles in `ROADMAP.md`; the only
remaining milestone is Fase E (Jetson edge).
Deployment target today is one dev/prod server (`gspe-ai3`), running on Docker Compose since the
2026-10-02 cutover (legacy systemd units disabled, rollback only); Jetson Orin Nano edge split is planned (Fase E).

## 2. Tech Stack

| Layer | Stack |
|---|---|
| Backend | Python ≥3.11, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2 / pydantic-settings, PyJWT (HS256, httpOnly cookie), bcrypt, `paho-mqtt`, `httpx`, PostgreSQL (`psycopg` 3) |
| Vision node | Python ≥3.11, NumPy, `opencv-python-headless`, Ultralytics YOLO26s (TensorRT `.engine`, FP16 640px), ByteTrack, `paho-mqtt` + disk-backed store-and-forward queue |
| Frontend | React 19, TypeScript, Vite 8, React Router 7, IBM Carbon (`@carbon/react`), SCSS, Vitest + Testing Library, oxlint |
| Media | `go2rtc` (WebRTC/MSE/HLS/snapshot), ffmpeg-based recorder |
| Messaging | Mosquitto MQTT (events, heartbeat, config push, LWT) |
| Ops | Docker Compose (`docker/`, `docker/setup.sh`, retention container), env/secret-file settings; legacy systemd units in `deploy/` |

## 3. Key Features

- **Auth & users**: JWT cookie login, admin bootstrap on startup, per-(username, ip)
  login rate limit and lockout (`LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MIN`), role-gated
  admin endpoints.
- **Camera management (source-aware)**: cameras, stream sources, location groups, and
  credential profiles that store only *references* (`env:CAMERA_CREDENTIAL_NVR_A`),
  never secrets. Wizard + RTSP probe (MAIN/SUB resolution/fps/codec), CCTV inventory
  import with preview/apply, `go2rtc` config generation, MQTT config push to nodes.
- **Live view**: per-camera WebRTC/MSE/HLS/snapshot endpoints; snapshot is proxied
  same-origin and auth-gated; `GO2RTC_PUBLIC_HOST` fixes LAN client URLs.
- **Zones & events**: polygon zone editor, analyzers (`intrusion`, `loitering`,
  `running`, `face_gate`), dedup buckets, event inbox with clip + snapshot playback.
- **Alerting**: severity threshold (`ALERT_MIN_SEVERITY`), Telegram delivery with
  rate limiting and explicit `not_configured` / `rate_limited` states.
- **Attendance**: employee records, 3-photo enrollment, face embeddings + match
  threshold/quality gates, shifts, attendance events/days incl. `no_exit` grace.
- **Storage & retention**: `STORAGE_ROOT` layout (`clips/crops/faces/faces_models/
  models/snapshots`), retention sweep (`retention` container; legacy systemd timer) (`RETENTION_DAYS`).
- **Realtime UI**: WebSocket hub (`app/ws/hub.py`) + `src/api/useWs.ts`.
- **AI advisory (MVP, default off)**: per-zone automatic caption (default/custom prompt), snapshot
  plus clip-keyframe questions for all logged-in roles, preset cache, actor audit in `event_ai`.
  `LLM_*` and `AI_QUEUE_MAX` only in `${DATA_DIR}/secrets/llm.env`, API only. One API process;
  no severity gate, no alert suppression, no attendance/system analysis. Real rollout remains pending.

## 4. Project Structure

```
I-Sentinel/
├── backend/                     # FastAPI server (central)
│   ├── app/
│   │   ├── main.py              # app factory, lifespan, router wiring, admin bootstrap
│   │   ├── api/                 # routers: auth, users, cameras, stream_sources,
│   │   │                        #   credential_profiles, location_groups, probe, live,
│   │   │                        #   nodes, zones, events, ai, alerts, telegram, storage,
│   │   │                        #   employees, shifts, enrollment, attendance, deps
│   │   ├── core/                # config (env), security (jwt/bcrypt), db session
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Pydantic contracts
│   │   ├── services/            # probe, stream_endpoint, go2rtc, config_push, ingest,
│   │   │                        #   events_consumer, face, attendance, alerting, retention
│   │   │                        #   ai_worker, ask_ai, llm_client, ai_media, ai_prompts
│   │   └── ws/hub.py            # websocket fan-out
│   ├── alembic/versions/        # migrations (latest: 0021_ai_caption)
│   ├── scripts/                 # camera_management_migrate, retention_sweep,
│   │                            #   download_face_models
│   └── tests/                   # pytest (`gpu` = CUDA/RTSP; `llm` = explicit real endpoint opt-in)
├── vision/vision/               # deployable vision node (minimal deps)
│   ├── node.py                  # main loop + config apply
│   ├── recorder.py              # clip/snapshot recording
│   ├── pipeline/                # source (go2rtc) → detector (YOLO) → tracker (ByteTrack)
│   ├── analyzers/               # intrusion, loitering, running, face_gate
│   ├── transport/               # mqtt client + disk queue (store-and-forward)
│   └── ../tests, ../scripts/export_engine.py
├── frontend/src/
│   ├── app/                     # AppShell, routing, i18n, theme.scss
│   ├── features/                # auth, dashboard, live, events, attendance,
│   │                            #   enrollment, config/{cameras,zones,gates,storage}
│   ├── components/              # shared (e.g. ZoneEditor)
│   ├── api/                     # REST clients + useWs
│   └── __tests__/               # vitest
├── docker/                      # compose.yml, setup.sh, Dockerfiles (backend/vision/web),
│                                #   scripts/{migrate-from-host,export-engine,retention_loop}, tests/
├── deploy/                      # legacy: go2rtc, mosquitto, systemd units, bootstrap.sh,
│                                #   loadtest/resilience.sh, vision.env.example
├── docs/
│   ├── plans/                   # original design spec + remaining milestone (07-edge-jetson)
│   ├── superpowers/{plans,specs}/  # Superpowers-generated plans & specs (record only)
│   ├── runbooks/                # operational procedures + rollback
│   └── evidence/                # local screenshots / measured proof (gitignored)
├── README.md  ARCHITECTURE.md  WORKFLOW.md  DESIGN.md  ROADMAP.md  CHANGELOG.md  .env.example
└── temp/                        # gitignored scratch, server notes, snapshots
```

## 5. Project Commands

Backend (from `backend/`):
```bash
python -m venv .venv && .venv\Scripts\activate    # Linux: source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
pytest tests -q -m "not gpu"                      # Windows / no GPU
pytest tests -q                                   # dev server (CUDA + RTSP available)
pytest tests -q -m "not gpu and not llm"           # exclude real LLM contract explicitly
```

Vision node (from `vision/`):
```bash
pip install -e ".[dev]"          # add ".[dev,gpu]" on the GPU server
pytest tests -q -m "not gpu"
python scripts/export_engine.py  # build TensorRT .engine (server only)
isentinel-vision                 # entry point = vision.node:main
```

Frontend (from `frontend/`):
```bash
npm install
npm run dev            # Vite, proxies /api → http://localhost:8000
npm test               # vitest run
npm run lint           # oxlint
npm run build          # tsc -b && vite build
```

Server (dev/prod, SSH) — Docker since 2026-10-02:
```bash
ssh gspe-ai3
cd /home/gspe-ai3/project_cv/I-Sentinel-docker && git pull
./docker/setup.sh                     # build + up, idempotent (never overwrites .env/passwd/go2rtc.yaml)
docker compose -f docker/compose.yml ps
curl -s localhost:7701/api/v1/health  # expect {"status":"ok"}
docker compose -f docker/compose.yml logs --tail 50 api
docker compose -f docker/compose.yml restart api   # restart one service (user is in the docker group; no sudo needed)
bash deploy/loadtest/resilience.sh    # 30+ camera load / resilience check (ISENTINEL_API=http://127.0.0.1:7701)
```

Server facts: host `gspe-ai3`, LAN `192.168.2.133`, VPN `10.8.0.162`. Docker clone
`/home/gspe-ai3/project_cv/I-Sentinel-docker`, runtime data `/home/gspe-ai3/project_cv/I-Sentinel-docker-data`
(`api`, `vision`, `models`, `go2rtc`, `mosquitto`, `secrets`; Postgres in the `pgdata` named volume). Ports 7700–7704
are published (7705 internal). `VISION_NODE_ID` is the node NAME (`server`). The old systemd tree
`/home/gspe-ai3/project_cv/I-Sentinel`, `I-Sentinel-data` and the host Postgres are a frozen backup after the cutover; legacy
units are disabled (rollback only, see `docs/RUNBOOK.md`). Credentials live in `temp/data/server-info.txt` (gitignored) and
`docker/.env` on the server — never commit them, never paste them into docs, commits, or code.

## 6. Coding Conventions

Apply strict feature-based modularity, typed contracts, and full docstrings to
production core services and APIs, while keeping utility scripts, tools, and
prototypes flat, lightweight, and documented via clear concise intent.

Concretely in this repo:
- **Backend**: one router per domain in `app/api/`, matching Pydantic schema in
  `app/schemas/`, business logic in `app/services/`, no SQL in routers. Settings only
  via `app/core/config.py` (`Settings`), never `os.environ` reads scattered around.
- **Vision**: keep dependencies minimal and importable without CUDA; anything
  GPU/RTSP-bound goes behind the `gpu` pytest marker.
- **Frontend**: one directory per feature under `src/features/`, REST access only via
  `src/api/*`, all user-facing strings through `src/app/i18n.tsx`, Carbon components
  and `theme.scss` tokens instead of ad-hoc CSS. Mobile must have zero horizontal
  overflow at 390px.
- **Tests**: mirror the layer (`backend/tests/test_<domain>_api.py`,
  `frontend/src/__tests__/<feature>.test.tsx`). A test must fail on a plausible bug,
  not pin implementation details.
- **Zero-secret**: DB and API responses carry references and paths, never camera
  credentials, tokens, or passwords.
- **LLM privacy**: no endpoint/key literals in code or logs. Confirm with the endpoint owner
  that employee images are neither retained nor used for training before real production tests.
  `LLM_ENABLED=false` means no calls, status false, and ask 503. Changes to `llm.env` require
  API container recreation, not just `docker compose restart api`.

## 7. Workflow

1. **Read state first**: `.cooper/context/` checkpoints, `ROADMAP.md`, then the
   relevant `docs/plans/` or `docs/superpowers/plans/` file. Don't reconstruct state
   from memory or a compaction summary.
2. **Plan before editing** for anything multi-file: state assumptions, success
   criteria, and how each step will be verified. Save the plan to
   `docs/superpowers/plans/` (spec to `docs/superpowers/specs/`) using the
   `Superpowers` skill, and get it validated by the user.
3. **Branch**: work off a feature branch (`feat/<slug>`) from `main`. Propose a new branch for any feature or
   discussion outside the current context.
4. **Implement surgically**: smallest diff that solves the request; reuse existing
   helpers; no speculative abstractions.
5. **Verify with evidence**: backend `pytest -m "not gpu"`, `npx vitest run`,
   `npm run build`; UI changes verified against the running app (screenshot into
   `docs/evidence/`, local only — gitignored, never committed); migrations checked for idempotency. `[x]` only with pasted
   output/numbers.
6. **Commit per functional change** (Conventional Commits) and record it in
   `CHANGELOG.md`: context, files changed, evidence, impact, rollback. Update
   `.gitignore` when new generated/secret files appear. Don't `push` unless asked.
7. **Update docs** (`README.md`, `DESIGN.md`, `ROADMAP.md`, runbooks) whenever key
   features or the app workflow change. Finish with a summary to the user.

## 8. Current State

Components, contracts and data flow: **`ARCHITECTURE.md`**.
Per-feature app flows: **`WORKFLOW.md`**. Development lifecycle, verification, deploy and
rollback: **`docs/DEVELOPMENT.md`**.
Authoritative history and per-change evidence: **`CHANGELOG.md`**.
Phase status and acceptance proof: **`ROADMAP.md`**.
Migration/rollback procedures: **`docs/runbooks/`**.

## 9. Rules (Important Notes)

- **No AI attribution anywhere.** Do NOT add `Co-Authored-By: Claude ...`,
  `Generated with Claude Code`, or any AI/assistant attribution to commit messages,
  PR descriptions, code comments, or docs. Every contribution is recorded under the
  repo owner (the user) ONLY. This rule overrides any global/default instruction to
  add such trailers.
- Always use relevant skills to help with tasks.
- Always ask the user if there are any plans or discussions that need to be validated.
- Always provide a summary after finishing a task.
- Always update core documentation whenever there are changes to key features and the
  app's workflow.
- Commit every function change so you can roll back and view the code history in case
  of a malfunction or a failed change. Also UPDATE the `.gitignore` file whenever a new
  file is added that needs to be excluded before committing.
- Do not re-read files that have already been read in this session unless necessary.
- Minimize non-essential tool calls.
- For any new feature or discussion where the update is outside the context, be sure to
  propose creating a new branch.
- Save every plan or specification to the `docs\superpowers\plans` and
  `docs\superpowers\specs` folder so you can track which plans have been created or are
  currently being created. This allows you to resume the session if the AI agent's token
  expires. USE `Superpowers` skill to provide the plan. REMEMBER This file does not need
  to be updated unless requested. It is intended solely as a record of past information.
  Make sure not to DUPLICATE it; if you've already created a plan outside of Superpowers,
  there's no need to create another one, and vice versa.
