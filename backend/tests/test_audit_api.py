from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.audit_log import AuditLog
from app.services import audit
from tests.conftest import admin_headers, viewer_headers  # noqa


@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed(db):
    audit.record(db, action="auth.login", actor_label="admin", status="ok")
    audit.record(db, action="camera.update", actor_label="admin",
                 target=("camera", 3, "Gerbang"), changes={"name": "Gerbang"}, status="ok")
    audit.record(db, action="attendance.correct", actor_label="op1", status="ok")
    audit.record(db, action="auth.login_failed", actor_label="intruder", status="failed")
    db.commit()


def test_viewer_forbidden(client, db):
    _seed(db)
    h = viewer_headers(client)
    assert client.get("/api/v1/audit-logs", headers=h).status_code == 403
    assert client.get("/api/v1/audit-logs/actors", headers=h).status_code == 403
    assert client.post("/api/v1/audit-logs/verify", headers=h).status_code == 403


def test_list_pagination_and_total(client, db):
    _seed(db)
    h = admin_headers(client)
    r = client.get("/api/v1/audit-logs?limit=2&offset=0", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    r2 = client.get("/api/v1/audit-logs?limit=2&offset=2", headers=h)
    assert len(r2.json()["items"]) == 2
    # urutan: terbaru dulu, id sebagai pemutus seri
    assert body["items"][0]["id"] > body["items"][1]["id"]


def test_list_filters(client, db):
    _seed(db)
    h = admin_headers(client)
    assert client.get("/api/v1/audit-logs?category=config", headers=h).json()["total"] == 1
    assert client.get("/api/v1/audit-logs?category=auth", headers=h).json()["total"] == 3
    assert client.get("/api/v1/audit-logs?action=auth.login_failed", headers=h).json()["total"] == 1
    assert client.get("/api/v1/audit-logs?actor=op1", headers=h).json()["total"] == 1
    assert client.get("/api/v1/audit-logs?status=failed", headers=h).json()["total"] == 1
    assert client.get("/api/v1/audit-logs?target_type=camera&target_id=3", headers=h).json()["total"] == 1
    assert client.get("/api/v1/audit-logs?q=Gerbang", headers=h).json()["total"] == 1
    assert client.get("/api/v1/audit-logs?q=gerbang", headers=h).json()["total"] == 1  # ILIKE


def test_list_from_to_filter(client, db):
    _seed(db)
    h = admin_headers(client)
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    # pakai params= agar '+' timezone di-encode benar (bila disusul literal di URL, '+' jadi spasi)
    assert client.get("/api/v1/audit-logs", params={"to": future}, headers=h).json()["total"] == 5
    assert client.get("/api/v1/audit-logs", params={"from": past}, headers=h).json()["total"] == 5
    assert client.get("/api/v1/audit-logs", params={"to": past}, headers=h).json()["total"] == 0


def test_item_shape(client, db):
    _seed(db)
    h = admin_headers(client)
    item = client.get("/api/v1/audit-logs?action=camera.update", headers=h).json()["items"][0]
    assert item["category"] == "config"
    assert item["action"] == "camera.update"
    assert item["actor_label"] == "admin"
    assert item["target_type"] == "camera"
    assert item["target_id"] == "3"
    assert item["target_label"] == "Gerbang"
    assert item["changes"] == {"name": "Gerbang"}
    assert "hash" not in item and "prev_hash" not in item


def test_actors_endpoint(client, db):
    _seed(db)
    r = client.get("/api/v1/audit-logs/actors", headers=admin_headers(client))
    assert r.status_code == 200
    assert sorted(r.json()) == ["admin", "intruder", "op1"]


def test_verify_endpoint_ok_and_tampered(client, db):
    h = admin_headers(client)
    _seed(db)
    r = client.post("/api/v1/audit-logs/verify", headers=h)
    assert r.json() == {"ok": True, "checked": 5, "first_break_id": None}
    # rusakkan satu baris langsung di DB → verify melapor
    row = db.query(AuditLog).order_by(AuditLog.id).first()
    row.status = "tampered"
    db.commit()
    r2 = client.post("/api/v1/audit-logs/verify", headers=h)
    assert r2.json()["ok"] is False
    assert r2.json()["first_break_id"] == row.id
