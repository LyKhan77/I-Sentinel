import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.camera import Camera
from app.models.event import Event
from app.models.monitoring_sample import MonitoringSample
from app.models.node import Node
from app.services import monitoring_history as mh
from tests.conftest import viewer_headers

T0 = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)


def _hb(cpu=10.0, ram=(1000, 4000), gpus=None, det=None, backlog=0, cams=None):
    hw = {"host": {"cpu_pct": cpu, "ram_used_mb": ram[0], "ram_total_mb": ram[1]},
          "gpus": gpus if gpus is not None else
          [{"idx": 0, "util_pct": 40, "vram_used_mb": 20, "vram_total_mb": 100, "temp_c": 60}]}
    mods = {"detector": det or {"ms_avg": 8.0, "ms_max": 12.0, "infer_fps": 40.0},
            "mqtt_backlog": backlog, "cameras": cams if cams is not None else []}
    return hw, mods


def test_record_aggregates_minute_bucket():
    mh.record(1, *_hb(cpu=10, det={"ms_avg": 8, "ms_max": 12, "infer_fps": 40}), now=T0 + timedelta(seconds=5))
    mh.record(1, *_hb(cpu=30, det={"ms_avg": 10, "ms_max": 30, "infer_fps": 20},
                      gpus=[{"idx": 0, "util_pct": 80, "vram_used_mb": 50, "vram_total_mb": 100, "temp_c": 70}]),
              now=T0 + timedelta(seconds=15))
    assert mh.flush(T0 + timedelta(seconds=30)) == []  # bucket berjalan tidak di-flush
    [(node_id, ts, data)] = mh.flush(T0 + timedelta(minutes=1))
    assert node_id == 1 and ts == T0
    assert data["cpu_pct"] == {"avg": 20.0, "max": 30.0}
    assert data["ram_pct"] == {"avg": 25.0, "max": 25.0}
    assert data["gpus"]["0"] == {"util_pct": {"avg": 60.0, "max": 80.0}, "vram_pct": {"max": 50.0},
                                 "temp_c": {"max": 70.0}}
    assert data["ms_avg"] == {"avg": 9.0} and data["ms_max"] == {"max": 30.0}
    assert data["infer_fps"] == {"avg": 30.0} and data["mqtt_backlog"] == {"max": 0}
    assert mh.flush(T0 + timedelta(minutes=5)) == []  # sudah dikeluarkan


def test_camera_workers_merged_and_state_worst():
    cams = [{"id": 3, "worker": "detect", "state": "streaming", "fps": 5.0, "target_fps": 5.0, "last_frame_age_s": 0.2},
            {"id": 3, "worker": "face", "state": "stalled", "fps": 2.0, "target_fps": 5.0, "last_frame_age_s": 12.0}]
    mh.record(1, *_hb(cams=cams), now=T0)
    mh.record(1, *_hb(cams=[{**cams[0], "fps": 4.0}]), now=T0 + timedelta(seconds=10))
    [(_, _, data)] = mh.flush(T0 + timedelta(minutes=1))
    cam = data["cameras"]["3"]
    assert cam["fps"] == {"min": 2.0, "avg": 3.0}  # hb1: min worker 2.0, hb2: 4.0
    assert cam["frame_age_s"] == {"max": 12.0}
    assert cam["target_fps"] == 5.0 and cam["state"] == "stalled"


def test_nodes_and_minutes_separate():
    mh.record(1, *_hb(cpu=10), now=T0)
    mh.record(2, *_hb(cpu=50), now=T0)
    mh.record(1, *_hb(cpu=90), now=T0 + timedelta(minutes=1))
    rows = mh.flush(T0 + timedelta(minutes=2))
    assert [(n, ts, d["cpu_pct"]["avg"]) for n, ts, d in rows] == [
        (1, T0, 10.0), (1, T0 + timedelta(minutes=1), 90.0), (2, T0, 50.0)]


def test_garbage_and_nulls_skipped():
    mh.record(1, {"host": "x", "gpus": [{"idx": "a"}, 5]}, {"detector": 3, "cameras": "junk", "mqtt_backlog": True},
              now=T0)
    mh.record(1, {"host": {"cpu_pct": None, "ram_used_mb": 5, "ram_total_mb": 0}}, None, now=T0)
    mh.record(2, None, None, now=T0)
    assert all(data == {} for *_, data in mh.flush(T0 + timedelta(minutes=1)))


def _node(db, name="server"):
    n = Node(name=name, status="online")
    db.add(n)
    db.commit()
    return n


def _naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _ts_list(db):
    return [_naive(r.ts) if r.ts.tzinfo else r.ts for r in db.query(MonitoringSample).order_by(MonitoringSample.ts)]


def test_sampler_writes_skips_duplicate_and_prunes_hourly(db):
    n = _node(db)
    nid = n.id  # run_once menutup sesi yang dibagikan — tangkap id sebelum instance detach
    db.add(MonitoringSample(node_id=nid, ts=T0 - timedelta(days=8), data={"cpu_pct": {"avg": 1.0}}))
    db.commit()
    s = mh.HistorySampler(session_factory=lambda: db)
    mh.record(nid, *_hb(), now=T0)
    assert s.run_once(now=T0 + timedelta(minutes=1)) == 1
    assert _ts_list(db) == [_naive(T0)]  # sampel 8 hari dipangkas pada run pertama

    mh.record(nid, *_hb(), now=T0)  # bucket menit yang sama datang terlambat → duplikat diabaikan
    db.add(MonitoringSample(node_id=nid, ts=T0 - timedelta(days=9), data={}))
    db.commit()
    assert s.run_once(now=T0 + timedelta(minutes=2)) == 0
    assert len(_ts_list(db)) == 2  # prune belum jalan (< 1 jam sejak prune terakhir)
    s.run_once(now=T0 + timedelta(minutes=62))
    assert _ts_list(db) == [_naive(T0)]


def test_sampler_skips_unknown_node_and_empty(db):
    n = _node(db)
    mh.record(999, *_hb(), now=T0)            # node sudah dihapus
    mh.record(n.id, None, None, now=T0)       # heartbeat tanpa metrik
    s = mh.HistorySampler(session_factory=lambda: db)
    assert s.run_once(now=T0 + timedelta(minutes=1)) == 0
    assert _ts_list(db) == []


def test_sampler_thread_survives_error_and_stops(monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("db down")

    s = mh.HistorySampler(interval_s=0.01, session_factory=boom)
    s.start()
    import time
    deadline = time.monotonic() + 2
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    s.stop()
    assert len(calls) >= 2 and not s._thread.is_alive()


def _sample(db, node, ts, **data):
    db.add(MonitoringSample(node_id=node.id, ts=ts, data=data))
    db.commit()


def _event(db, node, ts, reason):
    db.add(Event(event_id=str(uuid.uuid4()), type="system", node_id=node.id,
                 severity="info" if reason == "online" else "warning", ts_event=ts,
                 payload={"node": node.name, "reason": reason}))
    db.commit()


def _z(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def test_query_downsample_per_range(db):
    n = _node(db)
    for i in range(30):  # 07:30 .. 07:59, satu sampel per menit
        _sample(db, n, T0 - timedelta(minutes=i + 1), cpu_pct={"avg": float(i), "max": float(i) + 1})
    r = mh.query(db, "1h", now=T0)
    assert r["bucket_s"] == 60 and len(r["nodes"][0]["series"]["cpu_pct"]) == 30
    assert r["from"] == _z(T0 - timedelta(hours=1)) and r["to"] == _z(T0)
    r24 = mh.query(db, "24h", now=T0)
    pts = r24["nodes"][0]["series"]["cpu_pct"]
    assert r24["bucket_s"] == 300 and len(pts) == 6
    # bucket 07:30 berisi menit 07:30..07:34 (i = 29..25): avg dari avg, max dari max
    assert pts[0] == {"t": "2026-09-30T07:30:00Z", "avg": 27.0, "max": 30.0}
    assert mh.query(db, "7d", now=T0)["bucket_s"] == 1800


def test_query_gaps_not_filled_and_gpu_camera_series(db):
    n = _node(db)
    db.add(Camera(id=3, name="Lorong", host="1.2.3.4"))
    db.commit()
    cam = {"fps": {"min": 4.0, "avg": 5.0}, "target_fps": 5.0, "frame_age_s": {"max": 0.3}, "state": "streaming"}
    _sample(db, n, T0 - timedelta(minutes=10), gpus={"0": {"temp_c": {"max": 60.0}}},
            cameras={"3": cam, "99": cam})
    _sample(db, n, T0 - timedelta(minutes=5), gpus={"0": {"temp_c": {"max": 70.0}}}, cameras={"3": cam})
    node = mh.query(db, "1h", now=T0)["nodes"][0]
    assert [p["max"] for p in node["series"]["gpus"]["0"]["temp_c"]] == [60.0, 70.0]  # 2 titik, celah tidak diisi
    cams = {c["id"]: c for c in node["cameras"]}
    assert cams[3]["name"] == "Lorong" and cams[3]["target_fps"] == 5.0
    assert cams[3]["fps"][0] == {"t": _z(T0 - timedelta(minutes=10)), "min": 4.0, "avg": 5.0}
    assert cams[99]["name"] == "#99"  # kamera terhapus


def test_query_merge_state_and_min(db):
    n = _node(db)
    ts = T0 - timedelta(minutes=20)  # dua menit dalam satu bucket 5 menit (24h)
    _sample(db, n, ts, cameras={"3": {"fps": {"min": 5.0, "avg": 5.0}, "state": "streaming"}})
    _sample(db, n, ts + timedelta(minutes=1), cameras={"3": {"fps": {"min": 1.0, "avg": 3.0}, "state": "stalled"}})
    cam = mh.query(db, "24h", now=T0)["nodes"][0]["cameras"][0]
    assert cam["fps"] == [{"t": _z(ts), "min": 1.0, "avg": 4.0}]


def test_offline_periods_from_system_events(db):
    n = _node(db)
    _event(db, n, T0 - timedelta(hours=3), "timeout")   # sebelum rentang: node offline di awal rentang 1h
    _event(db, n, T0 - timedelta(minutes=50), "online")
    _event(db, n, T0 - timedelta(minutes=20), "lwt")    # belum pulih
    offline = mh.query(db, "1h", now=T0)["nodes"][0]["offline"]
    assert offline == [{"from": _z(T0 - timedelta(hours=1)), "to": _z(T0 - timedelta(minutes=50))},
                       {"from": _z(T0 - timedelta(minutes=20)), "to": None}]


def test_node_without_samples_listed_empty(db):
    _node(db)
    node = mh.query(db, "6h", now=T0)["nodes"][0]
    assert node["series"]["cpu_pct"] == [] and node["cameras"] == [] and node["offline"] == []


@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_history_endpoint_auth_and_validation(client):
    assert client.get("/api/v1/monitoring/history").status_code == 401
    headers = viewer_headers(client)  # login setelah cek 401: TestClient menyimpan cookie sesi
    r = client.get("/api/v1/monitoring/history?range=1h", headers=headers)
    assert r.status_code == 200 and r.json()["bucket_s"] == 60
    assert "from" in r.json()
    assert client.get("/api/v1/monitoring/history?range=2h", headers=headers).status_code == 422
    assert client.get("/api/v1/monitoring/history", headers=headers).json()["range"] == "6h"


def test_offline_ignores_unrelated_system_events(db):
    """Event system node dengan reason selain lwt/timeout (mis. config_applied) bukan periode offline."""
    n = _node(db)
    _event(db, n, T0 - timedelta(minutes=40), "config_applied")
    _event(db, n, T0 - timedelta(minutes=30), "online")
    assert mh.query(db, "1h", now=T0)["nodes"][0]["offline"] == []


def test_minute_treats_naive_datetime_as_utc():
    """Datetime naive dibaca sebagai UTC (konsisten dengan _utc), bukan zona lokal mesin."""
    assert mh._minute(datetime(2026, 9, 30, 8, 0)) == T0
