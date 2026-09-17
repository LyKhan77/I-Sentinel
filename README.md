# I-Sentinel

Sistem surveillance AI: FastAPI backend + vision-node + frontend.

## Peta Folder

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
├── frontend/                 # React 19 + Vite + Carbon (9 halaman)
│   ├── src/
│   │   ├── app/              # shell, routing, i18n
│   │   ├── features/         # dashboard, live, events, attendance, enrollment, config
│   │   ├── components/
│   │   └── api/              # REST client + WS
├── deploy/
│   ├── go2rtc/go2rtc.example.yaml   # template; salin ke go2rtc.yaml (gitignored, isi kredensial RTSP)
│   ├── mosquitto/mosquitto.conf
│   ├── systemd/              # isentinel-api.service, isentinel-recorder.service,
│   │                         #   vision-node.service, isentinel-retention.service
│   └── sql/                  # alembic migrations
├── docs/plans/               # spec + rencana per milestone
├── mockup-ui/                # mockup disetujui
└── README.md
```

## Run (dev lokal)

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Frontend (dev server dengan proxy ke API):

```bash
cd frontend
npm install
npm run dev
npm test          # vitest run
```

## Run (server dev)

```bash
ssh gspe-ai3
cd /home/gspe-ai3/project_cv/I-Sentinel && git pull
./deploy/bootstrap.sh
# isi .env di root project (DATABASE_URL postgres, JWT_SECRET, ADMIN_PASSWORD, CAM_USERNAME/PASSWORD)
sudo systemctl start isentinel-api
curl -s localhost:8000/api/v1/health
```

`bootstrap.sh` membuat venv, install `backend[dev]`, `alembic upgrade head`, menyalin unit systemd ke `/etc/systemd/system/`, lalu daemon-reload + enable (tidak start).

Catatan: unit systemd di `deploy/systemd/` masih memakai `/opt/isentinel` +
`User=isentinel`, sedangkan yang berjalan di `gspe-ai3` memakai
`/home/gspe-ai3/project_cv/I-Sentinel` + `User=gspe-ai3`. Rekonsiliasi = Fase 5
Task 12 (`docs/plans/06-fase-5-hardening.md`). `sudo` tanpa password tidak
tersedia di server, jadi restart service dilakukan lewat
`kill $(cat /sys/fs/cgroup/system.slice/<unit>.service/cgroup.procs)` (unit
memakai `Restart=always`).
