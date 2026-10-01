from datetime import datetime, timedelta, timezone

import pytest

from app.models.camera import Camera
from app.models.event import Event
from app.models.health_alert import HealthAlert
from app.models.monitoring_sample import MonitoringSample
from app.models.node import Node
from app.models.zone import Zone
from app.services import health_alerts as ha
from app.services import health_rules
from app.ws.hub import hub

NOW = datetime(2026, 9, 30, 8, 0, 30, tzinfo=timezone.utc)  # menit berjalan 08:00 → menit selesai terakhir 07:59
MIN = timedelta(minutes=1)


@pytest.fixture
def sent(monkeypatch):
    out = {"ws": [], "tg": []}
    async def fake_broadcast(payload):
        out["ws"].append(payload)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    return out


def _tg(out):
    return lambda db, text: out["tg"].append(text) or True


def _node(db, status="online"):
    n = Node(name="server", status=status)
    db.add(n)
    db.commit()
    return n


def _cam(db, node, cid=3, name="Lorong"):
    db.add(Camera(id=cid, name=name, host="1.2.3.4", node_id=node.id, enabled=True, ai_fps=5.0))
    db.add(Zone(camera_id=cid, name="z", type="behavior", polygon=[[0, 0], [1, 0], [1, 1]],
                behaviors=[{"kind": "intrusion"}], active=True))
    db.commit()


def _samples(db, node, minutes: int, make, end=NOW):
    """minutes sampel menit selesai terakhir (…, 07:58, 07:59); make(i) → data (i=0 paling lama)."""
    last = end.replace(second=0, microsecond=0) - MIN
    for i in range(minutes):
        ts = last - (minutes - 1 - i) * MIN
        db.add(MonitoringSample(node_id=node.id, ts=ts, data=make(i)))
    db.commit()


def gpu(temp):
    return {"gpus": {"0": {"temp_c": {"max": temp}}}}


def _active(db):
    return db.query(HealthAlert).filter(HealthAlert.resolved_at.is_(None)).all()


def _health_events(db):
    return [e for e in db.query(Event).filter_by(type="system").order_by(Event.id) if (e.payload or {}).get("kind") == "health"]


def test_gpu_temp_fires_after_full_window_with_event_and_telegram(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))                    # default 85 °C, 5 menit
    r = ha.evaluate(db, now=NOW, send=_tg(sent))
    assert r["fired"] == [("gpu_temp", f"gpu:{n.id}:0")]
    [a] = _active(db)
    assert a.label == "GPU 0 · server" and a.severity == "critical" and a.value == 90 and a.threshold == 85
    [ev] = _health_events(db)
    assert ev.severity == "critical" and ev.payload["state"] == "firing" and ev.payload["rule"] == "gpu_temp"
    assert sent["ws"] and len(sent["tg"]) == 1 and "GPU panas" in sent["tg"][0] and "90" in sent["tg"][0]


def test_one_normal_minute_or_missing_minute_blocks_firing(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(70 if i == 2 else 90))
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == []
    db.query(MonitoringSample).delete()
    db.commit()
    _samples(db, n, 4, lambda i: gpu(90))                    # jendela 5 menit tapi hanya 4 sampel
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == []


def test_idempotent_same_minute(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    ha.evaluate(db, now=NOW + timedelta(seconds=10), send=_tg(sent))
    assert len(_active(db)) == 1 and len(_health_events(db)) == 1 and len(sent["tg"]) == 1


@pytest.mark.parametrize("transition", ["firing", "resolved", "closed"])
def test_event_write_failure_rolls_back_health_transition(db, sent, monkeypatch, transition):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    at = NOW
    if transition != "firing":
        ha.evaluate(db, now=NOW, send=_tg(sent))
        if transition == "resolved":
            _samples(db, n, 2, lambda i: gpu(60), end=NOW + 2 * MIN)
            at = NOW + 2 * MIN
        else:
            health_rules.put(db, {"gpu_temp": {"enabled": False}})
        sent["tg"].clear()

    original = ha.ingest_event
    def failed_insert(*args, **kwargs):
        raise RuntimeError("simulated event write failure")
    monkeypatch.setattr(ha, "ingest_event", failed_insert)
    with pytest.raises(RuntimeError, match="simulated event write failure"):
        ha.evaluate(db, now=at, send=_tg(sent))
    db.rollback()
    assert len(_active(db)) == (0 if transition == "firing" else 1)
    assert len(_health_events(db)) == (0 if transition == "firing" else 1)
    assert sent["tg"] == []

    monkeypatch.setattr(ha, "ingest_event", original)
    result = ha.evaluate(db, now=at, send=_tg(sent))
    assert len(result[transition if transition != "firing" else "fired"]) == 1
    assert len(_health_events(db)) == (1 if transition == "firing" else 2)
    assert len(sent["tg"]) == (0 if transition == "closed" else 1)


def test_resolves_after_two_normal_minutes(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    _samples(db, n, 1, lambda i: gpu(60), end=NOW + MIN)       # 1 menit normal
    assert ha.evaluate(db, now=NOW + MIN, send=_tg(sent))["resolved"] == []
    _samples(db, n, 1, lambda i: gpu(60), end=NOW + 2 * MIN)   # 2 menit normal
    r = ha.evaluate(db, now=NOW + 2 * MIN, send=_tg(sent))
    assert r["resolved"] == [("gpu_temp", f"gpu:{n.id}:0")] and _active(db) == []
    ev = _health_events(db)[-1]
    assert ev.severity == "info" and ev.payload["state"] == "resolved"
    assert "normal" in sent["tg"][-1]


def test_node_offline_or_without_samples_holds(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    n.status = "offline"
    db.commit()
    later = NOW + 30 * MIN  # tidak ada sampel baru
    r = ha.evaluate(db, now=later, send=_tg(sent))
    assert r == {"fired": [], "resolved": [], "closed": []} and len(_active(db)) == 1
    n.status = "online"
    db.commit()
    r = ha.evaluate(db, now=later, send=_tg(sent))           # online tapi tanpa sampel di jendela (API baru restart)
    assert r == {"fired": [], "resolved": [], "closed": []} and len(_active(db)) == 1


def test_offline_node_cameras_do_not_fire(db, sent):
    n = _node(db, status="offline")
    _cam(db, n)
    _samples(db, n, 5, lambda i: {"cameras": {}})
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == []


def test_camera_no_frames_missing_or_stale(db, sent):
    n = _node(db)
    _cam(db, n, 3, "Lorong")
    _cam(db, n, 4, "Gudang")
    _samples(db, n, 2, lambda i: {"cameras": {"4": {"frame_age_s": {"max": 45.0}, "fps": {"min": 5, "avg": 5},
                                                    "target_fps": 5.0}}})  # cam 3 hilang, cam 4 basi
    fired = sorted(ha.evaluate(db, now=NOW, send=_tg(sent))["fired"])
    assert fired == [("camera_no_frames", "cam:3"), ("camera_no_frames", "cam:4")]
    assert {a.camera_id for a in _active(db)} == {3, 4}
    assert all(e.camera_id in (3, 4) for e in _health_events(db))


def test_camera_low_fps_skips_starting_and_no_target(db, sent):
    n = _node(db)
    _cam(db, n, 3)
    health_rules.put(db, {"camera_low_fps": {"duration_min": 2}})
    _samples(db, n, 2, lambda i: {"cameras": {"3": {"fps": {"min": 1.0, "avg": 2.0}, "target_fps": 5.0,
                                                    "frame_age_s": {"max": 0.2}, "state": "starting"}}})
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == []
    db.query(MonitoringSample).delete()
    db.commit()
    _samples(db, n, 2, lambda i: {"cameras": {"3": {"fps": {"min": 1.0, "avg": 2.0}, "target_fps": 5.0,
                                                    "frame_age_s": {"max": 0.2}, "state": "streaming"}}})
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == [("camera_low_fps", "cam:3")]
    assert sent["tg"] == []  # telegram default OFF
    assert _active(db)[0].value == 20.0  # % dari target


@pytest.mark.parametrize("rule, data, target", [
    ("gpu_vram", {"gpus": {"0": {"vram_pct": {"max": 95.0}}}}, "gpu:{n}:0"),
    ("node_ram", {"ram_pct": {"avg": 95.0, "max": 96.0}}, "node:{n}"),
    ("node_cpu", {"cpu_pct": {"avg": 95.0, "max": 99.0}}, "node:{n}"),
    ("infer_latency", {"ms_avg": {"avg": 80.0}}, "node:{n}"),
    ("mqtt_backlog", {"mqtt_backlog": {"max": 3}}, "node:{n}"),
])
def test_node_and_gpu_rules(db, sent, rule, data, target):
    n = _node(db)
    health_rules.put(db, {rule: {"duration_min": 2}})
    _samples(db, n, 2, lambda i: data)
    assert (rule, target.format(n=n.id)) in ha.evaluate(db, now=NOW, send=_tg(sent))["fired"]


def test_disabled_rule_or_unanalyzed_camera_closes_without_telegram(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    health_rules.put(db, {"gpu_temp": {"enabled": False}})
    tg_before = len(sent["tg"])
    r = ha.evaluate(db, now=NOW + timedelta(seconds=5), send=_tg(sent))
    assert r["closed"] == [("gpu_temp", f"gpu:{n.id}:0")] and _active(db) == []
    assert len(sent["tg"]) == tg_before
    assert _health_events(db)[-1].payload["state"] == "resolved"


def test_disabled_rule_does_not_fire(db, sent):
    n = _node(db)
    health_rules.put(db, {"gpu_temp": {"enabled": False}})
    _samples(db, n, 5, lambda i: gpu(99))
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == []


def test_prune_resolved_older_than_7_days(db):
    n = _node(db)
    db.add_all([
        HealthAlert(rule="gpu_temp", target="gpu:1:0", node_id=n.id, label="x", severity="critical", threshold=85,
                    started_at=NOW - timedelta(days=9), resolved_at=NOW - timedelta(days=8)),
        HealthAlert(rule="gpu_temp", target="gpu:1:0", node_id=n.id, label="x", severity="critical", threshold=85,
                    started_at=NOW - timedelta(days=2), resolved_at=NOW - timedelta(days=1)),
        HealthAlert(rule="node_cpu", target="node:1", node_id=n.id, label="x", severity="warning", threshold=90,
                    started_at=NOW - timedelta(days=10)),  # aktif: tidak dipangkas
    ])
    db.commit()
    assert ha.prune(db, NOW) == 1 and db.query(HealthAlert).count() == 2


def test_sampler_runs_evaluate_and_survives_its_error(db, monkeypatch):
    from app.services import monitoring_history as mh
    calls = []
    monkeypatch.setattr(ha, "evaluate", lambda db, now=None, send=None: calls.append(now) or (_ for _ in ()).throw(RuntimeError("x")))
    n = _node(db)
    mh.record(n.id, {"host": {"cpu_pct": 1.0}}, None, now=NOW - MIN)
    s = mh.HistorySampler(session_factory=lambda: db)
    assert s.run_once(now=NOW) == 1  # sampel tetap tertulis walau evaluate gagal
    assert calls


@pytest.mark.parametrize("mutation", ["unanalyzed", "deleted"])
def test_camera_target_disappears_closes_with_safe_event_fk(db, sent, mutation):
    n = _node(db)
    _cam(db, n)
    _samples(db, n, 2, lambda i: {"cameras": {}})
    ha.evaluate(db, now=NOW, send=_tg(sent))
    db.query(Zone).delete()
    if mutation == "deleted":
        db.query(Event).delete()
        db.query(Camera).delete()
    db.commit()
    count = len(sent["tg"])
    assert ha.evaluate(db, now=NOW + MIN, send=_tg(sent))["closed"] == [("camera_no_frames", "cam:3")]
    assert _active(db) == [] and len(sent["tg"]) == count
    assert _health_events(db)[-1].payload["state"] == "resolved"


def test_gpu_removed_from_latest_sample_closes_without_telegram(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    _samples(db, n, 1, lambda i: {"cpu_pct": {"avg": 10}}, end=NOW + MIN)
    assert ha.evaluate(db, now=NOW + MIN, send=_tg(sent))["closed"] == [("gpu_temp", f"gpu:{n.id}:0")]
    assert len(sent["tg"]) == 1


def test_repeated_one_normal_minute_does_not_resolve(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    _samples(db, n, 1, lambda i: gpu(60), end=NOW + MIN)
    for seconds in (0, 10, 20):
        assert ha.evaluate(db, now=NOW + MIN + timedelta(seconds=seconds), send=_tg(sent))["resolved"] == []
    assert len(_active(db)) == 1 and len(sent["tg"]) == 1


@pytest.mark.parametrize("rule,data,key,threshold,want", [
    ("camera_no_frames", {"cameras": {"3": {"frame_age_s": {"max": 30}}}}, "3", 30, False),
    ("camera_no_frames", {"cameras": {"3": {"fps": {"min": 5}}}}, "3", 30, None),
    ("camera_low_fps", {"cameras": {"3": {"fps": {"min": 2.499}, "target_fps": 5}}}, "3", 50, True),
    ("camera_low_fps", {"cameras": {"3": {"fps": {"min": 2.5}, "target_fps": 5}}}, "3", 50, False),
    ("camera_low_fps", {"cameras": {"3": {"fps": {"min": 1}}}}, "3", 50, None),
    ("gpu_temp", gpu(85), "0", 85, True),
    ("mqtt_backlog", {"mqtt_backlog": {"max": 0}}, "", 0, False),
])
def test_catalog_comparisons_and_missing_values(rule, data, key, threshold, want):
    assert ha._check(rule, data, key, threshold)[0] is want


def test_health_events_do_not_end_offline_history_period(db):
    from app.services import monitoring_history as mh
    n = _node(db)
    for i, payload in enumerate([{"reason": "timeout"}, {"kind": "health", "state": "resolved"}, {"reason": "online"}]):
        db.add(Event(event_id=f"offline-test-{i}", type="system", node_id=n.id, severity="info",
                     ts_event=NOW - (3 - i) * MIN, payload=payload))
    db.commit()
    periods = mh._offline(db, n, NOW - 5 * MIN, NOW)
    assert periods == [{"from": "2026-09-30T07:57:30Z", "to": "2026-09-30T07:59:30Z"}]


@pytest.mark.parametrize("transition", ["firing", "resolved", "closed"])
def test_concurrent_independent_sessions_deliver_one_transition(tmp_path, sent, transition):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Query, sessionmaker
    from app.core.db import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'race.sqlite'}",
                           connect_args={"check_same_thread": False, "timeout": 5})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    at = NOW
    with factory() as seed:
        n = _node(seed)
        _samples(seed, n, 5, lambda i: gpu(90))
        if transition != "firing":
            ha.evaluate(seed, now=NOW, send=_tg(sent))
            if transition == "resolved":
                _samples(seed, n, 2, lambda i: gpu(60), end=NOW + 2 * MIN)
                at = NOW + 2 * MIN
            else:
                health_rules.put(seed, {"gpu_temp": {"enabled": False}})
    sent["tg"].clear()
    sent["ws"].clear()
    barrier = Barrier(2)
    connections = set()
    pg_locks = []

    class RacingQuery(Query):
        def first(self):
            statement = self.statement.compile(dialect=postgresql.dialect())
            if "FOR UPDATE" in str(statement):
                pg_locks.append(str(statement))
            result = super().first()
            if transition != "closed" and statement.params.get("rule_1") == "gpu_temp":
                self.rendezvous()
            return result

        def __iter__(self):
            result = list(super().__iter__())
            if transition == "closed" and self.column_descriptions[0]["entity"] is HealthAlert:
                self.rendezvous()
            return iter(result)

        def rendezvous(self):
            if not self.session.info.get("raced"):
                self.session.info["raced"] = True
                connections.add(id(self.session.connection().connection.driver_connection))
                barrier.wait(timeout=5)

    concurrent = sessionmaker(bind=engine, query_cls=RacingQuery)
    def worker():
        with concurrent() as session:
            return ha.evaluate(session, now=at, send=_tg(sent))

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        key = "fired" if transition == "firing" else transition
        assert sum(len(result[key]) for result in results) == 1
        assert len(connections) == 2
        if transition != "closed":
            assert pg_locks  # Dialect compilation only; no live PostgreSQL server.
        with factory() as check:
            assert len(_active(check)) == (1 if transition == "firing" else 0)
            assert len(_health_events(check)) == (1 if transition == "firing" else 2)
        assert len(sent["ws"]) == 1
        assert len(sent["tg"]) == (0 if transition == "closed" else 1)
    finally:
        engine.dispose()


def test_firing_event_carries_evidence_series(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))

    ha.evaluate(db, now=NOW, send=_tg(sent))

    [event] = _health_events(db)
    evidence = event.payload["evidence"]
    start = NOW.replace(second=0, microsecond=0) - timedelta(minutes=35)
    assert evidence["v"] == 1 and evidence["step_s"] == 60
    assert evidence["from"] == start.isoformat().replace("+00:00", "Z")
    assert evidence["series"]["value"] == [None] * 30 + [90.0] * 5


def test_low_fps_evidence_is_percent_of_target(db, sent):
    n = _node(db)
    _cam(db, n)
    health_rules.put(db, {"camera_low_fps": {"duration_min": 2}})
    _samples(db, n, 2, lambda i: {"cameras": {"3": {"fps": {"min": 1.0, "avg": 2.0},
                                                       "target_fps": 5.0, "state": "streaming"}}})

    ha.evaluate(db, now=NOW, send=_tg(sent))

    [event] = _health_events(db)
    assert event.payload["evidence"]["series"]["value"][-2:] == [20.0, 20.0]


def test_resolved_event_evidence_starts_before_alert_start(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    started_at = _active(db)[0].started_at.replace(tzinfo=timezone.utc)
    resolved_at = NOW + 2 * MIN
    _samples(db, n, 2, lambda i: gpu(60), end=resolved_at)

    ha.evaluate(db, now=resolved_at, send=_tg(sent))

    [event] = _health_events(db)[-1:]
    evidence = event.payload["evidence"]
    start = started_at - 15 * MIN
    values = evidence["series"]["value"]
    assert evidence["from"] == start.isoformat().replace("+00:00", "Z")
    assert start + len(values) * MIN == resolved_at.replace(second=0, microsecond=0)


def test_resolved_evidence_is_capped_at_360_points(db, sent):
    n = _node(db)
    firing_at = NOW - timedelta(hours=10)
    _samples(db, n, 5, lambda i: gpu(90), end=firing_at)
    ha.evaluate(db, now=firing_at, send=_tg(sent))
    _samples(db, n, 2, lambda i: gpu(60), end=NOW)

    ha.evaluate(db, now=NOW, send=_tg(sent))

    [event] = _health_events(db)[-1:]
    evidence = event.payload["evidence"]
    start = NOW.replace(second=0, microsecond=0) - 360 * MIN
    assert len(evidence["series"]["value"]) == 360
    assert evidence["from"] == start.isoformat().replace("+00:00", "Z")


def test_closed_event_has_no_evidence(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    health_rules.put(db, {"gpu_temp": {"enabled": False}})

    ha.evaluate(db, now=NOW + timedelta(seconds=5), send=_tg(sent))

    closed = _health_events(db)[-1].payload
    assert closed["closed"] is True
    assert "evidence" not in closed


def test_evidence_failure_does_not_block_the_event(db, sent, monkeypatch):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    calls = []

    def boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("evidence unavailable")

    monkeypatch.setattr(ha, "_evidence", boom, raising=False)

    result = ha.evaluate(db, now=NOW, send=_tg(sent))

    [event] = _health_events(db)
    assert result["fired"] == [("gpu_temp", f"gpu:{n.id}:0")]
    assert calls and "evidence" not in event.payload
    assert len(_active(db)) == 1
