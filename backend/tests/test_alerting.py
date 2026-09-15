import json
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.event import Event
from app.models.telegram_chat import TelegramChat
from app.models.zone import Zone
from app.services import alerting
from app.services.events_consumer import handle_message

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class _Resp:
    def __init__(self, body: bytes = b'{"ok":true}'):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def calls(monkeypatch):
    """Record urlopen calls; default response ok:true."""
    calls = []

    def fake_urlopen(req, timeout=10):
        calls.append(req)
        return _Resp()

    monkeypatch.setattr(alerting.urllib.request, "urlopen", fake_urlopen)
    return calls


@pytest.fixture
def broadcast(monkeypatch):
    sent = []

    async def fake(payload):
        sent.append(payload)

    monkeypatch.setattr(alerting.hub, "broadcast", fake)
    return sent


def _camera(db, name="cam-alerting"):
    cam = Camera(name=name, host="1.2.3.4")
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


def _event(db, camera_id=None, zone_id=None, type="loitering", severity="critical"):
    ev = Event(type=type, camera_id=camera_id, zone_id=zone_id, severity=severity,
               ts_event=NOW)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def test_info_below_min_no_row(db, broadcast):
    cam = _camera(db)
    ev = _event(db, cam.id, severity="info")
    assert alerting.should_alert(db, ev, now=NOW) == (False, "below_min_severity")
    assert alerting.handle(db, ev, now=NOW) is None
    assert db.query(Alert).count() == 0


def test_critical_no_token_not_configured(db, broadcast, calls, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    cam = _camera(db)
    ev = _event(db, cam.id)
    a = alerting.handle(db, ev, now=NOW)
    assert a is not None and a.status == "not_configured" and a.chat_id is None
    assert calls == []  # no network call
    assert db.query(Alert).count() == 1


def test_critical_token_chat_sent(db, broadcast, calls, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "tok")
    db.add(TelegramChat(label="ops", chat_id="-100123"))
    db.commit()
    cam = _camera(db)
    ev = _event(db, cam.id)
    a = alerting.handle(db, ev, now=NOW)
    assert a is not None and a.status == "sent"
    assert a.chat_id == "-100123"
    assert len(calls) == 1
    assert any(p.get("kind") == "alert" and p.get("status") == "sent" for p in broadcast)


def test_second_within_window_rate_limited(db, broadcast, calls, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "tok")
    db.add(TelegramChat(label="ops", chat_id="-100123"))
    db.commit()
    cam = _camera(db)
    alerting.handle(db, _event(db, cam.id), now=NOW)
    a2 = alerting.handle(db, _event(db, cam.id), now=NOW)
    assert a2 is not None and a2.status == "rate_limited"
    assert len(calls) == 1  # only the first alert was sent
    assert db.query(Alert).count() == 2


def test_window_expiry_alerts_again(db, broadcast, calls, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    cam = _camera(db)
    alerting.handle(db, _event(db, cam.id), now=NOW)
    a2 = alerting.handle(db, _event(db, cam.id), now=NOW + timedelta(minutes=6))
    assert a2 is not None and a2.status == "not_configured"
    assert db.query(Alert).count() == 2


def test_urlopen_error_failed_with_retries(db, broadcast, calls, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "tok")
    db.add(TelegramChat(label="ops", chat_id="-100123"))
    db.commit()
    monkeypatch.setattr(alerting.time, "sleep", lambda _s: None)
    calls2 = []

    def boom(req, timeout=10):
        calls2.append(req)
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(alerting.urllib.request, "urlopen", boom)
    cam = _camera(db)
    a = alerting.handle(db, _event(db, cam.id), now=NOW)
    assert a is not None and a.status == "failed"
    assert "boom" in a.error
    assert len(calls2) == 3  # 3 attempts


def test_zone_telegram_off_no_row(db, broadcast, calls, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "tok")
    db.add(TelegramChat(label="ops", chat_id="-100123"))
    cam = _camera(db)
    zone = Zone(camera_id=cam.id, name="z1", type="restricted",
                polygon=[[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]], telegram=False)
    db.add(zone)
    db.commit()
    db.refresh(zone)
    ev = _event(db, cam.id, zone_id=zone.id)
    assert alerting.should_alert(db, ev, now=NOW) == (False, "zone_telegram_off")
    assert alerting.handle(db, ev, now=NOW) is None
    assert db.query(Alert).count() == 0
    assert calls == []


def test_events_consumer_hook_creates_alert(db, broadcast, calls, monkeypatch):
    """Ingest → alerting.handle runs before the event broadcast."""
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    cam = _camera(db)
    payload = json.dumps({
        "event_id": str(uuid.uuid4()),
        "type": "intrusion",
        "camera_id": cam.id,
        "severity": "critical",
        "ts_event": NOW.isoformat(),
    }).encode()
    handle_message(db, "isentinel/events", payload)
    assert db.query(Alert).count() == 1
    assert db.query(Alert).one().status == "not_configured"
