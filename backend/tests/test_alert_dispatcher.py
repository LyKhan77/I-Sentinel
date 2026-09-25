from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.event import Event
from app.models.telegram_chat import TelegramChat
from app.models.zone import Zone
from app.services import telegram
from app.services.alert_dispatcher import AlertDispatcher

TOKEN = "123456:" + "B" * 35


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_deliver(token, chat_id, caption, photo=None, **kw):
        calls.append({"token": token, "chat_id": chat_id, "caption": caption, "photo": photo})
        return "sent", None

    monkeypatch.setattr(telegram, "deliver", fake_deliver)
    return calls


def _alert(db, tmp_path, monkeypatch, snapshot=b"\xff\xd8jpg", configured=True):
    root = tmp_path / "media"
    (root / "snapshots").mkdir(parents=True)
    monkeypatch.setattr(settings, "storage_root", str(root))
    if snapshot is not None:
        (root / "snapshots" / "a.jpg").write_bytes(snapshot)
    if configured:
        telegram.set_token(TOKEN)
        db.add(TelegramChat(label="Satpam", chat_id="-1001", active=True))
    cam = Camera(name="Lorong Server", host="1.2.3.4")
    db.add(cam); db.commit()
    zone = Zone(camera_id=cam.id, name="Lorong-15", type="behavior", polygon=[[0, 0], [1, 0], [1, 1]])
    db.add(zone); db.commit()
    ev = Event(type="intrusion", camera_id=cam.id, zone_id=zone.id, severity="warning",
               ts_event=datetime(2026, 9, 25, 4, 42, 7, tzinfo=timezone.utc),
               snapshot_path="snapshots/a.jpg" if snapshot is not None else None)
    db.add(ev); db.commit()
    alert = Alert(event_id=ev.id, camera_id=cam.id, zone_id=zone.id, type="intrusion",
                  severity="warning", status="queued")
    db.add(alert); db.commit()
    return alert


def _dispatcher():
    return AlertDispatcher(snapshot_polls=3, poll_s=0, sleep=lambda s: None)


def test_process_sends_photo_with_caption(db, tmp_path, sent, monkeypatch):
    alert = _alert(db, tmp_path, monkeypatch)
    _dispatcher().process(alert.id, db)
    db.refresh(alert)
    assert (alert.status, alert.chat_id, alert.error) == ("sent", "-1001", None)
    assert sent[0]["photo"] == b"\xff\xd8jpg"
    assert sent[0]["caption"].startswith("🚨 Intrusi — Lorong Server · zona Lorong-15")


def test_process_waits_for_late_snapshot(db, tmp_path, sent, monkeypatch):
    alert = _alert(db, tmp_path, monkeypatch)
    ev = db.get(Event, alert.event_id)
    ev.snapshot_path = None
    db.commit()
    polls = []

    def late(_s):
        polls.append(1)
        if len(polls) == 2:
            ev.snapshot_path = "snapshots/a.jpg"
            db.commit()

    AlertDispatcher(snapshot_polls=5, poll_s=0.5, sleep=late).process(alert.id, db)
    assert sent[0]["photo"] == b"\xff\xd8jpg" and len(polls) == 2


def test_process_falls_back_to_text_when_snapshot_missing(db, tmp_path, sent, monkeypatch):
    alert = _alert(db, tmp_path, monkeypatch, snapshot=None)
    _dispatcher().process(alert.id, db)
    db.refresh(alert)
    assert alert.status == "sent" and sent[0]["photo"] is None


def test_process_not_configured_makes_no_call(db, tmp_path, sent, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    alert = _alert(db, tmp_path, monkeypatch, configured=False)
    _dispatcher().process(alert.id, db)
    db.refresh(alert)
    assert alert.status == "not_configured" and sent == []


def test_process_records_failure(db, tmp_path, monkeypatch):
    monkeypatch.setattr(telegram, "deliver", lambda *a, **k: ("failed", "Forbidden: bot was kicked"))
    alert = _alert(db, tmp_path, monkeypatch)
    _dispatcher().process(alert.id, db)
    db.refresh(alert)
    assert (alert.status, alert.error) == ("failed", "Forbidden: bot was kicked")


def test_worker_thread_drains_queue(db, tmp_path, sent, monkeypatch):
    alert = _alert(db, tmp_path, monkeypatch)

    class _NoClose:
        def __init__(self, s): self.s = s
        def __getattr__(self, name): return getattr(self.s, name)
        def close(self): pass

    d = AlertDispatcher(snapshot_polls=1, poll_s=0, sleep=lambda s: None, session_factory=lambda: _NoClose(db))
    d.start()
    try:
        assert d.enqueue(alert.id)
        d.join_queue(timeout=5)
    finally:
        d.stop()
    db.refresh(alert)
    assert alert.status == "sent"


def test_snapshot_path_outside_root_sends_text(db, tmp_path, sent, monkeypatch):
    """snapshot_path yang kabur dari storage_root → fallback teks, tidak baca file di luar root."""
    root = tmp_path / "media"
    (root / "snapshots").mkdir(parents=True)
    # File NYATA di luar root: bila guard realpath dihapus, ia akan ter-baca dan tes ini gagal.
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"\xff\xd8secret")
    monkeypatch.setattr(settings, "storage_root", str(root))
    telegram.set_token(TOKEN)
    db.add(TelegramChat(label="Satpam", chat_id="-1001", active=True))
    cam = Camera(name="Lorong Server", host="1.2.3.4"); db.add(cam); db.commit()
    zone = Zone(camera_id=cam.id, name="Lorong-15", type="behavior",
                polygon=[[0, 0], [1, 0], [1, 1]]); db.add(zone); db.commit()
    for escape in ("../outside.jpg", str(outside)):
        ev = Event(type="intrusion", camera_id=cam.id, zone_id=zone.id, severity="warning",
                   ts_event=datetime(2026, 9, 25, 4, 42, 7, tzinfo=timezone.utc), snapshot_path=escape)
        db.add(ev); db.commit()
        alert = Alert(event_id=ev.id, camera_id=cam.id, zone_id=zone.id, type="intrusion",
                      severity="warning", status="queued")
        db.add(alert); db.commit()
        sent.clear()
        AlertDispatcher(snapshot_polls=1, poll_s=0, sleep=lambda s: None).process(alert.id, db)
        db.refresh(alert)
        assert alert.status == "sent" and sent[0]["photo"] is None
