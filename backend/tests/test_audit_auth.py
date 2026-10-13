import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.audit_log import AuditLog
from tests.conftest import admin_headers  # noqa


@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    from app.api import auth
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "cookie_secure", True)
    auth._FAILURES.clear()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    auth._FAILURES.clear()


def test_login_success_recorded(client, db):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"})
    assert r.status_code == 200
    row = db.query(AuditLog).filter_by(action="auth.login").one()
    assert row.status == "ok"
    assert row.actor_label == "admin"
    assert row.actor_id is not None  # terisi (admin id 1)
    assert row.category == "auth"


def test_login_failed_recorded(client, db):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "salah"})
    assert r.status_code == 401
    row = db.query(AuditLog).filter_by(action="auth.login_failed").one()
    assert row.status == "failed"
    assert row.actor_label == "admin"  # username yang dicoba, walau salah


def test_lockout_recorded(client, db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "login_max_attempts", 2)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "salah"})
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "salah"})
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "salah"})
    assert r.status_code == 429
    row = db.query(AuditLog).filter_by(action="auth.lockout").one()
    assert row.status == "failed"
    assert db.query(AuditLog).filter_by(action="auth.login_failed").count() == 2


def test_change_password_recorded(client, db):
    h = admin_headers(client)
    r = client.post("/api/v1/auth/change-password",
                    json={"current_password": "boot123", "new_password": "barubanget1"}, headers=h)
    assert r.status_code == 200
    row = db.query(AuditLog).filter_by(action="auth.password_change").one()
    assert row.status == "ok"
    assert row.actor_label == "admin"
    assert row.changes is None  # jejak audit tidak pernah memuat password
