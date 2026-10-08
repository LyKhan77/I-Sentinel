"""sync_face_caption: edit caption identitas dengan klaim face_synced, lock modul bersama AI."""
import io
import json
import threading
import time
import urllib.error
from datetime import datetime, timezone

import pytest

from app.models import Alert, Camera, Event, EventAi, TelegramChat, Zone
from app.services import alert_ai, telegram

TOKEN = "123456:" + "C" * 35


@pytest.fixture
def ready(db, monkeypatch):
    """Alert photo terkirim + chat aktif (meniru fixture test_alert_ai)."""
    telegram.set_token(TOKEN)
    db.add(TelegramChat(label="Staff", chat_id="-1001", active=True))
    cam = Camera(name="Camera", host="camera.test")
    db.add(cam); db.flush()
    zone = Zone(camera_id=cam.id, name="Area", type="behavior", polygon=[])
    db.add(zone); db.flush()
    ev = Event(type="intrusion", camera_id=cam.id, zone_id=zone.id,
               severity="critical", ts_event=datetime.now(timezone.utc))
    db.add(ev); db.flush()
    alert = Alert(event_id=ev.id, camera_id=cam.id, zone_id=zone.id, type=ev.type,
                  status="sent", chat_id="-1001", message_id=77, message_photo=True)
    db.add(alert)
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


def _face(status, **extra):
    face = {"status": status}
    face.update(extra)
    return face


def test_sync_face_caption_edits_with_identity_and_ai_lines(db, ready):
    alert, calls, _ = ready
    alert.event.payload = {"face": _face("recognized", name="Budi", employee_id=1, score=0.83)}
    db.add(EventAi(event_id=alert.event_id, kind="caption", channel="auto",
                   status="ok", answer="Orang berjalan"))
    db.commit()
    assert alert_ai.sync_face_caption(db, alert.event_id) is True
    db.refresh(alert)
    assert alert.face_synced is True
    data = json.loads(calls[0].data)
    assert "<b>Identitas</b>: Dikenali: Budi" in data["caption"]
    assert "🤖 <b>AI</b>: Orang berjalan" in data["caption"]


def test_sync_face_caption_works_without_ai_text(db, ready):
    alert, calls, _ = ready
    alert.event.payload = {"face": _face("not_visible")}
    db.commit()
    assert alert_ai.sync_face_caption(db, alert.event_id) is True
    data = json.loads(calls[0].data)
    assert "<b>Identitas</b>: Wajah tidak terlihat jelas" in data["caption"]
    assert "AI" not in data["caption"]


def test_sync_face_caption_claims_once_and_releases_on_failure(db, ready, monkeypatch):
    alert, calls, replies = ready
    alert.event.payload = {"face": _face("unknown")}
    db.commit()
    original = telegram.edit_caption
    monkeypatch.setattr(telegram, "edit_caption",
                        lambda *a, **k: original(*a, **k, sleep=lambda _: None))
    replies.extend([urllib.error.HTTPError("u", 500, "Error", {}, io.BytesIO(json.dumps(
        {"ok": False, "description": "Internal"}).encode())) for _ in range(3)])
    assert alert_ai.sync_face_caption(db, alert.event_id) is False
    db.refresh(alert)
    assert alert.face_synced is False
    assert alert_ai.sync_face_caption(db, alert.event_id) is True
    assert len(calls) == 4  # 3 retry gagal + 1 sukses
    db.refresh(alert)
    assert alert.face_synced is True


def test_sync_face_caption_second_call_is_noop(db, ready):
    alert, calls, _ = ready
    alert.event.payload = {"face": _face("unknown")}
    db.commit()
    assert alert_ai.sync_face_caption(db, alert.event_id) is True
    assert alert_ai.sync_face_caption(db, alert.event_id) is False
    assert len(calls) == 1


def test_sync_face_caption_skips_text_only_alert_without_telegram_call(db, ready, caplog):
    import logging
    alert, calls, _ = ready
    alert.message_photo = False
    alert.event.payload = {"face": _face("unknown")}
    db.commit()
    with caplog.at_level(logging.INFO, logger="app.services.alert_ai"):
        assert alert_ai.sync_face_caption(db, alert.event_id) is False
    assert calls == []
    assert "identity_skipped_text_only" in caplog.text
    db.refresh(alert)
    assert alert.face_synced is False


def test_ai_edit_after_face_edit_renders_both_lines(db, ready):
    """Face sync dulu, teks AI datang belakangan → edit AI menampilkan keduanya."""
    alert, calls, _ = ready
    alert.event.payload = {"face": _face("recognized", name="Budi")}
    db.commit()
    assert alert_ai.sync_face_caption(db, alert.event_id) is True
    db.add(EventAi(event_id=alert.event_id, kind="caption", channel="auto",
                   status="ok", answer="Orang berjalan"))
    db.commit()
    assert alert_ai.sync_ai_caption(db, alert.event_id) is True
    assert len(calls) == 2
    data = json.loads(calls[1].data)
    assert "<b>Identitas</b>: Dikenali: Budi" in data["caption"]
    assert "🤖 <b>AI</b>: Orang berjalan" in data["caption"]


def test_concurrent_edits_are_serialised(db, ready, monkeypatch):
    """Dua edit bersamaan (worker AI + identitas) tidak boleh berada di dalam Telegram bersamaan."""
    alert, calls, _ = ready
    alert.event.payload = {"face": _face("recognized", name="Budi")}
    db.add(EventAi(event_id=alert.event_id, kind="caption", channel="auto",
                   status="ok", answer="Orang berjalan"))
    db.commit()

    guard = threading.Lock()
    state = {"inside": 0, "max": 0}
    release, first_inside = threading.Event(), threading.Event()
    real_edit = telegram.edit_caption

    def tracked_edit(*a, **k):
        with guard:
            state["inside"] += 1
            state["max"] = max(state["max"], state["inside"])
        first_inside.set()
        release.wait(3)
        try:
            return real_edit(*a, **k)
        finally:
            with guard:
                state["inside"] -= 1

    monkeypatch.setattr(telegram, "edit_caption", tracked_edit)
    t_ai = threading.Thread(target=alert_ai.sync_ai_caption, args=(db, alert.event_id))
    t_face = threading.Thread(target=alert_ai.sync_face_caption, args=(db, alert.event_id))
    t_ai.start()
    assert first_inside.wait(3)
    t_face.start()
    time.sleep(0.3)  # edit kedua mencapai Telegram sekarang bila tidak ada lock
    assert state["max"] == 1, "edit kedua harus menunggu edit pertama selesai"
    release.set()
    t_ai.join(5)
    t_face.join(5)
    assert state["max"] == 1 and not alert_ai._edit_lock.locked()
    assert "<b>Identitas</b>" in json.loads(calls[-1].data)["caption"]


@pytest.mark.parametrize("sync", ["sync_ai_caption", "sync_face_caption"])
def test_caption_is_rendered_while_holding_the_edit_lock(db, ready, monkeypatch, sync):
    """Render di dalam lock: caption basi yang menunggu lock tidak boleh menimpa yang lengkap."""
    alert, calls, _ = ready
    alert.event.payload = {"face": _face("unknown")}
    db.add(EventAi(event_id=alert.event_id, kind="caption", channel="auto",
                   status="ok", answer="Orang berjalan"))
    db.commit()
    seen = []
    real_build = alert_ai.build_caption

    def spy(*a, **k):
        seen.append(alert_ai._edit_lock.locked())
        return real_build(*a, **k)

    monkeypatch.setattr(alert_ai, "build_caption", spy)
    assert getattr(alert_ai, sync)(db, alert.event_id) is True
    assert seen and all(seen)


def test_ai_edit_renders_identity_that_arrived_while_waiting_for_the_lock(db, ready):
    alert, calls, _ = ready
    db.add(EventAi(event_id=alert.event_id, kind="caption", channel="auto",
                   status="ok", answer="Orang berjalan"))  # teks AI ada, identitas belum
    db.commit()
    result = {}
    alert_ai._edit_lock.acquire()  # edit lain sedang berjalan di Telegram
    try:
        t = threading.Thread(target=lambda: result.update(ok=alert_ai.sync_ai_caption(db, alert.event_id)))
        t.start()
        time.sleep(0.3)  # edit AI sudah mengklaim dan menunggu lock
        alert.event.payload = {"face": _face("recognized", name="Budi")}
        db.commit()
    finally:
        alert_ai._edit_lock.release()
    t.join(5)
    assert result.get("ok") is True
    assert "<b>Identitas</b>: Dikenali: Budi" in json.loads(calls[0].data)["caption"]
