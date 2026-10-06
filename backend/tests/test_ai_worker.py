"""Caption worker behavior with synthetic snapshots and no live network."""
from datetime import datetime, timedelta, timezone
from io import BytesIO

from PIL import Image
import pytest

from app.core.config import settings
from app.models import Camera, Event, EventAi, Zone
from app.services import llm_client
from app.ws.hub import hub


@pytest.fixture
def setup(db, tmp_path, monkeypatch):
    from app.services.ai_worker import AiWorker
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "llm_api_key", "sk-secret")
    Image.new("RGB", (100, 100)).save(tmp_path / "snap.jpg")
    cam = Camera(name="CAM-01", host="camera.test")
    db.add(cam); db.commit()
    zone = Zone(camera_id=cam.id, name="Area", type="behavior", polygon=[], ai_caption=True, ai_prompt="Fokus helm")
    db.add(zone); db.commit()
    ev = Event(type="intrusion", camera_id=cam.id, zone_id=zone.id, ts_event=datetime.now(timezone.utc), snapshot_path="snap.jpg")
    db.add(ev); db.commit()
    sent = []
    async def broadcast(payload):
        sent.append(payload)
    monkeypatch.setattr(hub, "broadcast", broadcast)
    clock = [100.0]
    return AiWorker(session_factory=lambda: db, clock=lambda: clock[0]), ev, zone, clock, sent


@pytest.mark.parametrize("condition", ["disabled", "attendance", "system", "zone_off", "no_zone", "no_snapshot", "expired"])
def test_enqueue_skip_conditions(db, setup, condition, monkeypatch):
    worker, ev, zone, _, _ = setup
    def forbidden(*args, **kwargs):
        pytest.fail("Skipped events must never invoke the LLM")
    monkeypatch.setattr(llm_client, "chat", forbidden)
    if condition == "disabled": monkeypatch.setattr(settings, "llm_enabled", False)
    elif condition in ("attendance", "system"): ev.type = condition
    elif condition == "zone_off": zone.ai_caption = False
    elif condition == "no_zone": ev.zone_id = None
    elif condition == "no_snapshot": ev.snapshot_path = None
    elif condition == "expired": ev.media_expired = True
    db.commit()
    assert worker.maybe_enqueue_caption(db, ev) is False
    assert db.query(EventAi).count() == 0
    worker.start(); worker.join_queue(0.2); worker.stop()


def test_enqueue_once_per_event(db, setup):
    worker, ev, _, _, _ = setup
    assert worker.maybe_enqueue_caption(db, ev)
    assert not worker.maybe_enqueue_caption(db, ev)
    assert db.query(EventAi).one().status == "pending"


def test_zone_throttle(db, setup):
    worker, ev, zone, clock, _ = setup
    assert worker.maybe_enqueue_caption(db, ev)
    ev2 = Event(type="intrusion", zone_id=zone.id, ts_event=ev.ts_event, snapshot_path="snap.jpg")
    db.add(ev2); db.commit()
    assert not worker.maybe_enqueue_caption(db, ev2)
    assert db.query(EventAi).count() == 1
    clock[0] += 60
    assert worker.maybe_enqueue_caption(db, ev2)


def test_queue_full_leaves_no_row(db, setup):
    from app.services.ai_worker import AiWorker
    _, ev, _, _, _ = setup
    worker = AiWorker(maxsize=1)
    assert worker.enqueue(999)
    assert not worker.maybe_enqueue_caption(db, ev)
    assert db.query(EventAi).count() == 0


def test_process_ok_uses_custom_prompt_and_snapshot(db, setup, monkeypatch):
    worker, ev, _, _, sent = setup
    def chat(messages, **kwargs):
        assert messages[0]["role"] == "system" and "identitas" in messages[0]["content"]
        content = messages[1]["content"]
        assert "Fokus helm" in content[0]["text"] and "CAM-01" in content[0]["text"]
        assert content[1]["type"] == "image_url"
        assert kwargs["timeout"] == 60
        return llm_client.LlmResult("Seseorang berjalan.", "stop", 1, 1, "test-model")
    monkeypatch.setattr(llm_client, "chat", chat)
    assert worker.maybe_enqueue_caption(db, ev)
    row = db.query(EventAi).one()
    worker.process(row.id, db)
    assert row.status == "ok" and row.answer == "Seseorang berjalan." and row.latency_ms >= 0
    assert sent == [{"kind": "ai", "event_id": ev.id, "status": "ok"}]


@pytest.mark.parametrize("message", ["LLM timeout", "sk-secret " + "x"*300])
def test_process_llm_error_marks_failed_without_raising(db, setup, monkeypatch, message):
    worker, ev, _, _, sent = setup
    def fail(*args, **kwargs): raise llm_client.LlmError(message)
    monkeypatch.setattr(llm_client, "chat", fail)
    worker.maybe_enqueue_caption(db, ev)
    row = db.query(EventAi).one()
    worker.process(row.id, db)
    assert row.status == "failed" and len(row.error) <= 255 and "sk-secret" not in row.error
    assert sent[-1]["status"] == "failed"


def test_recover(db, setup):
    from app.services.ai_worker import AiWorker
    _, ev, _, _, _ = setup
    now = datetime.now(timezone.utc)
    fresh = EventAi(event_id=ev.id, kind="caption", channel="auto", created_at=now)
    stale = EventAi(event_id=ev.id, kind="caption", channel="auto", created_at=now-timedelta(minutes=11))
    db.add_all([fresh, stale]); db.commit()
    worker = AiWorker()
    assert worker.recover(db, now) == 1
    assert stale.status == "failed" and stale.error == "interrupted by restart"
    assert fresh.status == "pending"


def test_caption_waits_for_slot_as_long_as_an_ask_may_hold_it(db, setup, monkeypatch):
    """Tanya AI memegang slot sampai llm_timeout_ask_s; caption yang menunggu lebih pendek gagal permanen."""
    from contextlib import contextmanager
    worker, ev, _, _, _ = setup
    waits = []
    @contextmanager
    def slot(timeout=5.0):
        waits.append(timeout)
        yield
    monkeypatch.setattr(llm_client, "slot", slot)
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: llm_client.LlmResult("Seseorang.", "stop", 1, 1, "test-model"))
    worker.maybe_enqueue_caption(db, ev)
    row = db.query(EventAi).one()
    worker.process(row.id, db)
    assert row.status == "ok"
    assert waits and waits[0] >= settings.llm_timeout_ask_s


def test_recover_fails_pending_rows_that_do_not_fit_the_queue(db, setup):
    """Baris pending yang tak muat antrean tidak boleh menggantung (maybe_enqueue_caption menolak event ber-baris)."""
    from app.services.ai_worker import AiWorker
    _, ev, _, _, _ = setup
    now = datetime.now(timezone.utc)
    rows = [EventAi(event_id=ev.id, kind="caption", channel="auto", created_at=now) for _ in range(2)]
    db.add_all(rows); db.commit()
    assert AiWorker(maxsize=1).recover(db, now) == 1
    assert sorted(r.status for r in rows) == ["failed", "pending"]
    assert next(r for r in rows if r.status == "failed").error == "antrean penuh"
