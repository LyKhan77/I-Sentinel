# I-Sentinel — Fase 0: Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Monorepo yang jalan: login (admin bootstrap), CRUD kamera + probe main/sub RTSP, frontend Carbon dark dengan shell + login + halaman kamera. Bukti Fase 0: login → tambah 1 kamera → hasil probe main & sub tampil.

**Architecture:** Backend FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL (unit test pakai SQLite in-memory). Frontend Vite + React + TS + @carbon/react (Gray-100 dark). Vision-node hanya stub di Fase 0. Deploy configs (go2rtc, mosquitto, systemd) disiapkan.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, psycopg, PyJWT, passlib[bcrypt], pydantic-settings, pytest · Node 20, Vite 5, React 18, @carbon/react, react-router-dom, vitest + @testing-library/react.

**Spec:** `docs/plans/2026-09-08-isentinel-design.md` · Master plan: `docs/plans/00-master.md`

## Global Constraints

- Lihat master plan `00-master.md` §Global Constraints — berlaku semua.
- Fase 0 khusus: tidak ada MQTT/vision runtime; probe = ffprobe + path umum (ONVIF fallback best-effort).
- Unit test CPU-only harus pass di Windows ini (tanpa PostgreSQL: SQLite in-memory; tanpa ffprobe: subprocess di-mock).
- DB naming: tabel singular (`user`, `camera`, `node`), snake_case. API prefix `/api/v1`.

---

### Task 1: Scaffolding monorepo

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/main.py` (stub), `backend/tests/__init__.py`
- Create: `vision/pyproject.toml`, `vision/README.md` (stub — runtime di Fase 1)
- Create: `.env.example`, `README.md`
- Create: `.gitignore` (sudah ada — tambah `frontend/node_modules`, `dist`, `.venv`, `*.egg-info`)

**Interfaces:**
- Produces: struktur folder sesuai master plan; `backend` & `vision` package terpisah.

- [ ] **Step 1: Buat folder + pyproject backend**

`backend/pyproject.toml`:
```toml
[project]
name = "isentinel-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlalchemy>=2.0",
  "alembic>=1.13",
  "psycopg[binary]>=3.2",
  "pyjwt>=2.9",
  "passlib[bcrypt]>=1.7",
  "pydantic-settings>=2.4",
  "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = ["pytest>=8", "httpx>=0.27"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["gpu: requires CUDA/RTSP (run on dev server)"]
```

`vision/pyproject.toml`:
```toml
[project]
name = "isentinel-vision"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["numpy>=1.26", "paho-mqtt>=2.1"]

[project.optional-dependencies]
dev = ["pytest>=8"]
gpu = ["ultralytics>=8.3", "onnxruntime-gpu>=1.19"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["gpu: requires CUDA/RTSP (run on dev server)"]
```

- [ ] **Step 2: Buat stub + README + .env.example**

`backend/app/main.py`:
```python
app = None  # digantikan di Task 2
```
`vision/README.md`: satu paragraf — "vision-node runtime, diimplementasi di Fase 1 (plan 02)."
`.env.example` — salin persis dari master plan §Env vars.
`README.md` — nama proyek, peta folder (salin dari master plan §Struktur), cara run dev (diisi Task 10).

- [ ] **Step 3: Install & verifikasi**

Run: `cd backend && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"` (Windows) / `pip install -e ".[dev]"` (server)
Expected: install sukses, `pytest` menemukan 0 test tanpa error.

- [ ] **Step 4: Commit**

```bash
git add backend vision .env.example README.md .gitignore
git commit -m "chore: monorepo scaffolding (backend, vision stub, frontend placeholder)"
```

---

### Task 2: Backend core — config, DB, Alembic

**Files:**
- Create: `backend/app/core/config.py`, `backend/app/core/db.py`, `backend/app/main.py` (ganti stub)
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/` (Kosong sampai Task 3)
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces: `app.core.config.settings` (pydantic-settings, fields sesuai .env.example), `app.core.db.engine`, `app.core.db.SessionLocal`, `app.core.db.get_db` (FastAPI dependency), `app.core.db.Base` (DeclarativeBase).

- [ ] **Step 1: Tulis test config (failing)**

`backend/tests/test_config.py`:
```python
import os
from app.core.config import Settings

def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    s = Settings()
    assert s.jwt_algorithm == "HS256"
    assert s.access_token_expire_min == 480
    assert s.retention_days == 30
    assert s.storage_root == "/data/isentinel"
```

- [ ] **Step 2: Run test — verify fail**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: FAIL (ModuleNotFoundError: app.core.config)

- [ ] **Step 3: Implement config + db**

`backend/app/core/config.py`:
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://isentinel:isentinel@localhost/isentinel"
    jwt_secret: str = "CHANGE_ME"
    jwt_algorithm: str = "HS256"
    access_token_expire_min: int = 480
    node_api_key: str = "CHANGE_ME"
    telegram_bot_token: str = ""
    cam_username: str = ""
    cam_password: str = ""
    storage_root: str = "/data/isentinel"
    mqtt_url: str = "localhost:1883"
    go2rtc_url: str = "http://localhost:1984"
    retention_days: int = 30
    admin_username: str = "admin"
    admin_password: str = ""   # wajib diisi di .env server; bootstrap gagal jelas bila kosong

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
```

`backend/app/core/db.py`:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings

class Base(DeclarativeBase): pass

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
```

`backend/app/main.py`:
```python
from fastapi import FastAPI
from app.core.config import settings

app = FastAPI(title="I-Sentinel API", version="0.1.0")

@app.get("/api/v1/health")
def health(): return {"status": "ok"}
```

Alembic: `cd backend && alembic init alembic` — lalu di `alembic/env.py` set:
```python
from app.core.db import Base
from app.core.config import settings
target_metadata = Base.metadata
# sqlalchemy.url dibaca dari settings.database_url (override alembic.ini)
```

- [ ] **Step 4: Run test — verify pass**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: backend core (settings, db, alembic, health endpoint)"
```

---

### Task 3: Models Fase 0 + migration awal

**Files:**
- Create: `backend/app/models/user.py`, `camera.py`, `node.py`, `setting.py`
- Create: `backend/alembic/versions/0001_initial.py`
- Test: `backend/tests/conftest.py`, `backend/tests/test_models.py`

**Interfaces:**
- Produces:
  - `User(id, username unique, password_hash, role: "admin"|"viewer", locale: "id"|"en" default "id")`
  - `Node(id, name unique, type: "server"|"edge", last_seen datetime null, status: "online"|"offline"|"unknown" default "unknown")`
  - `Camera(id, name, location, host, rtsp_main, rtsp_sub, node_id FK node.id, enabled bool default true, probe_main JSON null, probe_sub JSON null, status: "online"|"offline"|"unknown" default "unknown")`
  - `Setting(key PK, value JSON)`
- Constraint: `Camera.node_id` nullable FK ke `node`.

- [ ] **Step 1: conftest (SQLite in-memory) + test model roundtrip**

`backend/tests/conftest.py`:
```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.db import Base

@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
```

`backend/tests/test_models.py`:
```python
from app.models.user import User
from app.models.camera import Camera
from app.models.node import Node

def test_user_roundtrip(db):
    u = User(username="admin", password_hash="h", role="admin")
    db.add(u); db.commit()
    assert db.query(User).filter_by(username="admin").one().role == "admin"

def test_camera_belongs_to_node(db):
    n = Node(name="server", type="server"); db.add(n); db.commit()
    c = Camera(name="CAM-01", host="192.168.1.108", node_id=n.id,
               probe_main={"res": "2560x1440", "fps": 25, "codec": "h264"})
    db.add(c); db.commit()
    assert c.node.name == "server"
    assert c.probe_main["fps"] == 25
```

- [ ] **Step 2: Run — verify fail** (`cd backend && python -m pytest tests/test_models.py -v` → ModuleNotFoundError)

- [ ] **Step 3: Implement models**

`backend/app/models/user.py`:
```python
from datetime import datetime, timezone
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    locale: Mapped[str] = mapped_column(String(8), default="id")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```
(`camera.py`, `node.py`, `setting.py` pola sama; `camera.probe_main/probe_sub` = `Mapped[dict | None]` dengan `JSON`; `node.last_seen` nullable; semua ada `created_at`.)

`backend/app/models/__init__.py`:
```python
from app.models.user import User
from app.models.node import Node
from app.models.camera import Camera
from app.models.setting import Setting
```

- [ ] **Step 4: Migration — `cd backend && alembic revision --autogenerate -m "initial"` lalu edit revision id → `0001`; verifikasi offline SQL**

Run: `cd backend && python -m pytest tests/test_models.py -v` → PASS
Run (server, saat deploy): `alembic upgrade head` → tabel dibuat di PostgreSQL.

- [ ] **Step 5: Commit** — `git commit -m "feat: fase0 models (user, node, camera, setting) + initial migration"`

---

### Task 4: Security — hash + JWT + dependencies

**Files:**
- Create: `backend/app/core/security.py`
- Test: `backend/tests/test_security.py`

**Interfaces:**
- Produces: `hash_password(pw) -> str`, `verify_password(pw, hash) -> bool`, `create_access_token(user_id, role) -> str`, `decode_token(token) -> dict | None`, `get_current_user` (FastAPI dep → User atau 401), `require_admin` (dep → 403 bila role != admin).

- [ ] **Step 1: Failing test**

`backend/tests/test_security.py`:
```python
import pytest
from fastapi import HTTPException
from app.core.security import hash_password, verify_password, create_access_token, decode_token

def test_hash_roundtrip():
    h = hash_password("s3cret")
    assert h != "s3cret" and verify_password("s3cret", h) and not verify_password("wrong", h)

def test_token_roundtrip():
    t = create_access_token(1, "admin")
    d = decode_token(t)
    assert d["sub"] == "1" and d["role"] == "admin"

def test_bad_token_none():
    assert decode_token("garbage") is None
```

- [ ] **Step 2: Run — verify fail** → `cd backend && python -m pytest tests/test_security.py -v`

- [ ] **Step 3: Implement**

`backend/app/core/security.py`:
```python
import jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

pwd = CryptContext(schemes=["bcrypt"])
bearer = HTTPBearer(auto_error=False)

def hash_password(pw: str) -> str: return pwd.hash(pw)
def verify_password(pw: str, h: str) -> bool: return pwd.verify(pw, h)

def create_access_token(user_id: int, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_min)
    return jwt.encode({"sub": str(user_id), "role": role, "exp": exp}, settings.jwt_secret, settings.jwt_algorithm)

def decode_token(token: str) -> dict | None:
    try: return jwt.decode(token, settings.jwt_secret, [settings.jwt_algorithm])
    except jwt.PyJWTError: return None

```
Catatan: `get_current_user`/`require_admin` TIDAK di file ini — implementasi final di `app/api/deps.py` (Task 5), karena butuh `get_db`. Token dikirim via httpOnly cookie **dan** header Bearer (cookie untuk browser, header untuk test/API key).

- [ ] **Step 4: Run — verify pass** → pytest PASS

- [ ] **Step 5: Commit** — `git commit -m "feat: password hashing + JWT auth dependencies"`

---

### Task 5: Auth & users API + bootstrap admin

**Files:**
- Create: `backend/app/api/deps.py`, `backend/app/api/auth.py`, `backend/app/api/users.py`, `backend/app/schemas/user.py`
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**
- Produces:
  - `POST /api/v1/auth/login {username, password}` → `{token, user}` + Set-Cookie httpOnly; 401 bila salah
  - `GET /api/v1/auth/me` → `{id, username, role, locale}`
  - `PATCH /api/v1/auth/me {locale?}` → update locale sendiri
  - `GET/POST /api/v1/users` (admin), `PATCH/DELETE /api/v1/users/{id}` (admin; DELETE tolak bila admin terakhir)
  - Bootstrap: `startup` — bila tabel `user` kosong → buat admin dari `settings.admin_username/admin_password` (password kosong → log ERROR, skip)
- Schemas: `UserOut{id,username,role,locale}`, `LoginIn{username,password}`, `UserIn{username,password,role,locale}`.

- [ ] **Step 1: Failing test (TestClient + SQLite override)**

`backend/tests/test_auth_api.py`:
```python
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db, Base
from tests.conftest import *  # noqa

@pytest.fixture
def client(db, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:  # context manager memicu startup/bootstrap
        yield c
    app.dependency_overrides.clear()

def test_bootstrap_and_login(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert "isentinel_token" in r.cookies

def test_login_wrong_password(client):
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "x"}).status_code == 401

def test_me_requires_auth(client):
    assert client.get("/api/v1/auth/me").status_code == 401

def test_create_user_admin_only(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.post("/api/v1/users", json={"username": "v1", "password": "pw12345", "role": "viewer"}, headers=h).status_code == 200
    assert client.get("/api/v1/users").status_code == 401  # tanpa token

def test_delete_last_admin_blocked(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert client.delete(f"/api/v1/users/{me['id']}", headers=h).status_code == 409
```
Catatan conftest: override `settings.database_url` belum perlu — dependency_overrides mengganti `get_db`.

- [ ] **Step 2: Run — verify fail** → `cd backend && python -m pytest tests/test_auth_api.py -v`

- [ ] **Step 3: Implement**

`backend/app/api/deps.py`:
```python
from fastapi import Depends, HTTPException, Request
from app.core.db import get_db
from app.core.security import decode_token
from app.models.user import User

COOKIE = "isentinel_token"

def _token_from(request: Request) -> str | None:
    if request.cookies.get(COOKIE): return request.cookies[COOKIE]
    h = request.headers.get("Authorization", "")
    return h[7:] if h.startswith("Bearer ") else None

def get_current_user(request: Request, db=Depends(get_db)) -> User:
    tok = _token_from(request)
    payload = decode_token(tok) if tok else None
    if not payload: raise HTTPException(401, "not authenticated")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.id: raise HTTPException(401, "user gone")
    return user

def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin": raise HTTPException(403, "admin only")
    return user
```

Routers `auth.py` (login/me/patch-locale, set cookie httpOnly `isentinel_token`), `users.py` (CRUD, DELETE tolak admin terakhir → 409), bootstrap di `main.py` lifespan: bila tabel `user` kosong → buat admin dari `settings.admin_username/admin_password` (password kosong → log ERROR, skip); seed `Node(name="server", type="server")` bila kosong. Semua response tanpa `password_hash`.

- [ ] **Step 4: Run — verify pass** → semua test PASS

- [ ] **Step 5: Commit** — `git commit -m "feat: auth API + user management + first-run admin bootstrap"`

---

### Task 6: Nodes & cameras CRUD API

**Files:**
- Create: `backend/app/api/nodes.py`, `backend/app/api/cameras.py`, `backend/app/schemas/camera.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_cameras_api.py`

**Interfaces:**
- Produces:
  - `GET /api/v1/nodes` → list (server node di-seed saat startup bila kosong: `Node(name="server", type="server")`)
  - `POST /api/v1/cameras {name, location?, host, rtsp_main?, rtsp_sub?, node_id?}` (admin) → CameraOut; `rtsp_*` optional — bisa diisi dari hasil probe
  - `GET /api/v1/cameras` → list (viewer boleh), `GET /cameras/{id}`, `PATCH` (admin), `DELETE` (admin)
  - `CameraOut{id,name,location,host,rtsp_main,rtsp_sub,node_id,enabled,status,probe_main,probe_sub}`
  - Unik: `name` per node (UniqueConstraint).
- Kredensial kamera TIDAK disimpan di DB (mengikuti zero-secret): rtsp URL final disusun runtime dari env `CAM_USERNAME/CAM_PASSWORD` + host. `rtsp_main/rtsp_sub` di DB menyimpan **path** saja (mis. `/Streaming/Channels/101`) — full URL disusun `rtsp://<user>:<pass>@<host><path>` saat runtime oleh go2rtc template. Bila kamera butuh kredensial berbeda, field `credential_ref` opsional (nama env var) — Fase 0: cukup default global.

- [ ] **Step 1: Failing test** — CRUD lengkap: create tanpa auth → 401; create oleh admin → 200 + GET list berisi; PATCH enabled=false; DELETE → 200 lalu 404. (Pola fixture sama dengan test_auth_api.)

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement** routers (pola sama dengan users: deps admin/viewer, response schema).

- [ ] **Step 4: Run — verify pass**

- [ ] **Step 5: Commit** — `git commit -m "feat: nodes + cameras CRUD API"`

---

### Task 7: Probe service + endpoint

**Files:**
- Create: `backend/app/services/probe.py`, `backend/app/api/probe.py`
- Test: `backend/tests/test_probe.py` (unit, subprocess di-mock) + `backend/tests/test_probe_gpu.py` (`@pytest.mark.gpu`, hanya jalan di server dengan kamera nyata)

**Interfaces:**
- Produces:
  - `build_rtsp_candidates(host, cam_user_env, cam_pass_env) -> dict[str, list[str]]` — `{"main": [url...], "sub": [url...]}` kandidat terurut: Hikvision (`/Streaming/Channels/101|102`), Dahua (`/cam/realmonitor?channel=1&subtype=0|1`), generic (`/stream1`, `/live/ch00_0`, `/`).
  - `probe_url(url, timeout=6.0) -> dict | None` — panggil `ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,codec_name -of json <url>`; parse → `{"res": "WxH", "fps": float, "codec": str}`; None bila gagal/timeout.
  - `probe_camera(host) -> {"main": {...}|None, "sub": {...}|None, "main_path": str|None, "sub_path": str|None}` — coba kandidat berurutan sampai berhasil.
  - `POST /api/v1/cameras/probe {host}` (admin) → hasil probe_camera; frontend wizard memakai ini; tombol "Probe" per kamera → endpoint sama.
- Known gap (tercatat): ONVIF fallback belum ada di Fase 0; path umum mencakup mayoritas. Tambah di Fase 1 bila kamera aktual tidak terprobe.

- [ ] **Step 1: Failing test (mock subprocess)**

`backend/tests/test_probe.py`:
```python
from unittest.mock import patch
from app.services.probe import build_rtsp_candidates, probe_url, probe_camera

def test_candidates_hikvision():
    c = build_rtsp_candidates("192.168.1.108")
    assert c["main"][0].endswith("192.168.1.108/Streaming/Channels/101")
    assert c["sub"][0].endswith("/Streaming/Channels/102")
    assert any("realmonitor" in u for u in c["main"])  # dahua juga masuk daftar

FFPROBE_JSON = '{"streams":[{"width":2560,"height":1440,"r_frame_rate":"25/1","codec_name":"h264"}]}'

def test_probe_url_parses():
    with patch("app.services.probe.subprocess.run") as m:
        m.return_value.returncode = 0
        m.return_value.stdout = FFPROBE_JSON
        r = probe_url("rtsp://x")
    assert r == {"res": "2560x1440", "fps": 25.0, "codec": "h264"}

def test_probe_url_fail_returns_none():
    with patch("app.services.probe.subprocess.run") as m:
        m.return_value.returncode = 1
        m.return_value.stdout = ""
        assert probe_url("rtsp://x") is None

def test_probe_camera_stops_at_first_hit():
    with patch("app.services.probe.probe_url") as p:
        p.side_effect = [None, {"res": "2560x1440", "fps": 25.0, "codec": "h264"},
                         {"res": "640x360", "fps": 15.0, "codec": "h264"}]
        r = probe_camera("1.2.3.4")
    assert r["main"]["res"] == "2560x1440" and r["sub"]["res"] == "640x360"
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement** (subprocess dengan `timeout`, `subprocess.TimeoutExpired` → None; kredensial dibaca `os.environ`, URL-encode user/pass).

- [ ] **Step 4: Run — verify pass**

- [ ] **Step 5: Commit** — `git commit -m "feat: rtsp probe service (ffprobe + vendor path candidates)"`

---

### Task 8: Frontend scaffold + Carbon dark + i18n + shell + login

**Files:**
- Create: `frontend/` via `npm create vite@latest frontend -- --template react-ts`; deps `@carbon/react @carbon/icons-react react-router-dom sass`
- Create: `frontend/src/app/theme.scss` (`@use '@carbon/react/scss/themes'; @use '@carbon/react/scss' with ($theme: g100);` + `html { color-scheme: dark }`), `frontend/src/app/i18n.tsx` (context + dict ID/EN), `frontend/src/app/AppShell.tsx`, `frontend/src/features/auth/LoginPage.tsx`, `frontend/src/api/client.ts`
- Test: `frontend/src/__tests__/shell.test.tsx`

**Interfaces:**
- Produces:
  - `api/client.ts`: `apiFetch(path, opts)` (fetch + JSON + 401 → redirect login), `login(u,p)`, `getMe()`, `logout()`
  - `i18n.tsx`: `<I18nProvider>`, `useT()` → `t(key)`; dict `id` & `en` flat keys (`nav.dashboard`, `login.title`, ...)
  - `AppShell`: Carbon `Header` (logo IS + env chip + lang toggle ID/EN) + `HeaderSideNavToggle` (collapsible — simpan state localStorage) + `SideNav` grup Monitoring/Management/System (item: Dashboard, Live View, Events, Attendance, Enrollment, Configuration) + `<Outlet/>`
  - Routing: `/login` publik; selain itu guard `RequireAuth` (getMe → 401 → redirect); `/` → `/dashboard` (placeholder heading di Fase 0)
- UI rules: g100 theme, corner 0px (Carbon default), tanpa emoji (icon dari @carbon/icons-react), label via t().

- [ ] **Step 1: Scaffold + deps**

Run: `npm create vite@latest frontend -- --template react-ts && cd frontend && npm i && npm i @carbon/react @carbon/icons-react react-router-dom sass && npm i -D vitest @testing-library/react @testing-library/jest-dom jsdom`

- [ ] **Step 2: Failing test shell + login**

`frontend/src/__tests__/shell.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AppShell from '../app/AppShell'
import { I18nProvider } from '../app/i18n'

test('renders sidebar items and lang toggle', () => {
  render(<I18nProvider><MemoryRouter initialEntries={['/dashboard']}><AppShell/></MemoryRouter></I18nProvider>)
  expect(screen.getByText('Dashboard')).toBeInTheDocument()
  expect(screen.getByText('Konfigurasi')).toBeInTheDocument()   // locale default id
  expect(screen.getByText('ID')).toBeInTheDocument()
})

test('login page validates empty submit', async () => {
  render(<I18nProvider><MemoryRouter initialEntries={['/login']}><LoginPage/></MemoryRouter></I18nProvider>)
  // klik tombol tanpa isi → pesan validasi muncul, tidak ada fetch
  await userEvent.click(screen.getByRole('button'))
  expect(screen.getByText(/wajib/i)).toBeInTheDocument()
})
```

- [ ] **Step 3: Run — verify fail** → `cd frontend && npx vitest run`

- [ ] **Step 4: Implement** (theme, i18n dict minimal ±40 key, shell sesuai mockup 01 — header 48px, sidebar 232px collapsible, footer user; LoginPage Carbon `TextInput` + `Button`; sidebar hidden untuk viewer pada item admin — role dari getMe; `App.css` default Vite dihapus).

- [ ] **Step 5: Run — verify pass** → vitest PASS; `npm run dev` → login page tampil dark.

- [ ] **Step 6: Commit** — `git commit -m "feat: frontend scaffold (carbon g100, i18n id/en, app shell, login)"`

---

### Task 9: Frontend halaman Kamera (list + wizard probe)

**Files:**
- Create: `frontend/src/features/config/CamerasPage.tsx`, `frontend/src/features/config/CameraWizard.tsx`, `frontend/src/api/cameras.ts`
- Modify: routing (tambah `/config/cameras`), i18n dict tambah key kamera
- Test: `frontend/src/__tests__/cameras.test.tsx` (mock fetch via `vi.stubGlobal`)

**Interfaces:**
- Consumes: `apiFetch`, t(); endpoints Task 6/7.
- Produces: `listCameras()`, `createCamera(payload)`, `probeCamera(host)` — thin wrappers.
- UI sesuai mockup 06 tab Kamera: tabel/list (nama, lokasi, chip MAIN/SUB hasil probe, node, status dot), tombol `+ Tambah kamera` → modal wizard: nama, lokasi, IP, node select → tombol `Probe stream` (loading state, hasil per baris: main/sub res·fps·codec atau gagal) → `Simpan` aktif hanya bila probe menemukan ≥1 stream. Aksi list: Probe (re-run), Nonaktif/Aktifkan (PATCH enabled), Hapus.
- Viewer: tombol admin disabled/hidden.

- [ ] **Step 1: Failing test** — render list dari mock data; submit wizard dengan probe mocked sukses → createCamera terpanggil dengan payload benar; probe gagal → Simpan disabled.
- [ ] **Step 2: Run — verify fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run — verify pass** + `npm run build` sukses
- [ ] **Step 5: Commit** — `git commit -m "feat: cameras page with probe wizard"`

---

### Task 10: Deploy configs + bring-up di server dev

**Files:**
- Create: `deploy/go2rtc/go2rtc.yaml`, `deploy/mosquitto/mosquitto.conf`, `deploy/systemd/isentinel-api.service`, `deploy/systemd/isentinel-recorder.service` (stub Fase 0), `deploy/bootstrap.sh`
- Modify: `README.md` (bagian Run: lokal + server)
- Verifikasi: end-to-end Fase 0 di `gspe-ai3` (bukan unit test)

- [ ] **Step 1: Tulis configs**

`deploy/go2rtc/go2rtc.yaml` (Fase 0 minimal — kamera ditambah manual/lewat API nanti):
```yaml
api: { listen: ":1984" }
rtsp: { listen: ":8554" }
log: { level: info }
# streams ditambahkan per kamera:
#   cam_1: rtsp://user:pass@192.168.1.108/Streaming/Channels/101
```
`deploy/mosquitto/mosquitto.conf`:
```
listener 1883 0.0.0.0
allow_anonymous false
password_file /etc/mosquitto/passwd
# Fase 1+ dipakai vision; Fase 0 hanya service siap
```
`deploy/systemd/isentinel-api.service`:
```ini
[Unit]
Description=I-Sentinel API
After=network.target postgresql.service

[Service]
User=isentinel
WorkingDirectory=/opt/isentinel/backend
EnvironmentFile=/opt/isentinel/.env
ExecStart=/opt/isentinel/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```
`deploy/bootstrap.sh` (server): buat venv, `pip install -e backend[dev]`, `alembic upgrade head`, salin unit systemd, enable; echo checklist manual.

- [ ] **Step 2: Bring-up di gspe-ai3 (manual, via SSH):**

```bash
ssh gspe-ai3
cd /opt/isentinel && git pull
./deploy/bootstrap.sh
# isi /opt/isentinel/.env (DATABASE_URL postgres, JWT_SECRET, ADMIN_PASSWORD, CAM_USERNAME/PASSWORD)
sudo systemctl start isentinel-api
curl -s localhost:8000/api/v1/health
```
Bukti Fase 0 (dicatat di plan ini sebagai checklist):
- [ ] `health` → `{"status":"ok"}`
- [ ] Login dari browser (frontend dev server → proxy API) sukses
- [ ] Tambah kamera via wizard → probe menemukan MAIN & SUB → tersimpan; daftar menampilkan chip resolusi
- [ ] `alembic upgrade head` idempotent (jalankan 2× tanpa error)

- [ ] **Step 3: Commit + push** — `git commit -m "chore: deploy configs (go2rtc, mosquitto, systemd) + bootstrap script"`

---

## Fase 0 — Definition of Done

1. Semua checkbox `[x]` dengan bukti (output test/curl/screenshot).
2. `pytest backend/tests -m "not gpu"` hijau di Windows; `pytest backend/tests` hijau di server.
3. `vitest run` + `npm run build` hijau.
4. Demo di server: login → tambah kamera → probe main+sub tampil.
5. Semua ter-commit; push ke GitHub.
