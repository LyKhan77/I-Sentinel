import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db

@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:  # context manager memicu startup/bootstrap
        yield c
    app.dependency_overrides.clear()


def test_login_locks_after_max_attempts(client, monkeypatch):
    from app.api import auth as auth_mod

    auth_mod._FAILURES.clear()
    monkeypatch.setattr(auth_mod.settings, "login_max_attempts", 3)
    monkeypatch.setattr(auth_mod.settings, "login_lockout_min", 15)

    body = {"username": "admin", "password": "salah"}
    for _ in range(3):
        assert client.post("/api/v1/auth/login", json=body).status_code == 401

    r = client.post("/api/v1/auth/login", json=body)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_successful_login_resets_failures(client, monkeypatch):
    from app.api import auth as auth_mod

    auth_mod._FAILURES.clear()
    monkeypatch.setattr(auth_mod.settings, "login_max_attempts", 3)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "salah"})
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "salah"})
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "salah"}).status_code == 401
