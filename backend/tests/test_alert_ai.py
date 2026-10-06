"""AI alert synchronization uses fake Telegram I/O only."""
import io
import json
import urllib.error
from datetime import datetime, timezone

import pytest

from app.models import Alert, Camera, Event, EventAi, TelegramChat, Zone
from app.services import telegram

TOKEN = "123456:" + "A" * 35


@pytest.fixture
def ready(db, monkeypatch):
    telegram.set_token(TOKEN)
    db.add(TelegramChat(label="Staff", chat_id="-1001", active=True))
    cam = Camera(name="Camera", host="camera.test")
    db.add(cam); db.flush()
    zone = Zone(camera_id=cam.id, name="Area", type="behavior", polygon=[])
    db.add(zone); db.flush()
    ev = Event(type="intrusion", camera_id=cam.id, zone_id=zone.id,
               severity="warning", ts_event=datetime.now(timezone.utc))
    db.add(ev); db.flush()
    alert = Alert(event_id=ev.id, camera_id=cam.id, zone_id=zone.id, type=ev.type,
                  status="sent", chat_id="-1001", message_id=77, message_photo=True)
    db.add_all([alert, EventAi(event_id=ev.id, kind="caption", channel="auto",
                               status="ok", answer="a <b> & c\n d")])
    db.commit()
    calls, replies = [], []

    def fake(req, timeout=None):
        assert not db.in_transaction(), "Telegram I/O must not hold the DB transaction"
        calls.append(req)
        reply = replies.pop(0) if replies else {"ok": True, "result": True}
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(telegram, "_urlopen", fake)
    return alert, calls, replies


@pytest.mark.parametrize("guard", ["queued", "failed", "rate_limited", "not_configured",
     "no_message", "text", "synced", "no_caption", "pending", "failed_caption", "ask_only",
     "no_token", "no_chat", "no_alert"], ids=str)
def test_guards_skip_edit(db, ready, guard, monkeypatch):
    from app.services import alert_ai
    alert, calls, _ = ready
    event_id = alert.event_id
    if guard in ("queued", "failed", "rate_limited", "not_configured"):
        alert.status = guard
    elif guard == "no_message": alert.message_id = None
    elif guard == "text": alert.message_photo = False
    elif guard == "synced": alert.ai_synced = True
    elif guard == "no_caption": db.query(EventAi).delete()
    elif guard == "pending": db.query(EventAi).one().status = "pending"
    elif guard == "failed_caption": db.query(EventAi).one().status = "failed"
    elif guard == "ask_only": db.query(EventAi).one().kind = "ask"
    elif guard == "no_token": monkeypatch.setattr(telegram, "get_token", lambda: "")
    elif guard == "no_chat": db.query(TelegramChat).one().active = False
    elif guard == "no_alert": db.delete(alert)
    db.commit()
    assert alert_ai.sync_ai_caption(db, event_id) is False
    assert calls == []


def test_ai_text_uses_latest_ok_caption_only(db, ready):
    from app.services import alert_ai
    alert, _, _ = ready
    db.add_all([
        EventAi(event_id=alert.event_id, kind="caption", channel="auto", status="ok", answer="Latest"),
        EventAi(event_id=alert.event_id, kind="caption", channel="auto", status="failed", answer="Failed"),
        EventAi(event_id=alert.event_id, kind="ask", channel="web", status="ok", answer="Manual"),
    ])
    db.commit()
    assert alert_ai.ai_text(db, alert.event_id) == "Latest"


def test_edit_adds_ai_line_and_marks_synced(db, ready):
    from app.services import alert_ai
    alert, calls, _ = ready
    event_id = alert.event_id
    assert alert_ai.sync_ai_caption(db, event_id) is True
    db.refresh(alert)
    assert alert.ai_synced is True and alert.status == "sent"
    assert len(calls) == 1 and calls[0].full_url.endswith("/editMessageCaption")
    data = json.loads(calls[0].data)
    assert data["chat_id"] == "-1001" and data["message_id"] == 77
    assert "🤖 <b>AI</b>: a &lt;b&gt; &amp; c d" in data["caption"]


def test_failure_does_not_raise_or_mark_synced(db, ready, monkeypatch, caplog):
    from app.services import alert_ai
    alert, calls, replies = ready
    original = telegram.edit_caption
    monkeypatch.setattr(telegram, "edit_caption", lambda *a, **k: original(*a, **k, sleep=lambda _: None))
    replies.extend([urllib.error.HTTPError("u", 500, "Error", {}, io.BytesIO(json.dumps(
        {"ok": False, "description": f"Bad Request: denied {TOKEN}"}).encode())) for _ in range(3)])
    assert alert_ai.sync_ai_caption(db, alert.event_id) is False
    db.refresh(alert)
    assert alert.ai_synced is False and alert.status == "sent"
    assert len(calls) == 3 and TOKEN not in caplog.text


def test_not_modified_is_success(db, ready):
    from app.services import alert_ai
    alert, calls, replies = ready
    replies.append(urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(json.dumps(
        {"ok": False, "description": "Bad Request: message is not modified"}).encode())))
    assert alert_ai.sync_ai_caption(db, alert.event_id) is True
    db.refresh(alert)
    assert alert.ai_synced and len(calls) == 1


def test_second_call_is_noop(db, ready):
    from app.services import alert_ai
    alert, calls, _ = ready
    event_id = alert.event_id
    assert alert_ai.sync_ai_caption(db, event_id) is True
    assert alert_ai.sync_ai_caption(db, event_id) is False
    assert len(calls) == 1


def test_unexpected_error_is_contained_without_secret_logging(db, ready, monkeypatch, caplog):
    from app.services import alert_ai
    alert, _, _ = ready
    def boom(*args):
        raise RuntimeError(TOKEN)
    monkeypatch.setattr(telegram, "edit_caption", boom)
    assert alert_ai.sync_ai_caption(db, alert.event_id) is False
    db.refresh(alert)
    assert not alert.ai_synced and alert.status == "sent" and TOKEN not in caplog.text


def test_stale_session_object_cannot_cause_a_second_edit(db, ready):
    """SessionLocal memakai expire_on_commit=False: objek alert lama di memori tidak boleh meloloskan guard
    setelah pemanggil lain sudah mengedit dan menandai ai_synced."""
    from sqlalchemy import text
    from app.services import alert_ai
    alert, calls, _ = ready
    db.expire_on_commit = False  # seperti sesi produksi
    assert alert.ai_synced is False  # dimuat dan tertahan di identity map
    db.execute(text("UPDATE alert SET ai_synced = 1 WHERE id = :i"), {"i": alert.id})
    db.commit()
    assert alert.ai_synced is False  # objek di sesi ini basi
    assert alert_ai.sync_ai_caption(db, alert.event_id) is False
    assert calls == []


def test_failed_edit_releases_the_claim_so_a_later_call_can_retry(db, ready, monkeypatch):
    from sqlalchemy import text
    from app.services import alert_ai
    alert, calls, replies = ready
    original = telegram.edit_caption
    monkeypatch.setattr(telegram, "edit_caption", lambda *a, **k: original(*a, **k, sleep=lambda _: None))
    replies.extend([urllib.error.HTTPError("u", 500, "Error", {}, io.BytesIO(json.dumps(
        {"ok": False, "description": "Internal"}).encode())) for _ in range(3)])
    assert alert_ai.sync_ai_caption(db, alert.event_id) is False
    assert db.execute(text("SELECT ai_synced FROM alert WHERE id = :i"), {"i": alert.id}).scalar() == 0
    assert alert_ai.sync_ai_caption(db, alert.event_id) is True  # balasan default sukses
    assert len(calls) == 4
    assert db.execute(text("SELECT ai_synced FROM alert WHERE id = :i"), {"i": alert.id}).scalar() == 1


def test_build_caption_requires_an_event(db):
    """Event hilang dulu membuat dispatcher gagal cepat (alert 'failed'); jangan mengirim pesan kosong."""
    from types import SimpleNamespace
    from app.services import alert_ai
    with pytest.raises(ValueError):
        alert_ai.build_caption(db, SimpleNamespace(event=None, camera_id=None, zone_id=None), None)
