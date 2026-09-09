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
    assert client.post("/api/v1/users", json={"username": "v1", "password": "pw12345", "role": "viewer"}, headers=h).status_code == 200
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
    r = client.post("/api/v1/users", json={"username": "v1", "password": "pw12345", "role": "viewer"}, headers=h)
    uid = r.json()["id"]
    r = client.patch(f"/api/v1/users/{uid}", json={"password": "x" * 73}, headers=h)
    assert r.status_code == 422

def test_patch_role_invalid_rejected(client):
    h = _admin_headers(client)
    r = client.post("/api/v1/users", json={"username": "v2", "password": "pw12345", "role": "viewer"}, headers=h)
    uid = r.json()["id"]
    assert client.patch(f"/api/v1/users/{uid}", json={"role": "superuser"}, headers=h).status_code == 422

def test_create_user_invalid_role_rejected(client):
    h = _admin_headers(client)
    assert client.post("/api/v1/users", json={"username": "v3", "password": "pw12345", "role": "root"}, headers=h).status_code == 422
