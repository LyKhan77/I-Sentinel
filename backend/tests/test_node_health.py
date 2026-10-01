from datetime import datetime, timedelta, timezone

import pytest

from app.models.event import Event
from app.models.monitoring_sample import MonitoringSample
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
    assert ev.severity == "warning" and ev.payload == {
        "node": "server", "reason": "timeout", "last_seen": T0.isoformat().replace("+00:00", "Z"),
    }
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
    assert ev.severity == "info" and ev.payload == {"node": "server", "reason": "online", "down_s": 720}
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


def test_offline_event_carries_last_seen_and_cpu_fps_evidence(db, sent):
    seen = T0 - timedelta(minutes=1)
    n = _node(db, seen=seen)
    now = T0 + timedelta(minutes=30)
    for i in range(30):
        db.add(MonitoringSample(
            node_id=n.id,
            ts=T0 + timedelta(minutes=i),
            data={"cpu_pct": {"avg": 40.04}, "infer_fps": {"avg": 30.06}},
        ))
    db.commit()

    assert node_health.mark_offline(db, n, "timeout", now=now, send=_send(sent)) is True

    [event] = _system(db)
    evidence = event.payload["evidence"]
    start = now - timedelta(minutes=30)
    assert event.payload["last_seen"] == seen.isoformat().replace("+00:00", "Z")
    assert evidence["from"] == start.isoformat().replace("+00:00", "Z")
    assert evidence["step_s"] == 60
    assert evidence["series"]["cpu_pct"] == [40.0] * 30
    assert evidence["series"]["infer_fps"] == [30.1] * 30


def test_offline_event_without_samples_has_last_seen_but_no_evidence(db, sent):
    seen = T0 - timedelta(minutes=3)
    n = _node(db, seen=seen)

    assert node_health.mark_offline(db, n, "timeout", now=T0 + timedelta(minutes=30),
                                    send=_send(sent)) is True

    [event] = _system(db)
    assert event.payload["last_seen"] == seen.isoformat().replace("+00:00", "Z")
    assert "evidence" not in event.payload


def test_online_event_carries_down_s(db, sent):
    n = _node(db, status="offline")
    since = T0 - timedelta(minutes=5)

    assert node_health.mark_online(db, n, now=T0, since=since, send=_send(sent)) is True

    [event] = _system(db)
    assert event.payload["down_s"] == 300


def test_online_event_without_since_has_no_down_s(db, sent):
    n = _node(db, status="offline")

    assert node_health.mark_online(db, n, now=T0 + timedelta(minutes=5), send=_send(sent)) is True

    [event] = _system(db)
    assert "down_s" not in event.payload


def test_node_evidence_failure_does_not_block_the_event(db, sent, monkeypatch):
    seen = T0 - timedelta(minutes=1)
    n = _node(db, seen=seen)
    calls = []

    def boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("minute samples unavailable")

    monkeypatch.setattr(node_health, "minute_samples", boom, raising=False)

    assert node_health.mark_offline(db, n, "timeout", now=T0 + timedelta(minutes=30),
                                    send=_send(sent)) is True

    [event] = _system(db)
    assert calls and n.status == "offline"
    assert event.payload["last_seen"] == seen.isoformat().replace("+00:00", "Z")
    assert "evidence" not in event.payload
