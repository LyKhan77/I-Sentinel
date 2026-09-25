import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.event import Event
from app.models.telegram_chat import TelegramChat
from tests.conftest import *  # noqa


@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _seed(db, status="sent", sev="warning"):
    cam = Camera(name=f"cam-{uuid.uuid4().hex[:6]}", host="1.2.3.4")
    db.add(cam); db.commit(); db.refresh(cam)
    ev = Event(type="loitering", camera_id=cam.id, severity=sev, ts_event=datetime.now(timezone.utc))
    db.add(ev); db.commit(); db.refresh(ev)
    alert = Alert(event_id=ev.id, camera_id=cam.id, zone_id=None, type=ev.type,
                  severity=sev, status=status)
    db.add(alert); db.commit(); db.refresh(alert)
    return ev, alert


def test_list_alerts_requires_auth(client):
    assert client.get("/api/v1/alerts").status_code == 401


def test_list_alerts_filtered_by_event(client, db):
    ev, _ = _seed(db, status="sent")
    _seed(db, status="failed")
    h = _admin_headers(client)
    rows = client.get(f"/api/v1/alerts?event_id={ev.id}", headers=h).json()
    assert len(rows) == 1
    assert rows[0]["event_id"] == ev.id and rows[0]["status"] == "sent"
    assert len(client.get("/api/v1/alerts", headers=h).json()) == 2


def test_list_alerts_limit_cap(client, db):
    for _ in range(3):
        _seed(db, status="sent")
    h = _admin_headers(client)
    assert len(client.get("/api/v1/alerts?limit=2", headers=h).json()) == 2
    assert client.get("/api/v1/alerts?limit=201", headers=h).status_code == 422


def test_by_events_maps_latest_status(client, db):
    ev1, _ = _seed(db, status="sent")
    ev2, _ = _seed(db, status="rate_limited")
    _seed(db, status="failed")  # not requested
    h = _admin_headers(client)
    r = client.get(f"/api/v1/alerts/by-events?ids={ev1.event_id},{ev2.event_id}", headers=h)
    assert r.status_code == 200
    assert r.json() == {ev1.event_id: "sent", ev2.event_id: "rate_limited"}


def test_by_events_requires_auth(client):
    assert client.get("/api/v1/alerts/by-events?ids=x").status_code == 401


def test_telegram_status_not_configured_counts_active_chats(client, db):
    db.add_all([
        TelegramChat(label="ops", chat_id="-1001", active=True),
        TelegramChat(label="ops2", chat_id="-1002", active=True),
        TelegramChat(label="off", chat_id="-1003", active=False),
    ])
    db.commit()
    h = _admin_headers(client)
    body = client.get("/api/v1/telegram/status", headers=h).json()
    assert body == {"configured": False, "active_chats": 2}


def test_telegram_status_configured_when_token_set(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    h = _admin_headers(client)
    assert client.get("/api/v1/telegram/status", headers=h).json()["configured"] is True


def test_list_alerts_with_null_camera_is_200(client, db):
    ev = Event(type="system", camera_id=None, severity="critical", ts_event=datetime.now(timezone.utc))
    db.add(ev); db.commit(); db.refresh(ev)
    db.add(Alert(event_id=ev.id, camera_id=None, zone_id=None, type="system", severity="critical",
                 status="not_configured"))
    db.commit()
    r = client.get("/api/v1/alerts", headers=_admin_headers(client))
    assert r.status_code == 200 and r.json()[0]["camera_id"] is None
