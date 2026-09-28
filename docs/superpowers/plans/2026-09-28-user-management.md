# User Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin mengelola user dari tab **User** (tambah, ubah role, reset password, nonaktifkan/aktifkan, hapus), setiap user bisa mengganti password sendiri, dan sesi yang dicabut (akun nonaktif / password diganti) langsung ditolak — termasuk sesi bergulir.

**Architecture:** Migrasi `0018` menambah `is_active`, `token_version`, `last_login_at`. JWT membawa klaim `tv`; `get_current_user` menolak akun nonaktif dan versi token yang tidak cocok (satu titik, jadi sesi bergulir ikut). API user memakai skema Pydantic ketat (`UserPatch`) + pengaman diri sendiri/admin terakhir. Frontend: `api/users.ts`, `UsersPage` di Konfigurasi, `ChangePasswordModal` dari kartu akun sidebar, pesan login 403.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic + PyJWT + bcrypt, pytest; React 19 + TypeScript + Carbon, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-28-user-management-design.md`

## Global Constraints

- Branch `feat/user-management` (dari `main` @ `3154c7b`); spec di commit pertama branch ini.
- **Tanpa AI attribution** di commit/kode/docs (`AGENTS.md` §9).
- Tanpa dependensi baru. Satu migrasi: `0018_user_status` (down_revision `0017`).
- **Zero-secret**: password tidak pernah di response, log, atau pesan error (handler 422 global sudah membuang
  `input`); response user tanpa `password_hash`/`token_version`.
- 2 role saja: `admin`, `viewer`. Password: **≥ 8 karakter, ≤ 72 byte**. Username: `^[A-Za-z0-9._-]{3,64}$`.
- REST hanya lewat `src/api/*`; string UI lewat `i18n.tsx` (`id` + `en`, kunci sama); Carbon + token tema; 390 px
  tanpa overflow horizontal halaman.
- **Jangan** `uv sync` / `uv lock` / membuat ulang venv.
- Setiap task: commit Conventional Commits + bullet `CHANGELOG.md` bagian `### User management (2026-09-28 – …)`
  (dibuat di Task 1, di atas `### Live View mode TV (2026-09-28)`).
- Baseline `main` `3154c7b`: backend **435**, vision **223** (3 deselected), frontend **161**, build 0, lint = set rule+file lama.
- **Eksekutor berhenti setelah `git push`.** Deploy (alembic upgrade + restart API) dan uji lapangan di sesi perencana.

## Deviasi / keputusan teknis dari spec

1. **Aksi baris = tombol ghost** (pola `ShiftsTab`), bukan `OverflowMenu`: konsisten dengan tabel lain dan bisa
   dites tanpa portal menu; tabel di `.en-table-scroll` (scroll horizontal milik tabel).
2. **Pengaman "admin aktif terakhir" tidak bisa dicapai lewat API** setelah pengaman "diri sendiri": pelaku harus admin
   aktif lain, jadi target tidak pernah admin aktif terakhir. Pengaman tetap dipertahankan (murah, pertahanan
   berlapis) tanpa tes khusus; tes lama `test_delete_last_admin_blocked` (hapus diri sendiri) tetap 409.
3. Reset password **akun sendiri** lewat tab User dinonaktifkan di UI (akan mengeluarkan sesi sendiri); pakai
   "Ganti password" di sidebar.
4. Tes lama yang membuat user dengan password < 8 karakter (mis. `"pw12345"`) diperbarui ke password ≥ 8.
5. `UsersPage` menerima `meId` sebagai prop (dari `useOutletContext` di `ConfigurationPage`) agar mudah dites.

## Review Focus

1. **Sesi bergulir setelah password diganti** → token lama yang lewat separuh umur tidak boleh "diperpanjang"; harus
   401. Tes: Task 2 `test_reset_revokes_old_tokens_including_rolling_cookie`.
2. **Deploy tidak mengeluarkan semua orang** → token tanpa klaim `tv` valid selama `token_version == 0`.
   Tes: Task 2 `test_token_without_tv_claim_valid_while_version_zero`.
3. **Status akun tidak bocor** → login akun nonaktif dengan password salah tetap 401 (bukan 403).
   Tes: Task 2 `test_login_disabled_403_only_with_right_password`.
4. **Ganti password sendiri saat token lama lewat separuh umur** → dependency juga menulis cookie perpanjangan
   (versi lama); cookie terakhir di response harus token versi baru yang valid.
   Tes: Task 4 `test_change_password_new_cookie_wins_over_rolling_renewal`.
5. **Input liar ke `PATCH /users`** (field tak dikenal, role lain, password pendek) → 422, tidak tersimpan.
   Tes: Task 3 `test_patch_validation`.

---

### Task 1: Migrasi `0018_user_status` + model

**Files:**
- Create: `backend/alembic/versions/0018_user_status.py`
- Modify: `backend/app/models/user.py`
- Test: `backend/tests/test_migration_0018.py` (baru)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `User.is_active: bool` (default True), `User.token_version: int` (default 0), `User.last_login_at: datetime | None`.

- [ ] **Step 1: Tulis tes (gagal)** — `backend/tests/test_migration_0018.py`:

```python
"""0018: status akun, versi token, login terakhir pada tabel user lama."""
import importlib.util
import pathlib

import sqlalchemy as sa

_PATH = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0018_user_status.py"
_spec = importlib.util.spec_from_file_location("mig0018", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_upgrade_downgrade_on_old_user_table():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = sa.create_engine("sqlite://")
    meta = sa.MetaData()
    sa.Table("user", meta,
             sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("username", sa.String(64)),
             sa.Column("password_hash", sa.String(255)),
             sa.Column("role", sa.String(16)),
             sa.Column("locale", sa.String(8)),
             sa.Column("created_at", sa.DateTime(timezone=True)))
    meta.create_all(engine)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO \"user\" (id, username, password_hash, role, locale) VALUES (1, 'a', 'h', 'admin', 'id')"))

    def run(fn):
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            fn()

    run(mig.upgrade)
    with engine.connect() as c:
        row = c.execute(sa.text("SELECT is_active, token_version, last_login_at FROM \"user\" WHERE id = 1")).one()
    assert bool(row.is_active) is True and row.token_version == 0 and row.last_login_at is None

    run(mig.downgrade)
    cols = {col["name"] for col in sa.inspect(engine).get_columns("user")}
    assert not cols & {"is_active", "token_version", "last_login_at"}
    assert {"id", "username", "password_hash", "role"} <= cols
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd backend && .venv/bin/python -m pytest tests/test_migration_0018.py -q` → FAIL (file migrasi tidak ada).

- [ ] **Step 3: Implementasi**

`backend/alembic/versions/0018_user_status.py`:

```python
"""user: status aktif, versi token (pencabutan sesi), login terakhir.

Revision ID: 0018
Revises: 0017
"""

from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("user", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("user", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # batch: SQLite (tes) tidak selalu mendukung DROP COLUMN; Postgres tetap ALTER biasa
    with op.batch_alter_table("user") as batch:
        batch.drop_column("last_login_at")
        batch.drop_column("token_version")
        batch.drop_column("is_active")
```

`backend/app/models/user.py`:

```python
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Integer, String, true
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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # naik saat password diganti / akun dinonaktifkan → token dengan klaim `tv` lama ditolak
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Jalankan, pastikan lulus** — backend suite penuh:
`cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`

- [ ] **Step 5: CHANGELOG + commit** — di atas `### Live View mode TV (2026-09-28)`:

```markdown
### User management (2026-09-28 – …)

- **Migrasi `0018_user_status`**: `user.is_active` (default true), `user.token_version` (default 0),
  `user.last_login_at`; downgrade lewat batch. Backend **<angka> passed**. Rollback: `alembic downgrade 0017`.
```

```bash
git add backend/alembic/versions/0018_user_status.py backend/app/models/user.py backend/tests/test_migration_0018.py CHANGELOG.md
git commit -m "feat(users): migrasi status akun, versi token, login terakhir"
```

---

### Task 2: Token versi + tolak akun nonaktif + login 403

**Files:**
- Modify: `backend/app/core/security.py` (`create_access_token`)
- Modify: `backend/app/api/deps.py` (`get_current_user`)
- Modify: `backend/app/api/auth.py` (`_login`, `login`)
- Test: `backend/tests/test_users_api.py` (baru)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: kolom Task 1.
- Produces: `create_access_token(user_id: int, role: str, token_version: int = 0) -> str` (klaim `tv`);
  `get_current_user` → 401 `"account disabled"` / `"session revoked"`; login → 403 `"account disabled"`.

- [ ] **Step 1: Tulis tes (gagal)** — `backend/tests/test_users_api.py`:

```python
import jwt
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from tests.conftest import *  # noqa

PW = "rahasia123"


@pytest.fixture
def client(db, monkeypatch):
    from app.api import auth
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "cookie_secure", True)  # httpx tidak replay cookie secure
    auth._FAILURES.clear()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    auth._FAILURES.clear()


def _login(client, username="admin", password="boot123"):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def _h(client, username="admin", password="boot123"):
    return {"Authorization": f"Bearer {_login(client, username, password).json()['token']}"}


def _create(client, h, username="tv-uji", role="viewer", password=PW):
    r = client.post("/api/v1/users", json={"username": username, "password": password, "role": role}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _token(uid: int, minutes_left: float, tv: int | None = 0) -> str:
    from app.core.config import settings
    claims = {"sub": str(uid), "role": "viewer", "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes_left)}
    if tv is not None:
        claims["tv"] = tv
    return jwt.encode(claims, settings.jwt_secret, settings.jwt_algorithm)


def _me(client, token: str, cookie: bool = False):
    headers = {"Cookie": f"isentinel_token={token}"} if cookie else {"Authorization": f"Bearer {token}"}
    return client.get("/api/v1/auth/me", headers=headers)


def test_login_disabled_403_only_with_right_password(client):
    h = _h(client)
    u = _create(client, h)
    assert client.patch(f"/api/v1/users/{u['id']}", json={"is_active": False}, headers=h).status_code == 200
    assert _login(client, "tv-uji", "salah-sekali").status_code == 401  # status tidak bocor
    r = _login(client, "tv-uji", PW)
    assert r.status_code == 403 and r.json()["detail"] == "account disabled"


def test_deactivate_revokes_active_session_and_reactivate_allows_login(client):
    h = _h(client)
    u = _create(client, h)
    tok = _login(client, "tv-uji", PW).json()["token"]
    assert _me(client, tok).status_code == 200
    client.patch(f"/api/v1/users/{u['id']}", json={"is_active": False}, headers=h)
    assert _me(client, tok).status_code == 401
    client.patch(f"/api/v1/users/{u['id']}", json={"is_active": True}, headers=h)
    assert _me(client, tok).status_code == 401  # versi token sudah naik saat dinonaktifkan
    assert _me(client, _login(client, "tv-uji", PW).json()["token"]).status_code == 200


def test_reset_revokes_old_tokens_including_rolling_cookie(client):
    h = _h(client)
    u = _create(client, h)
    fresh = _login(client, "tv-uji", PW).json()["token"]
    near_expiry = _token(u["id"], 30, tv=0)  # lewat separuh umur → biasanya diperpanjang
    assert _me(client, near_expiry, cookie=True).status_code == 200
    assert client.patch(f"/api/v1/users/{u['id']}", json={"password": "baru-rahasia-1"}, headers=h).status_code == 200
    assert _me(client, fresh).status_code == 401
    r = _me(client, near_expiry, cookie=True)
    assert r.status_code == 401 and "set-cookie" not in r.headers
    assert _login(client, "tv-uji", "baru-rahasia-1").status_code == 200


def test_token_without_tv_claim_valid_while_version_zero(client):
    h = _h(client)
    u = _create(client, h)
    assert _me(client, _token(u["id"], 600, tv=None)).status_code == 200
    client.patch(f"/api/v1/users/{u['id']}", json={"password": "baru-rahasia-1"}, headers=h)
    assert _me(client, _token(u["id"], 600, tv=None)).status_code == 401


def test_login_sets_last_login_and_listing_hides_secrets(client):
    h = _h(client)
    _create(client, h)
    _login(client, "tv-uji", PW)
    rows = {u["username"]: u for u in client.get("/api/v1/users", headers=h).json()}
    assert rows["tv-uji"]["last_login_at"] is not None and rows["tv-uji"]["is_active"] is True
    assert "created_at" in rows["tv-uji"]
    assert not {"password_hash", "token_version", "password"} & set(rows["tv-uji"])
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd backend && .venv/bin/python -m pytest tests/test_users_api.py -q`.

- [ ] **Step 3: Implementasi**

`backend/app/core/security.py`:

```python
def create_access_token(user_id: int, role: str, token_version: int = 0) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_min)
    # tv: versi sesi user; naik saat password diganti / akun dinonaktifkan → token lama ditolak
    return jwt.encode({"sub": str(user_id), "role": role, "tv": token_version, "exp": exp},
                      settings.jwt_secret, settings.jwt_algorithm)
```

`backend/app/api/deps.py` `get_current_user`:

```python
def get_current_user(request: Request, response: Response, db=Depends(get_db)) -> User:
    tok = _token_from(request)
    payload = decode_token(tok) if tok else None
    if not payload: raise HTTPException(401, "not authenticated")
    user = db.get(User, int(payload["sub"]))
    if not user: raise HTTPException(401, "user gone")
    if not user.is_active: raise HTTPException(401, "account disabled")
    # token tanpa klaim tv (terbit sebelum 0018) = versi 0 → tidak ada logout massal saat deploy
    if payload.get("tv", 0) != user.token_version: raise HTTPException(401, "session revoked")
    # Sesi bergulir: token cookie yang lewat separuh umurnya diganti baru, jadi layar TV yang
    # terus me-refresh tidak pernah logout. Bearer (skrip/API) tidak diubah.
    remaining_s = payload["exp"] - datetime.now(timezone.utc).timestamp()
    if request.cookies.get(COOKIE) == tok and remaining_s < settings.access_token_expire_min * 30:
        set_auth_cookie(response, create_access_token(user.id, user.role, user.token_version))
    return user
```

`backend/app/api/auth.py`:

```python
def _login(user: User, response: Response) -> dict:
    token = create_access_token(user.id, user.role, user.token_version)
    set_auth_cookie(response, token)
    return {"token": token, "user": UserOut.model_validate(user)}
```

Di `login`, setelah blok password salah (401) dan sebelum `_FAILURES.pop`:

```python
    if not user.is_active:
        # hanya pemegang password benar yang tahu akunnya nonaktif
        raise HTTPException(403, "account disabled")
    _FAILURES.pop(key, None)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return _login(user, response)
```

(import `from datetime import datetime, timezone`.)

`backend/app/schemas/user.py` `UserOut` — tambah field (dipakai juga oleh `/auth/me` dan response login):

```python
class UserOut(BaseModel):
    id: int
    username: str
    role: str
    locale: str
    is_active: bool = True
    created_at: datetime | None = None
    last_login_at: datetime | None = None
    model_config = {"from_attributes": True}
```

(`PATCH is_active` sudah dibutuhkan tes ini — Task 3 mengganti `update_user` seluruhnya; untuk sementara tambahkan di
`update_user` lama: `if "is_active" in body: user.is_active = bool(body["is_active"]); user.token_version += int(not user.is_active)`
dan pada cabang `password`: `user.token_version += 1`. Task 3 menggantinya dengan `UserPatch`.)

- [ ] **Step 4: Jalankan, pastikan lulus** — backend suite penuh (termasuk `test_auth_api.py` sesi bergulir).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Pencabutan sesi**: JWT membawa klaim `tv` (`token_version`); `get_current_user` menolak akun nonaktif dan versi
  token lama (termasuk sesi bergulir); token tanpa `tv` = versi 0 (tanpa logout massal saat deploy). Login akun
  nonaktif → 403 `account disabled` hanya bila password benar; `last_login_at` terisi. Backend **<angka> passed**.
```

```bash
git add backend/app/core/security.py backend/app/api/deps.py backend/app/api/auth.py backend/app/api/users.py backend/app/schemas/user.py backend/tests/test_users_api.py CHANGELOG.md
git commit -m "feat(auth): versi token dan tolak akun nonaktif"
```

---

### Task 3: API user — skema ketat, aturan password, pengaman diri sendiri

**Files:**
- Modify: `backend/app/schemas/user.py` (`UserIn`, `UserPatch`, validator bersama)
- Modify: `backend/app/api/users.py` (seluruh `update_user`, `delete_user`, `_active_admins`)
- Test: `backend/tests/test_users_api.py`, perbarui tes lama berpassword < 8
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces (`app.schemas.user`): `check_password(v: str) -> str`, `UserIn`, `UserPatch` (`extra="forbid"`:
  `role: Literal["admin","viewer"] | None`, `is_active: bool | None`, `password: str | None`, `locale: str | None`).
- Pesan 409 stabil (dipakai frontend Task 5): `"username taken"`, `"cannot change your own role"`,
  `"cannot deactivate yourself"`, `"cannot delete yourself"`, `"cannot demote last admin"`,
  `"cannot deactivate last admin"`, `"cannot delete last admin"`.

- [ ] **Step 1: Tulis tes (gagal)** — tambahkan di `test_users_api.py`:

```python
def test_create_validation(client):
    h = _h(client)
    for body in ({"username": "ab", "password": PW},                     # username < 3
                 {"username": "a b c", "password": PW},                  # spasi
                 {"username": "okuser", "password": "pendek7"},          # < 8
                 {"username": "okuser", "password": "é" * 37},          # 74 byte
                 {"username": "okuser", "password": PW, "role": "operator"}):
        assert client.post("/api/v1/users", json=body, headers=h).status_code == 422, body
    _create(client, h, username="okuser")
    r = client.post("/api/v1/users", json={"username": "okuser", "password": PW}, headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "username taken"


def test_patch_validation(client):
    h = _h(client)
    u = _create(client, h)
    for body in ({"password_hash": "x"}, {"token_version": 0}, {"role": "operator"},
                 {"password": "pendek7"}, {"is_active": "nanti"}):
        assert client.patch(f"/api/v1/users/{u['id']}", json=body, headers=h).status_code == 422, body
    assert _login(client, "tv-uji", PW).status_code == 200  # tidak ada yang tersimpan


def test_self_guards(client):
    h = _h(client)
    me = client.get("/api/v1/auth/me", headers=h).json()
    _create(client, h, username="admin2", role="admin")  # admin lain aktif → bukan kasus admin terakhir
    cases = [({"role": "viewer"}, "cannot change your own role"), ({"is_active": False}, "cannot deactivate yourself")]
    for body, detail in cases:
        r = client.patch(f"/api/v1/users/{me['id']}", json=body, headers=h)
        assert r.status_code == 409 and r.json()["detail"] == detail
    r = client.delete(f"/api/v1/users/{me['id']}", headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "cannot delete yourself"


def test_admin_manages_other_user(client):
    h = _h(client)
    u = _create(client, h)
    assert client.patch(f"/api/v1/users/{u['id']}", json={"role": "admin"}, headers=h).json()["role"] == "admin"
    assert client.patch(f"/api/v1/users/{u['id']}", json={"role": "viewer"}, headers=h).json()["role"] == "viewer"
    assert client.delete(f"/api/v1/users/{u['id']}", headers=h).status_code == 200
    assert _login(client, "tv-uji", PW).status_code == 401
```

Perbarui tes lama: `grep -rn '"password": "' backend/tests | grep -v boot123` — setiap `POST /api/v1/users` atau
`PATCH password` dengan password < 8 karakter (mis. `"pw12345"` di `test_auth_api.py::test_create_user_admin_only`)
ganti ke `"rahasia123"`; assertion lain tidak diubah.

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd backend && .venv/bin/python -m pytest tests/test_users_api.py -q`.

- [ ] **Step 3: Implementasi**

`backend/app/schemas/user.py` (ganti validator lama `UserIn`; `LoginIn` tetap):

```python
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
Role = Literal["admin", "viewer"]


def check_password(v: str) -> str:
    if len(v) < 8: raise ValueError("password must be at least 8 characters")
    if len(v.encode()) > 72: raise ValueError("password too long (max 72 bytes, bcrypt limit)")
    return v


class UserIn(BaseModel):
    username: str
    password: str
    role: Role = "viewer"
    locale: str = "id"

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        if not USERNAME_RE.fullmatch(v): raise ValueError("username must be 3-64 of A-Z a-z 0-9 . _ -")
        return v

    @field_validator("password")
    @classmethod
    def pw_valid(cls, v: str) -> str:
        return check_password(v)


class UserPatch(BaseModel):
    model_config = {"extra": "forbid"}
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = None
    locale: str | None = None

    @field_validator("password")
    @classmethod
    def pw_valid(cls, v: str | None) -> str | None:
        return None if v is None else check_password(v)
```

(Pydantic v2 `bool` menerima `"true"/"false"`; `"nanti"` → 422. Bila `is_active: "yes"` harus ditolak ketat, pakai
`StrictBool` — tidak wajib.)

`backend/app/api/users.py` — `update_user`, `delete_user`, penghitung admin aktif:

```python
from app.schemas.user import UserIn, UserOut, UserPatch


def _active_admins(db: Session) -> int:
    return db.query(User).filter_by(role="admin", is_active=True).count()


def _is_last_active_admin(db: Session, user: User) -> bool:
    return user.role == "admin" and user.is_active and _active_admins(db) == 1


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user: raise HTTPException(404, "user not found")
    is_self = user.id == admin.id
    if body.role is not None and body.role != user.role:
        if is_self: raise HTTPException(409, "cannot change your own role")
        if _is_last_active_admin(db, user): raise HTTPException(409, "cannot demote last admin")
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        if not body.is_active:
            if is_self: raise HTTPException(409, "cannot deactivate yourself")
            if _is_last_active_admin(db, user): raise HTTPException(409, "cannot deactivate last admin")
            user.token_version += 1  # sesi yang sedang aktif langsung ditolak
        user.is_active = body.is_active
    if body.locale is not None:
        user.locale = body.locale
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        user.token_version += 1  # reset password mengeluarkan semua sesi user ini
    db.commit(); db.refresh(user)
    return user


@router.delete("/{user_id}")
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user: raise HTTPException(404, "user not found")
    if user.id == admin.id: raise HTTPException(409, "cannot delete yourself")
    if _is_last_active_admin(db, user): raise HTTPException(409, "cannot delete last admin")
    db.delete(user); db.commit()
    return {"ok": True}
```

(`_admin_count` lama dihapus. Pengaman admin terakhir dipertahankan walau tidak tercapai lewat API — deviasi 2.
`create_user` tetap, kini memakai `UserIn` baru.)

- [ ] **Step 4: Jalankan, pastikan lulus** — backend suite penuh.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **API user ketat**: `UserPatch` (`extra="forbid"`, role `admin|viewer`), password ≥ 8 / ≤ 72 byte, username
  `[A-Za-z0-9._-]{3,64}`; reset password & nonaktif menaikkan `token_version`; admin tidak bisa mengubah role,
  menonaktifkan, atau menghapus akun sendiri; pengaman admin aktif terakhir. Backend **<angka> passed**.
```

```bash
git add backend/app/schemas/user.py backend/app/api/users.py backend/tests/test_users_api.py backend/tests/test_auth_api.py CHANGELOG.md
git commit -m "feat(users): skema ketat, aturan password, pengaman akun sendiri"
```

---

### Task 4: Ganti password sendiri (`POST /auth/change-password`)

**Files:**
- Modify: `backend/app/schemas/user.py` (`PasswordChange`)
- Modify: `backend/app/api/auth.py`
- Test: `backend/tests/test_users_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `POST /api/v1/auth/change-password` body `{current_password, new_password}` → 200 `{"ok": true}` + cookie
  baru; 400 `"current password is incorrect"`; 422 password baru tidak valid; 429 terkunci.

- [ ] **Step 1: Tulis tes (gagal)**

```python
def _cookie_token(r) -> str:
    """Token dari header Set-Cookie TERAKHIR (browser menerapkan berurutan)."""
    cookies = [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("isentinel_token=")]
    assert cookies, "tidak ada cookie sesi"
    return cookies[-1].split(";")[0].split("=", 1)[1]


def test_change_password_flow(client):
    h = _h(client)
    _create(client, h)
    old = _login(client, "tv-uji", PW).json()["token"]
    r = client.post("/api/v1/auth/change-password", headers={"Cookie": f"isentinel_token={old}"},
                    json={"current_password": "salah-sekali", "new_password": "baru-rahasia-1"})
    assert r.status_code == 400 and r.json()["detail"] == "current password is incorrect"
    r = client.post("/api/v1/auth/change-password", headers={"Cookie": f"isentinel_token={old}"},
                    json={"current_password": PW, "new_password": "pendek7"})
    assert r.status_code == 422 and "pendek7" not in r.text
    r = client.post("/api/v1/auth/change-password", headers={"Cookie": f"isentinel_token={old}"},
                    json={"current_password": PW, "new_password": "baru-rahasia-1"})
    assert r.status_code == 200
    assert _me(client, _cookie_token(r), cookie=True).status_code == 200  # browser ini tetap login
    assert _me(client, old).status_code == 401                              # perangkat lain keluar
    assert _login(client, "tv-uji", "baru-rahasia-1").status_code == 200


def test_change_password_new_cookie_wins_over_rolling_renewal(client):
    h = _h(client)
    u = _create(client, h)
    near_expiry = _token(u["id"], 30, tv=0)  # dependency juga akan menulis cookie perpanjangan (versi 0)
    r = client.post("/api/v1/auth/change-password", headers={"Cookie": f"isentinel_token={near_expiry}"},
                    json={"current_password": PW, "new_password": "baru-rahasia-1"})
    assert r.status_code == 200
    assert _me(client, _cookie_token(r), cookie=True).status_code == 200


def test_change_password_wrong_attempts_lock(client):
    from app.core.config import settings
    h = _h(client)
    _create(client, h)
    tok = _login(client, "tv-uji", PW).json()["token"]
    codes = [client.post("/api/v1/auth/change-password", headers={"Authorization": f"Bearer {tok}"},
                         json={"current_password": "salah-sekali", "new_password": "baru-rahasia-1"}).status_code
             for _ in range(settings.login_max_attempts + 1)]
    assert codes[-1] == 429
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd backend && .venv/bin/python -m pytest tests/test_users_api.py -q -k change_password`.

- [ ] **Step 3: Implementasi**

`backend/app/schemas/user.py`:

```python
class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def pw_valid(cls, v: str) -> str:
        return check_password(v)
```

`backend/app/api/auth.py` (import `hash_password`, `PasswordChange`):

```python
@router.post("/change-password")
def change_password(body: PasswordChange, request: Request, response: Response,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    key = _client_key(user.username, request)
    _check_lock(key)  # tebakan password lama ikut batas percobaan login
    if len(body.current_password.encode()) > 72 or not verify_password(body.current_password, user.password_hash):
        _FAILURES.setdefault(key, []).append(time.monotonic())
        raise HTTPException(400, "current password is incorrect")  # bukan 401: jangan lempar ke /login
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # perangkat lain keluar
    db.commit()
    # ditulis setelah cookie perpanjangan dari get_current_user (bila ada) → yang terakhir menang
    set_auth_cookie(response, create_access_token(user.id, user.role, user.token_version))
    return {"ok": True}
```

(Bila tes "cookie terakhir" gagal karena urutan header, hapus cookie perpanjangan dulu dengan
`del response.headers["set-cookie"]` sebelum `set_auth_cookie` — catat deviasinya.)

- [ ] **Step 4: Jalankan, pastikan lulus** — backend suite penuh.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Ganti password sendiri**: `POST /auth/change-password` (semua role); password lama salah → 400 dan dihitung ke
  batas percobaan login (429); sukses menaikkan `token_version` (perangkat lain keluar) dan menulis cookie baru
  (browser ini tetap login, menang atas cookie perpanjangan). Backend **<angka> passed**.
```

```bash
git add backend/app/schemas/user.py backend/app/api/auth.py backend/tests/test_users_api.py CHANGELOG.md
git commit -m "feat(auth): ganti password sendiri dengan pencabutan sesi lain"
```

---

### Task 5: Frontend — tab User di Konfigurasi

**Files:**
- Create: `frontend/src/api/users.ts`
- Create: `frontend/src/features/auth/password.ts`
- Create: `frontend/src/features/config/UsersPage.tsx`
- Modify: `frontend/src/features/config/ConfigurationPage.tsx`
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/users.test.tsx` (baru)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: API Task 2–3 (pesan 409 stabil).
- Produces:
  - `api/users.ts`: `type Role = 'admin' | 'viewer'`, `type User = { id: number; username: string; role: Role; locale: string; is_active: boolean; created_at: string; last_login_at: string | null }`, `listUsers(): Promise<User[]>`, `createUser(b: { username: string; role: Role; password: string }): Promise<User>`, `updateUser(id: number, b: { role?: Role; is_active?: boolean; password?: string }): Promise<User>`, `deleteUser(id: number): Promise<{ ok: boolean }>` — gagal → `Error(message)` dengan `message` = `detail` server (string) atau `'invalid'` untuk 422.
  - `features/auth/password.ts`: `MIN_PASSWORD = 8`, `passwordProblem(pw: string, confirm: string): TKey | null` (`'pw.err.short' | 'pw.err.long' | 'pw.err.mismatch'`).
  - `UsersPage({ meId }: { meId?: number })`.

- [ ] **Step 1: Tulis tes (gagal)** — `frontend/src/__tests__/users.test.tsx`:

```tsx
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Mock } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import UsersPage from '../features/config/UsersPage'
import type { User } from '../api/users'

const NOW = '2026-09-28T03:00:00Z'
const base = (id: number, username: string, role: 'admin' | 'viewer'): User =>
  ({ id, username, role, locale: 'id', is_active: true, created_at: NOW, last_login_at: id === 1 ? NOW : null })
let users: User[]

function stubFetch() {
  const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })
  return vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    if (u.endsWith('/users') && method === 'GET') return json(200, users)
    if (u.endsWith('/users') && method === 'POST') {
      if (users.some((x) => x.username === body.username)) return json(409, { detail: 'username taken' })
      const created = base(9, body.username, body.role)
      users = [...users, created]
      return json(200, created)
    }
    const m = u.match(/\/users\/(\d+)$/)
    const id = m ? Number(m[1]) : 0
    if (m && method === 'PATCH') {
      if (id === 2 && body.role === 'viewer') return json(409, { detail: 'cannot demote last admin' })
      users = users.map((x) => (x.id === id ? { ...x, ...('is_active' in body ? { is_active: body.is_active } : {}), ...(body.role ? { role: body.role } : {}) } : x))
      return json(200, users.find((x) => x.id === id))
    }
    if (m && method === 'DELETE') {
      users = users.filter((x) => x.id !== id)
      return json(200, { ok: true })
    }
    return json(404, null)
  })
}

function calls(f: Mock, method: string) {
  return f.mock.calls.filter(([, i]) => (i as RequestInit | undefined)?.method === method)
    .map(([u, i]) => ({ url: String(u), body: JSON.parse(String((i as RequestInit).body ?? 'null')) }))
}

function renderPage() {
  const f = stubFetch()
  vi.stubGlobal('fetch', f)
  render(<I18nProvider><UsersPage meId={1} /></I18nProvider>)
  return f
}

beforeEach(() => {
  users = [base(1, 'admin', 'admin'), base(2, 'admin2', 'admin'), base(3, 'tv-1', 'viewer')]
})
afterEach(() => vi.unstubAllGlobals())

test('tabel: akun sendiri ditandai dan aksi berbahayanya nonaktif', async () => {
  renderPage()
  const row = await screen.findByTestId('user-row-1')
  expect(row).toHaveTextContent('(Anda)')
  for (const a of ['role', 'reset', 'deactivate', 'delete']) expect(screen.getByTestId(`user-${a}-1`)).toBeDisabled()
  expect(screen.getByTestId('user-delete-3')).toBeEnabled()
  expect(screen.getByTestId('user-row-3')).toHaveTextContent('—') // belum pernah login
})

test('tambah user: validasi klien, lalu POST dan baris baru; username terpakai → pesan', async () => {
  const f = renderPage()
  await screen.findByTestId('user-row-1')
  await userEvent.click(screen.getByTestId('user-add'))
  const dialog = screen.getByRole('dialog')
  await userEvent.type(within(dialog).getByLabelText('Username'), 'tv-2')
  await userEvent.type(within(dialog).getByLabelText('Password awal', { selector: 'input' }), 'pendek7')
  expect(screen.getByTestId('user-form-problem')).toHaveTextContent('minimal 8')
  await userEvent.type(within(dialog).getByLabelText('Password awal', { selector: 'input' }), 'x')
  await userEvent.type(within(dialog).getByLabelText('Ulangi password', { selector: 'input' }), 'pendek7x')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Simpan' }))
  expect(await screen.findByTestId('user-row-9')).toHaveTextContent('tv-2')
  expect(calls(f, 'POST')[0].body).toEqual({ username: 'tv-2', role: 'viewer', password: 'pendek7x' })

  await userEvent.click(screen.getByTestId('user-add'))
  const d2 = screen.getByRole('dialog')
  await userEvent.type(within(d2).getByLabelText('Username'), 'tv-1')
  await userEvent.type(within(d2).getByLabelText('Password awal', { selector: 'input' }), 'rahasia123')
  await userEvent.type(within(d2).getByLabelText('Ulangi password', { selector: 'input' }), 'rahasia123')
  await userEvent.click(within(d2).getByRole('button', { name: 'Simpan' }))
  expect(await within(d2).findByText('Username sudah dipakai')).toBeInTheDocument()
})

test('reset password, nonaktifkan (konfirmasi), aktifkan, hapus', async () => {
  const f = renderPage()
  await screen.findByTestId('user-row-3')

  await userEvent.click(screen.getByTestId('user-reset-3'))
  const d = screen.getByRole('dialog')
  await userEvent.type(within(d).getByLabelText('Password awal', { selector: 'input' }), 'baru-rahasia-1')
  await userEvent.type(within(d).getByLabelText('Ulangi password', { selector: 'input' }), 'baru-rahasia-1')
  await userEvent.click(within(d).getByRole('button', { name: 'Reset password' }))
  await waitFor(() => expect(calls(f, 'PATCH')[0]).toEqual({ url: '/api/v1/users/3', body: { password: 'baru-rahasia-1' } }))

  await userEvent.click(screen.getByTestId('user-deactivate-3'))
  await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Nonaktifkan' }))
  expect(await screen.findByTestId('user-activate-3')).toBeInTheDocument()
  expect(screen.getByTestId('user-row-3')).toHaveTextContent('Nonaktif')
  expect(calls(f, 'PATCH')[1].body).toEqual({ is_active: false })

  await userEvent.click(screen.getByTestId('user-activate-3'))
  expect(await screen.findByTestId('user-deactivate-3')).toBeInTheDocument()
  expect(calls(f, 'PATCH')[2].body).toEqual({ is_active: true })

  await userEvent.click(screen.getByTestId('user-delete-3'))
  await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Hapus' }))
  await waitFor(() => expect(screen.queryByTestId('user-row-3')).not.toBeInTheDocument())
})

test('penolakan server (admin terakhir) tampil sebagai pesan', async () => {
  renderPage()
  await screen.findByTestId('user-row-2')
  await userEvent.click(screen.getByTestId('user-role-2'))
  expect(await screen.findByText('Harus tersisa minimal satu admin aktif')).toBeInTheDocument()
})
```

(Bila `getByRole('dialog')` menemukan lebih dari satu karena Carbon me-render modal tertutup, pakai
`screen.getAllByRole('dialog').find((d) => d.closest('.is-visible'))` atau `data-testid="user-dialog"` pada `Modal`.)

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd frontend && npx vitest run src/__tests__/users.test.tsx`.

- [ ] **Step 3: Implementasi**

`frontend/src/api/users.ts`:

```ts
import { apiFetch } from './client'

export type Role = 'admin' | 'viewer'
export type User = {
  id: number
  username: string
  role: Role
  locale: string
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

// Gagal → Error(detail server) agar UI memetakan pesan stabil backend (app/api/users.py); 422 → 'invalid'.
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(res.status === 422 ? 'invalid' : typeof body?.detail === 'string' ? body.detail : `http ${res.status}`)
  }
  return res.json()
}

export const listUsers = () => call<User[]>('/users')
export const createUser = (b: { username: string; role: Role; password: string }) =>
  call<User>('/users', { method: 'POST', body: JSON.stringify(b) })
export const updateUser = (id: number, b: { role?: Role; is_active?: boolean; password?: string }) =>
  call<User>(`/users/${id}`, { method: 'PATCH', body: JSON.stringify(b) })
export const deleteUser = (id: number) => call<{ ok: boolean }>(`/users/${id}`, { method: 'DELETE' })
```

`frontend/src/features/auth/password.ts`:

```ts
import type { TKey } from '../../app/i18n'

export const MIN_PASSWORD = 8 // sama dengan backend (schemas/user.py check_password)

export function passwordProblem(pw: string, confirm: string): TKey | null {
  if (pw.length < MIN_PASSWORD) return 'pw.err.short'
  if (new TextEncoder().encode(pw).length > 72) return 'pw.err.long' // batas bcrypt
  if (pw !== confirm) return 'pw.err.mismatch'
  return null
}
```

`frontend/src/features/config/UsersPage.tsx`:

```tsx
import { useCallback, useEffect, useState } from 'react'
import {
  Button, InlineLoading, InlineNotification, Modal, PasswordInput, Select, SelectItem,
  Table, TableBody, TableCell, TableContainer, TableHead, TableHeader, TableRow, Tag, TextInput,
} from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { createUser, deleteUser, listUsers, updateUser, type Role, type User } from '../../api/users'
import { passwordProblem } from '../auth/password'

const USERNAME_RE = /^[A-Za-z0-9._-]{3,64}$/
const HEADERS = ['users.col.username', 'users.col.role', 'users.col.status', 'users.col.created',
  'users.col.lastLogin', 'users.col.actions'] as const
// pesan backend stabil (app/api/users.py) → teks UI
const ERRORS: [string, TKey][] = [
  ['username taken', 'users.err.taken'], ['yourself', 'users.err.self'], ['your own', 'users.err.self'],
  ['last admin', 'users.err.lastAdmin'], ['invalid', 'users.err.invalid'],
]
const errKey = (msg: string): TKey => ERRORS.find(([s]) => msg.includes(s))?.[1] ?? 'users.err.generic'

type Dialog = { kind: 'add' } | { kind: 'reset' | 'deactivate' | 'delete'; user: User }
const PRIMARY: Record<Dialog['kind'], TKey> = {
  add: 'common.save', reset: 'users.reset', deactivate: 'users.deactivate', delete: 'users.delete',
}
const EMPTY = { username: '', role: 'viewer' as Role, password: '', confirm: '' }

export default function UsersPage({ meId }: { meId?: number }) {
  const { t, locale } = useT()
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<TKey | null>(null)
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const [dialogError, setDialogError] = useState<TKey | null>(null)
  const [form, setForm] = useState(EMPTY)

  const refresh = useCallback(async () => {
    try {
      setUsers(await listUsers())
    } catch {
      setError('users.err.load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- refresh async: setState setelah await
    refresh()
  }, [refresh])

  const open = (d: Dialog) => {
    setDialog(d)
    setDialogError(null)
    setForm(EMPTY)
  }

  const run = async (fn: () => Promise<unknown>, inDialog: boolean) => {
    try {
      await fn()
      setDialog(null)
      setError(null)
      await refresh()
    } catch (e) {
      const key = errKey((e as Error).message)
      if (inDialog) setDialogError(key)
      else setError(key)
    }
  }

  const submit = () => {
    if (!dialog) return
    if (dialog.kind === 'add') return run(() => createUser({ username: form.username, role: form.role, password: form.password }), true)
    if (dialog.kind === 'reset') return run(() => updateUser(dialog.user.id, { password: form.password }), true)
    if (dialog.kind === 'deactivate') return run(() => updateUser(dialog.user.id, { is_active: false }), true)
    return run(() => deleteUser(dialog.user.id), true)
  }

  const problem: TKey | null = dialog?.kind === 'add'
    ? (USERNAME_RE.test(form.username) ? passwordProblem(form.password, form.confirm) : 'users.err.username')
    : dialog?.kind === 'reset' ? passwordProblem(form.password, form.confirm) : null

  const fmt = (iso: string | null) => (iso
    ? new Date(iso).toLocaleString(locale === 'en' ? 'en-GB' : 'id-ID', { dateStyle: 'medium', timeStyle: 'short' })
    : '—')

  const passwordFields = (
    <>
      <PasswordInput id="user-password" labelText={t('users.password')} autoComplete="new-password"
        value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
      <PasswordInput id="user-confirm" labelText={t('users.confirm')} autoComplete="new-password"
        value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
    </>
  )

  return (
    <div>
      {error && <InlineNotification kind="error" lowContrast title={t(error)} onCloseButtonClick={() => setError(null)} />}
      <div className="en-toolbar">
        <Button size="sm" data-testid="user-add" onClick={() => open({ kind: 'add' })}>{t('users.add')}</Button>
      </div>
      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : (
        <div className="en-table-scroll">
          <TableContainer>
            <Table size="sm">
              <TableHead>
                <TableRow>{HEADERS.map((h) => <TableHeader key={h}>{t(h)}</TableHeader>)}</TableRow>
              </TableHead>
              <TableBody>
                {users.map((u) => {
                  const self = u.id === meId
                  return (
                    <TableRow key={u.id} data-testid={`user-row-${u.id}`}>
                      <TableCell>
                        <strong>{u.username}</strong>
                        {self && <span className="en-muted"> {t('users.you')}</span>}
                      </TableCell>
                      <TableCell><Tag size="sm" type={u.role === 'admin' ? 'red' : 'gray'}>{u.role}</Tag></TableCell>
                      <TableCell>
                        {u.is_active ? t('users.active') : <Tag size="sm" type="warm-gray">{t('users.inactive')}</Tag>}
                      </TableCell>
                      <TableCell>{fmt(u.created_at)}</TableCell>
                      <TableCell>{fmt(u.last_login_at)}</TableCell>
                      <TableCell>
                        <Button kind="ghost" size="sm" data-testid={`user-role-${u.id}`} disabled={self}
                          onClick={() => run(() => updateUser(u.id, { role: u.role === 'admin' ? 'viewer' : 'admin' }), false)}>
                          {t(u.role === 'admin' ? 'users.makeViewer' : 'users.makeAdmin')}
                        </Button>
                        <Button kind="ghost" size="sm" data-testid={`user-reset-${u.id}`} disabled={self}
                          onClick={() => open({ kind: 'reset', user: u })}>
                          {t('users.reset')}
                        </Button>
                        {u.is_active ? (
                          <Button kind="ghost" size="sm" data-testid={`user-deactivate-${u.id}`} disabled={self}
                            onClick={() => open({ kind: 'deactivate', user: u })}>
                            {t('users.deactivate')}
                          </Button>
                        ) : (
                          <Button kind="ghost" size="sm" data-testid={`user-activate-${u.id}`}
                            onClick={() => run(() => updateUser(u.id, { is_active: true }), false)}>
                            {t('users.activate')}
                          </Button>
                        )}
                        <Button kind="danger--ghost" size="sm" data-testid={`user-delete-${u.id}`} disabled={self}
                          onClick={() => open({ kind: 'delete', user: u })}>
                          {t('users.delete')}
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </div>
      )}
      <p className="en-muted">{t('users.hint')}</p>

      {dialog && (
        <Modal
          open
          size="sm"
          danger={dialog.kind === 'deactivate' || dialog.kind === 'delete'}
          modalHeading={t(`users.dlg.${dialog.kind}` as TKey)}
          primaryButtonText={t(PRIMARY[dialog.kind])}
          secondaryButtonText={t('common.cancel')}
          primaryButtonDisabled={problem !== null}
          onRequestClose={() => setDialog(null)}
          onRequestSubmit={submit}
        >
          <div className="en-form">
            {dialog.kind === 'add' && (
              <>
                <TextInput id="user-username" labelText={t('users.col.username')} autoComplete="off"
                  value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value.trim() })} />
                <Select id="user-role" labelText={t('users.col.role')} value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                  <SelectItem value="viewer" text={t('users.role.viewer')} />
                  <SelectItem value="admin" text={t('users.role.admin')} />
                </Select>
                {passwordFields}
              </>
            )}
            {dialog.kind === 'reset' && (
              <>
                <p>{t('users.resetBody').replace('{name}', dialog.user.username)}</p>
                {passwordFields}
              </>
            )}
            {dialog.kind === 'deactivate' && <p>{t('users.deactivateBody').replace('{name}', dialog.user.username)}</p>}
            {dialog.kind === 'delete' && <p>{t('users.deleteBody').replace('{name}', dialog.user.username)}</p>}
            {problem && (form.username || form.password) && (
              <p className="en-form__hint" data-testid="user-form-problem">{t(problem)}</p>
            )}
            {dialogError && <InlineNotification kind="error" lowContrast hideCloseButton title={t(dialogError)} />}
          </div>
        </Modal>
      )}
    </div>
  )
}
```

(Label "Password awal" dipakai juga di dialog reset — tes memakai label yang sama. Bila `PasswordInput` tidak
diekspor versi Carbon terpasang, pakai `TextInput type="password"` dan catat.)

`ConfigurationPage.tsx`: `TABS` + `'users'` di akhir; `TAB_LABEL.users = 'users.title'`;
`import { useOutletContext } from 'react-router-dom'` + `import type { Me } from '../../api/client'`;
`const me = useOutletContext<Me | null>()`; panel `<TabPanel>{tab === 'users' && <UsersPage meId={me?.id} />}</TabPanel>`.

`i18n.tsx` — `id` / `en`:

| Kunci | id | en |
|---|---|---|
| `users.title` | User | Users |
| `users.add` | Tambah user | Add user |
| `users.col.username` | Username | Username |
| `users.col.role` | Role | Role |
| `users.col.status` | Status | Status |
| `users.col.created` | Dibuat | Created |
| `users.col.lastLogin` | Login terakhir | Last login |
| `users.col.actions` | Aksi | Actions |
| `users.you` | (Anda) | (you) |
| `users.active` | Aktif | Active |
| `users.inactive` | Nonaktif | Disabled |
| `users.makeAdmin` | Jadikan admin | Make admin |
| `users.makeViewer` | Jadikan viewer | Make viewer |
| `users.reset` | Reset password | Reset password |
| `users.deactivate` | Nonaktifkan | Disable |
| `users.activate` | Aktifkan | Enable |
| `users.delete` | Hapus | Delete |
| `users.role.viewer` | viewer — read-only | viewer — read-only |
| `users.role.admin` | admin — akses penuh | admin — full access |
| `users.password` | Password awal | Initial password |
| `users.confirm` | Ulangi password | Confirm password |
| `users.dlg.add` | Tambah user | Add user |
| `users.dlg.reset` | Reset password | Reset password |
| `users.dlg.deactivate` | Nonaktifkan user | Disable user |
| `users.dlg.delete` | Hapus user | Delete user |
| `users.resetBody` | Password baru untuk {name}. Semua sesi user ini akan keluar. | New password for {name}. All of this user's sessions will be signed out. |
| `users.deactivateBody` | {name} tidak bisa login dan sesi yang aktif langsung keluar. | {name} will not be able to sign in and active sessions end immediately. |
| `users.deleteBody` | Hapus {name} secara permanen? | Permanently delete {name}? |
| `users.hint` | admin = semua konfigurasi + enrollment + koreksi · viewer = read-only. | admin = all configuration + enrollment + corrections · viewer = read-only. |
| `users.err.load` | Gagal memuat user | Failed to load users |
| `users.err.taken` | Username sudah dipakai | Username already taken |
| `users.err.self` | Tidak bisa mengubah role, menonaktifkan, atau menghapus akun sendiri | You cannot change the role of, disable, or delete your own account |
| `users.err.lastAdmin` | Harus tersisa minimal satu admin aktif | At least one active admin must remain |
| `users.err.invalid` | Data tidak valid | Invalid data |
| `users.err.generic` | Gagal menyimpan | Save failed |
| `users.err.username` | Username 3–64 karakter: huruf, angka, titik, minus, garis bawah | Username must be 3–64 characters: letters, digits, dot, dash, underscore |
| `pw.err.short` | Password minimal 8 karakter | Password must be at least 8 characters |
| `pw.err.long` | Password maksimal 72 byte | Password must be at most 72 bytes |
| `pw.err.mismatch` | Konfirmasi password tidak sama | Passwords do not match |

(`common.save`, `common.cancel`, `common.loading` sudah ada.)

- [ ] **Step 4: Jalankan, pastikan lulus** — `npx vitest run && npm run build && npm run lint`; cek visual tab User
  1440 px & 390 px (tabel menggulir di dalam `.en-table-scroll`, halaman tanpa overflow).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Tab User (Konfigurasi)**: tabel username/role/status/dibuat/login terakhir + aksi (jadikan admin/viewer, reset
  password, nonaktifkan dengan konfirmasi, aktifkan, hapus); akun sendiri ditandai "(Anda)" dan aksi berbahayanya
  nonaktif; modal tambah user dengan validasi klien = backend; pesan 409 server dipetakan ke teks. Frontend
  **<angka> passed**, build 0, lint set sama.
```

```bash
git add frontend/src/api/users.ts frontend/src/features/auth/password.ts frontend/src/features/config/UsersPage.tsx frontend/src/features/config/ConfigurationPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/users.test.tsx CHANGELOG.md
git commit -m "feat(users): tab User di Konfigurasi"
```

---

### Task 6: Frontend — ganti password sendiri + pesan login akun nonaktif

**Files:**
- Create: `frontend/src/features/auth/ChangePasswordModal.tsx`
- Modify: `frontend/src/api/client.ts` (`login` error, `changePassword`)
- Modify: `frontend/src/features/auth/LoginPage.tsx`
- Modify: `frontend/src/app/AppShell.tsx`
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/password.test.tsx` (baru)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `passwordProblem` (Task 5); `POST /auth/change-password` (Task 4).
- Produces: `changePassword(current: string, next: string): Promise<void>` — `Error('wrong' | 'locked' | 'invalid')`;
  `login()` melempar `Error('disabled')` untuk 403, `Error('invalid')` untuk 401;
  `ChangePasswordModal({ onClose }: { onClose: (changed: boolean) => void })`.

- [ ] **Step 1: Tulis tes (gagal)** — `frontend/src/__tests__/password.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import AppShell from '../app/AppShell'
import ChangePasswordModal from '../features/auth/ChangePasswordModal'
import LoginPage from '../features/auth/LoginPage'
import { passwordProblem } from '../features/auth/password'

afterEach(() => vi.unstubAllGlobals())

const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })

test('passwordProblem: panjang minimal, batas byte, konfirmasi', () => {
  expect(passwordProblem('pendek7', 'pendek7')).toBe('pw.err.short')
  expect(passwordProblem('é'.repeat(37), 'é'.repeat(37))).toBe('pw.err.long')
  expect(passwordProblem('rahasia123', 'rahasia124')).toBe('pw.err.mismatch')
  expect(passwordProblem('rahasia123', 'rahasia123')).toBeNull()
})

async function fill(current: string, next: string) {
  await userEvent.type(screen.getByLabelText('Password lama', { selector: 'input' }), current)
  await userEvent.type(screen.getByLabelText('Password baru', { selector: 'input' }), next)
  await userEvent.type(screen.getByLabelText('Ulangi password baru', { selector: 'input' }), next)
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
}

test('ganti password: lama salah → pesan; sukses → onClose(true) dengan body benar', async () => {
  const f = vi.fn(async () => json(400, { detail: 'current password is incorrect' }))
  vi.stubGlobal('fetch', f)
  const onClose = vi.fn()
  render(<I18nProvider><ChangePasswordModal onClose={onClose} /></I18nProvider>)
  await fill('salah-sekali', 'baru-rahasia-1')
  expect(await screen.findByText('Password lama salah')).toBeInTheDocument()
  expect(onClose).not.toHaveBeenCalled()

  f.mockImplementation(async () => json(200, { ok: true }))
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
  await vi.waitFor(() => expect(onClose).toHaveBeenCalledWith(true))
  const [url, init] = f.mock.calls.at(-1) as unknown as [string, RequestInit]
  expect(url).toBe('/api/v1/auth/change-password')
  expect(JSON.parse(String(init.body))).toEqual({ current_password: 'salah-sekali', new_password: 'baru-rahasia-1' })
})

test('login akun nonaktif menampilkan pesan khusus', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(403, { detail: 'account disabled' })))
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/login']}>
        <Routes><Route path="/login" element={<LoginPage />} /></Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
  await userEvent.type(screen.getByLabelText(/username|nama pengguna/i), 'tv-1')
  await userEvent.type(screen.getByLabelText(/password|kata sandi/i, { selector: 'input' }), 'rahasia123')
  await userEvent.click(screen.getByRole('button', { name: /masuk|login|sign in/i }))
  expect(await screen.findByText('Akun dinonaktifkan — hubungi admin')).toBeInTheDocument()
})

test('kartu akun sidebar membuka modal ganti password', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(200, { id: 1, username: 'admin', role: 'admin' })))
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes><Route path="/" element={<AppShell />}><Route path="dashboard" element={<div />} /></Route></Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
  await userEvent.click(await screen.findByTestId('change-password-open'))
  expect(screen.getByLabelText('Password lama', { selector: 'input' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `npx vitest run src/__tests__/password.test.tsx`.

- [ ] **Step 3: Implementasi**

`frontend/src/api/client.ts`:

```ts
export async function login(username: string, password: string): Promise<Me> {
  const res = await apiFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    throw new Error(res.status === 401 ? 'invalid' : res.status === 403 ? 'disabled' : `login failed: ${res.status}`)
  }
  const data = await res.json()
  return data.user
}

/** 400 = password lama salah (bukan 401 → tidak melempar ke /login); cookie baru ditulis server. */
export async function changePassword(current: string, next: string): Promise<void> {
  const res = await apiFetch('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: current, new_password: next }),
  })
  if (res.ok) return
  throw new Error(res.status === 400 ? 'wrong' : res.status === 429 ? 'locked' : 'invalid')
}
```

`LoginPage.tsx`: state `apiError` jadi `'invalid' | 'disabled' | null`:

```tsx
  const [apiError, setApiError] = useState<'invalid' | 'disabled' | null>(null)
  // …
    setApiError(null)
    try {
      await login(username, password)
      navigate(safeNext(params.get('next')))
    } catch (e) {
      setApiError((e as Error).message === 'disabled' ? 'disabled' : 'invalid')
    }
  // …
        {apiError && (
          <InlineNotification kind="error" lowContrast
            title={t(apiError === 'disabled' ? 'login.disabled' : 'login.invalid')} subtitle=""
            onCloseButtonClick={() => setApiError(null)} />
        )}
```

`frontend/src/features/auth/ChangePasswordModal.tsx`:

```tsx
import { useState } from 'react'
import { InlineNotification, Modal, PasswordInput } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { changePassword } from '../../api/client'
import { passwordProblem } from './password'

/** Ganti password sendiri; sukses → server menulis cookie baru (browser ini tetap login). */
export default function ChangePasswordModal({ onClose }: { onClose: (changed: boolean) => void }) {
  const { t } = useT()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<TKey | null>(null)
  const [busy, setBusy] = useState(false)
  const problem: TKey | null = current ? passwordProblem(next, confirm) : 'pw.err.current'

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await changePassword(current, next)
      onClose(true)
    } catch (e) {
      const m = (e as Error).message
      setError(m === 'wrong' ? 'pw.err.wrong' : m === 'locked' ? 'pw.err.locked' : 'users.err.invalid')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open size="sm" modalHeading={t('pw.title')} primaryButtonText={t('common.save')}
      secondaryButtonText={t('common.cancel')} primaryButtonDisabled={problem !== null || busy}
      onRequestClose={() => onClose(false)} onRequestSubmit={submit}>
      <div className="en-form">
        <PasswordInput id="pw-current" labelText={t('pw.current')} autoComplete="current-password"
          value={current} onChange={(e) => setCurrent(e.target.value)} />
        <PasswordInput id="pw-new" labelText={t('pw.new')} autoComplete="new-password"
          value={next} onChange={(e) => setNext(e.target.value)} />
        <PasswordInput id="pw-confirm" labelText={t('pw.confirm')} autoComplete="new-password"
          value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {problem && next && <p className="en-form__hint">{t(problem)}</p>}
        {error && <InlineNotification kind="error" lowContrast hideCloseButton title={t(error)} />}
      </div>
    </Modal>
  )
}
```

`AppShell.tsx`:
- import `Password` dari `@carbon/icons-react`, `InlineNotification` dari `@carbon/react`, `ChangePasswordModal`.
- state `const [pwOpen, setPwOpen] = useState(false)` dan `const [pwDone, setPwDone] = useState(false)`.
- di `li.app-sidenav-user`, sebelum tombol logout, bila `me`:

```tsx
            {me && (
              <button type="button" className="app-sidenav-user__logout" data-testid="change-password-open"
                aria-label={t('pw.title')} title={t('pw.title')} onClick={() => setPwOpen(true)}>
                <Password size={16} />
                <span className="app-sidenav-user__logout-text">{t('pw.short')}</span>
              </button>
            )}
```

- di `<main>` sebelum `<Outlet>`:

```tsx
        {pwDone && (
          <InlineNotification kind="success" lowContrast title={t('pw.done')} onCloseButtonClick={() => setPwDone(false)} />
        )}
```

- setelah `</main>`: `{pwOpen && <ChangePasswordModal onClose={(changed) => { setPwOpen(false); setPwDone(changed) }} />}`.

`i18n.tsx` — `id` / `en`:

| Kunci | id | en |
|---|---|---|
| `pw.title` | Ganti password | Change password |
| `pw.short` | Password | Password |
| `pw.current` | Password lama | Current password |
| `pw.new` | Password baru | New password |
| `pw.confirm` | Ulangi password baru | Confirm new password |
| `pw.done` | Password diganti; perangkat lain telah dikeluarkan. | Password changed; other devices were signed out. |
| `pw.err.current` | Isi password lama | Enter your current password |
| `pw.err.wrong` | Password lama salah | Current password is incorrect |
| `pw.err.locked` | Terlalu banyak percobaan, coba lagi nanti | Too many attempts, try again later |
| `login.disabled` | Akun dinonaktifkan — hubungi admin | Account disabled — contact an admin |

- [ ] **Step 4: Jalankan, pastikan lulus** — `npx vitest run && npm run build && npm run lint`; cek sidebar mode rail
  (ikon saja) dan 390 px.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Ganti password sendiri (UI) + login nonaktif**: tombol "Ganti password" di kartu akun sidebar (semua role) →
  modal lama/baru/konfirmasi, pesan password lama salah/terkunci, notifikasi sukses; login akun nonaktif
  menampilkan "Akun dinonaktifkan — hubungi admin". Frontend **<angka> passed**, build 0, lint set sama.
```

```bash
git add frontend/src/features/auth/ChangePasswordModal.tsx frontend/src/api/client.ts frontend/src/features/auth/LoginPage.tsx frontend/src/app/AppShell.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/password.test.tsx CHANGELOG.md
git commit -m "feat(auth): ganti password sendiri dan pesan akun nonaktif"
```

---

### Task 7: Dokumen, suite penuh, push (eksekutor berhenti di sini)

- [ ] **Step 1: Suite penuh**

```bash
cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1; cd ..
backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu" | tail -1
cd frontend && npx vitest run | tail -3 && npm run build > /dev/null; echo build=$?; npm run lint | tail -2; cd ..
```

- [ ] **Step 2: Dokumen**
  - `README.md` — bagian auth/user: tab User (Konfigurasi), 2 role, nonaktifkan/aktifkan, reset password (mengeluarkan
    sesi), ganti password sendiri, aturan password ≥ 8, sesi dicabut via `token_version`; akun TV = `viewer`.
  - `docs/runbooks/live-view-tv-pi.md` — satu baris: akun TV sebaiknya `viewer` khusus; perangkat hilang →
    nonaktifkan akun / reset password.
  - `ROADMAP.md` — baris sebelum `| E | Edge Jetson …`:
    `| UM | User management (tab User, nonaktif, reset & ganti password, cabut sesi) | [~] lokal selesai, PENDING deploy + verifikasi | — | spec + plan 2026-09-28 | |`
  - `CHANGELOG.md` — bullet dokumen + suite akhir.

```bash
git add README.md docs/runbooks/live-view-tv-pi.md ROADMAP.md CHANGELOG.md
git commit -m "docs(users): dokumentasi user management"
```

- [ ] **Step 3: Push** — `git push -u origin feat/user-management` (diizinkan). **Jangan** deploy, ssh, atau merge.
  Catatan untuk sesi perencana: deploy = `alembic upgrade head` (0018) di venv API + restart **isentinel-api**;
  sesi yang ada tetap valid (token tanpa `tv` = versi 0).
