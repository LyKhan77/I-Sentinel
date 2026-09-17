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

Status: pre-release `0.x`, Fase 0–4e done, Fase 5 (hardening) in progress.
Deployment target today is one dev/prod server (`gspe-ai3`); Jetson Orin Nano edge
split is planned (Fase E).

## 2. Tech Stack

| Layer | Stack |
|---|---|
| Backend | Python ≥3.11, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2 / pydantic-settings, PyJWT (HS256, httpOnly cookie), bcrypt, `paho-mqtt`, `httpx`, PostgreSQL (`psycopg` 3) |
| Vision node | Python ≥3.11, NumPy, `opencv-python-headless`, Ultralytics YOLO26s (TensorRT `.engine`, FP16 640px), ByteTrack, `paho-mqtt` + disk-backed store-and-forward queue |
| Frontend | React 19, TypeScript, Vite 8, React Router 7, IBM Carbon (`@carbon/react`), SCSS, Vitest + Testing Library, oxlint |
| Media | `go2rtc` (WebRTC/MSE/HLS/snapshot), ffmpeg-based recorder |
| Messaging | Mosquitto MQTT (events, heartbeat, config push, LWT) |
| Ops | systemd units, `deploy/bootstrap.sh`, retention timer, `.env`-only secrets |

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
  models/snapshots`), retention sweep service + systemd timer (`RETENTION_DAYS`).
- **Realtime UI**: WebSocket hub (`app/ws/hub.py`) + `src/api/useWs.ts`.

## 4. Project Structure

```
I-Sentinel/
├── backend/                     # FastAPI server (central)
│   ├── app/
│   │   ├── main.py              # app factory, lifespan, router wiring, admin bootstrap
│   │   ├── api/                 # routers: auth, users, cameras, stream_sources,
│   │   │                        #   credential_profiles, location_groups, probe, live,
│   │   │                        #   nodes, zones, events, alerts, telegram, storage,
│   │   │                        #   employees, shifts, enrollment, attendance, deps
│   │   ├── core/                # config (env), security (jwt/bcrypt), db session
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Pydantic contracts
│   │   ├── services/            # probe, stream_endpoint, go2rtc, config_push, ingest,
│   │   │                        #   events_consumer, face, attendance, alerting, retention
│   │   └── ws/hub.py            # websocket fan-out
│   ├── alembic/versions/        # migrations (latest: 0007_camera_management_expand)
│   ├── scripts/                 # camera_management_migrate, retention_sweep,
│   │                            #   download_face_models
│   └── tests/                   # pytest (marker `gpu` = needs CUDA/RTSP)
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
├── deploy/                      # go2rtc, mosquitto, systemd units, bootstrap.sh,
│                                #   loadtest/resilience.sh, vision.env.example
├── docs/
│   ├── plans/                   # design + per-phase plans (00-master … 07-edge-jetson)
│   ├── superpowers/{plans,specs}/  # Superpowers-generated plans & specs (record only)
│   ├── runbooks/                # operational procedures + rollback
│   └── evidence/                # screenshots / measured proof
├── mockup-ui/                   # approved HTML mockups (UI source of truth)
├── README.md  DESIGN.md  ROADMAP.md  CHANGELOG.md  .env.example
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

Server (dev/prod, SSH):
```bash
ssh gspe-ai3
cd /home/gspe-ai3/project_cv/I-Sentinel && git pull
./deploy/bootstrap.sh                 # venv + install + alembic + systemd install (no start)
# NOTE: no passwordless sudo on gspe-ai3. Restart a service by killing its
# cgroup procs; units use Restart=always:
kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs)
curl -s localhost:8000/api/v1/health  # expect {"status":"ok"}
journalctl -u isentinel-api -n 50 --no-pager
bash deploy/loadtest/resilience.sh    # 30+ camera load / resilience check
```

Server facts: host `gspe-ai3`, LAN `192.168.2.133`, VPN `10.8.0.162`, project
`/home/gspe-ai3/project_cv/I-Sentinel`, runtime data in the sibling
`I-Sentinel-data/{api,vision}`. Credentials live in `temp/data/server-info.txt`
(gitignored) and the server `.env` — never commit them, never paste them into
docs, commits, or code. Units in `deploy/systemd/` still carry `/opt/isentinel` +
`User=isentinel` while the running ones use the `project_cv` path + `User=gspe-ai3`;
reconciling them is Fase 5 Task 12 (`docs/plans/06-fase-5-hardening.md`), so treat
the repo units as not-yet-authoritative.

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

## 7. Workflow

1. **Read state first**: `.cooper/context/` checkpoints, `ROADMAP.md`, then the
   relevant `docs/plans/` or `docs/superpowers/plans/` file. Don't reconstruct state
   from memory or a compaction summary.
2. **Plan before editing** for anything multi-file: state assumptions, success
   criteria, and how each step will be verified. Save the plan to
   `docs/superpowers/plans/` (spec to `docs/superpowers/specs/`) using the
   `Superpowers` skill, and get it validated by the user.
3. **Branch**: work off a feature branch (`feat/<slug>`, current:
   `feat/camera-management-b-prime`). Propose a new branch for any feature or
   discussion outside the current context.
4. **Implement surgically**: smallest diff that solves the request; reuse existing
   helpers; no speculative abstractions.
5. **Verify with evidence**: backend `pytest -m "not gpu"`, `npx vitest run`,
   `npm run build`; UI changes verified against the running app (screenshot into
   `docs/evidence/`); migrations checked for idempotency. `[x]` only with pasted
   output/numbers.
6. **Commit per functional change** (Conventional Commits) and record it in
   `CHANGELOG.md`: context, files changed, evidence, impact, rollback. Update
   `.gitignore` when new generated/secret files appear. Don't `push` unless asked.
7. **Update docs** (`README.md`, `DESIGN.md`, `ROADMAP.md`, runbooks) whenever key
   features or the app workflow change. Finish with a summary to the user.

## 8. Current State

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
