from datetime import datetime, timedelta, timezone

import pytest

from app.models.event import Event
from app.models.node import Node
from app.services import node_health
from app.ws.hub import hub

T0 = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def sent(monkeypatch):
    out = {"ws": [], "tg": []}
    async def fake_broadcast(payload):
        out["ws"].append(payload)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    return out


def _send(out):
    return lambda db, text: out["tg"].append(text) or True


def _node(db, status="online", seen=T0):
    n = Node(name="server", status=status, last_seen=seen)
    db.add(n)
    db.commit()
    return n


def _system(db):
    return db.query(Event).filter_by(type="system").order_by(Event.id).all()


def test_timeout_marks_offline_once_with_event_ws_and_telegram(db, sent):
    _node(db, seen=T0)
    assert node_health.check(db, now=T0 + timedelta(seconds=30), send=_send(sent)) == 0
    assert node_health.check(db, now=T0 + timedelta(seconds=40), send=_send(sent)) == 1
    assert node_health.check(db, now=T0 + timedelta(seconds=60), send=_send(sent)) == 0  # sudah offline
    [ev] = _system(db)
    assert ev.severity == "warning" and ev.payload == {"node": "server", "reason": "timeout"}
    assert len(sent["ws"]) == 1 and sent["ws"][0]["type"] == "system"
    assert len(sent["tg"]) == 1 and "server" in sent["tg"][0] and "offline" in sent["tg"][0]


def test_lwt_then_timeout_single_transition(db, sent):
    n = _node(db, seen=T0)
    assert node_health.mark_offline(db, n, "lwt", now=T0, send=_send(sent)) is True
    assert node_health.check(db, now=T0 + timedelta(minutes=5), send=_send(sent)) == 0
    assert len(_system(db)) == 1 and len(sent["tg"]) == 1


def test_online_after_offline_emits_recovered(db, sent):
    n = _node(db, status="offline", seen=T0)
    now = T0 + timedelta(minutes=12)
    assert node_health.mark_online(db, n, now=now, since=T0, send=_send(sent)) is True
    assert n.status == "online"
    [ev] = _system(db)
    assert ev.severity == "info" and ev.payload == {"node": "server", "reason": "online"}
    assert "pulih" in sent["tg"][0] and "12" in sent["tg"][0]  # durasi offline
    assert node_health.mark_online(db, n, now=now, send=_send(sent)) is False  # sudah online


def test_unknown_to_online_no_event(db, sent):
    n = _node(db, status="unknown", seen=None)
    assert node_health.mark_online(db, n, now=T0, send=_send(sent)) is False
    assert n.status == "online" and _system(db) == [] and sent["tg"] == []


def test_without_telegram_transition_still_recorded(db, sent):
    n = _node(db)
    assert node_health.mark_offline(db, n, "lwt", now=T0, send=lambda db, t: False) is True
    assert n.status == "offline" and len(_system(db)) == 1


def test_monitor_runs_check_and_stops(monkeypatch):
    calls = []
    monkeypatch.setattr(node_health, "check", lambda db: calls.append(db) or 0)
    m = node_health.NodeHealthMonitor(interval_s=0.01)
    m.start()
    import time
    deadline = time.monotonic() + 2
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    m.stop()
    assert calls and not m._thread.is_alive()


def test_monitor_survives_session_factory_error(monkeypatch):
    # DB mati tidak boleh mematikan thread monitor: percobaan berikutnya tetap jalan.
    calls = []
    def factory():
        calls.append(1)
        raise RuntimeError("db down")
    m = node_health.NodeHealthMonitor(interval_s=0.01, session_factory=factory)
    m.start()
    import time
    deadline = time.monotonic() + 2
    while len(calls) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    m.stop()
    assert len(calls) >= 3 and not m._thread.is_alive()


def test_monitor_survives_session_close_error(monkeypatch):
    monkeypatch.setattr(node_health, "check", lambda db: 0)
    calls = []
    class BadSession:
        def close(self):
            calls.append(1)
            raise RuntimeError("close failed")
    m = node_health.NodeHealthMonitor(interval_s=0.01, session_factory=BadSession)
    m.start()
    import time
    deadline = time.monotonic() + 2
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    m.stop()
    assert calls and not m._thread.is_alive()
