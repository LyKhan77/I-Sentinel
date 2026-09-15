from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.core.db import get_db
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
    monkeypatch.setattr(settings, "cookie_secure", True)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


VALID_ZONE = {"name": "z1", "type": "restricted",
              "polygon": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]]}


def _camera(client, h, name="cam1"):
    return client.post("/api/v1/cameras", json={"name": name, "host": "1.2.3.4"}, headers=h).json()


def _camera_row(db, name="cam1"):
    cam = Camera(name=name, host="1.2.3.4")
    db.add(cam); db.commit(); db.refresh(cam)
    return cam


def _event(db, camera_id):
    ev = Event(type="loitering", camera_id=camera_id, ts_event=datetime.now(timezone.utc))
    db.add(ev); db.commit(); db.refresh(ev)
    return ev


def test_zone_analyzer_params_persist(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    body = {**VALID_ZONE, "camera_id": cam["id"], "loiter_seconds": 15, "speed_limit_mps": 2.5}
    r = client.post("/api/v1/zones", json=body, headers=h)
    assert r.status_code == 200
    assert r.json()["loiter_seconds"] == 15 and r.json()["speed_limit_mps"] == 2.5
    got = client.get(f"/api/v1/zones/{r.json()['id']}", headers=h).json()
    assert got["loiter_seconds"] == 15 and got["speed_limit_mps"] == 2.5


def test_zone_analyzer_params_default_off(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID_ZONE, "camera_id": cam["id"]}, headers=h)
    assert r.status_code == 200
    assert r.json()["loiter_seconds"] == 0 and r.json()["speed_limit_mps"] == 0


@pytest.mark.parametrize("field", ["loiter_seconds", "speed_limit_mps"])
def test_zone_negative_analyzer_params_422(client, field):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID_ZONE, "camera_id": cam["id"], field: -1}, headers=h)
    assert r.status_code == 422


def test_zone_patch_sets_analyzer_params(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID_ZONE, "camera_id": cam["id"]}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/zones/{zid}", json={"loiter_seconds": 30, "speed_limit_mps": 1.5}, headers=h)
    assert r.status_code == 200
    assert r.json()["loiter_seconds"] == 30 and r.json()["speed_limit_mps"] == 1.5


def test_camera_patch_meters_per_pixel_roundtrip(client):
    h = _admin_headers(client)
    cid = _camera(client, h)["id"]
    r = client.patch(f"/api/v1/cameras/{cid}", json={"meters_per_pixel": 0.01}, headers=h)
    assert r.status_code == 200
    assert r.json()["meters_per_pixel"] == 0.01
    assert client.get(f"/api/v1/cameras/{cid}", headers=h).json()["meters_per_pixel"] == 0.01


def test_camera_meters_per_pixel_default_null(client):
    h = _admin_headers(client)
    cid = _camera(client, h)["id"]
    assert client.get(f"/api/v1/cameras/{cid}", headers=h).json()["meters_per_pixel"] is None


@pytest.mark.parametrize("value", [-1, 0])
def test_camera_meters_per_pixel_invalid_422(client, value):
    h = _admin_headers(client)
    cid = _camera(client, h)["id"]
    assert client.patch(f"/api/v1/cameras/{cid}", json={"meters_per_pixel": value}, headers=h).status_code == 422


def test_alert_event_id_unique(db):
    cam = _camera_row(db, "cam-alert")
    ev = _event(db, cam.id)
    db.add(Alert(event_id=ev.id, camera_id=cam.id, zone_id=None, type="loitering",
                 severity="warning", status="sent", chat_id="123"))
    db.commit()
    db.add(Alert(event_id=ev.id, camera_id=cam.id, zone_id=None, type="loitering",
                 severity="warning", status="rate_limited"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.query(Alert).filter_by(event_id=ev.id).count() == 1


def test_alert_ok_status_and_event_relationship(db):
    cam = _camera_row(db, "cam-alert2")
    ev = _event(db, cam.id)
    a = Alert(event_id=ev.id, camera_id=cam.id, type="running", severity="critical",
              status="not_configured", error="no telegram token")
    db.add(a); db.commit(); db.refresh(a)
    assert a.id is not None and a.created_at is not None
    assert Alert.__table__.c.created_at.type.timezone is True  # tz-aware column (SQLite drops tzinfo on read-back)
    assert a.event.id == ev.id and a.chat_id is None


def test_telegram_chat_roundtrip(db):
    db.add(TelegramChat(label="ops", chat_id="-100123"))
    db.commit()
    row = db.query(TelegramChat).filter_by(chat_id="-100123").one()
    assert row.label == "ops" and row.active is True and row.created_at is not None
