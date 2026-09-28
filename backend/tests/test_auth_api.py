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
    monkeypatch.setattr(settings, "cookie_secure", True)  # httpx tidak replay cookie secure → uji 401 tanpa token valid
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
    assert client.post("/api/v1/users", json={"username": "uji-v1", "password": "rahasia123", "role": "viewer"}, headers=h).status_code == 200
    assert client.get("/api/v1/users").status_code == 401  # tanpa token

def test_delete_last_admin_blocked(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert client.delete(f"/api/v1/users/{me['id']}", headers=h).status_code == 409

def test_logout_clears_cookie(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    r = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.json() == {}
    assert "isentinel_token=" in r.headers.get("set-cookie", "")
    assert "Max-Age=0" in r.headers.get("set-cookie", "") or "expires=Thu, 01 Jan 1970" in r.headers.get("set-cookie", "")
    assert client.get("/api/v1/auth/me").status_code == 401

def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}

def test_patch_password_too_long_rejected(client):
    h = _admin_headers(client)
    r = client.post("/api/v1/users", json={"username": "uji-v1", "password": "rahasia123", "role": "viewer"}, headers=h)
    uid = r.json()["id"]
    r = client.patch(f"/api/v1/users/{uid}", json={"password": "x" * 73}, headers=h)
    assert r.status_code == 422

def test_patch_role_invalid_rejected(client):
    h = _admin_headers(client)
    r = client.post("/api/v1/users", json={"username": "uji-v2", "password": "rahasia123", "role": "viewer"}, headers=h)
    uid = r.json()["id"]
    assert client.patch(f"/api/v1/users/{uid}", json={"role": "superuser"}, headers=h).status_code == 422

def test_create_user_invalid_role_rejected(client):
    h = _admin_headers(client)
    assert client.post("/api/v1/users", json={"username": "uji-v3", "password": "rahasia123", "role": "root"}, headers=h).status_code == 422


def _token_with(uid: int, minutes_left: float) -> str:
    import jwt
    from datetime import datetime, timedelta, timezone
    from app.core.config import settings
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes_left)
    return jwt.encode({"sub": str(uid), "role": "admin", "exp": exp}, settings.jwt_secret, settings.jwt_algorithm)


def _admin_id(client) -> int:
    return client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["user"]["id"]


def test_session_cookie_renewed_past_half_life(client):
    """TV command center: token cookie yang lewat separuh umur diganti baru (sesi bergulir)."""
    from datetime import datetime, timezone
    from app.core.config import settings
    from app.core.security import decode_token
    old = _token_with(_admin_id(client), 60)
    r = client.get("/api/v1/auth/me", headers={"Cookie": f"isentinel_token={old}"})
    assert r.status_code == 200
    cookie = r.headers.get("set-cookie", "")
    assert cookie.startswith("isentinel_token=") and "httponly" in cookie.lower()
    new = cookie.split(";")[0].split("=", 1)[1]
    left = decode_token(new)["exp"] - datetime.now(timezone.utc).timestamp()
    assert left > settings.access_token_expire_min * 60 - 60


def test_session_cookie_not_renewed_when_fresh_or_bearer(client):
    uid = _admin_id(client)
    fresh = _token_with(uid, 2800)
    assert "set-cookie" not in client.get("/api/v1/auth/me", headers={"Cookie": f"isentinel_token={fresh}"}).headers
    old = _token_with(uid, 60)
    assert "set-cookie" not in client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old}"}).headers


def test_default_session_is_48_hours():
    from app.core.config import Settings
    assert Settings.model_fields["access_token_expire_min"].default == 2880
