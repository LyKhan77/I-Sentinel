from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.camera import Camera
from app.models.node import Node
from app.models.setting import Setting
from app.models.zone import Zone
from app.services import monitoring

from tests.conftest import viewer_headers

NOW = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _services(monkeypatch):
    """Layanan eksternal dipalsukan: go2rtc sehat dengan stream cam_1/cam_2, MQTT terhubung."""
    monitoring.reset_cache()
    monkeypatch.setattr(monitoring.go2rtc, "probe", lambda: ({"cam_1", "cam_1_main", "cam_2"}, 3.0))
    monitoring.events_consumer.connected.set()
    yield
    monitoring.events_consumer.connected.clear()
    monitoring.reset_cache()


def _node(db, **over):
    n = Node(name="server", status="online", last_seen=NOW - timedelta(seconds=3),
             hw={"gpus": [{"idx": 0, "name": "RTX", "util_pct": 50, "vram_used_mb": 1000,
                           "vram_total_mb": 12000, "temp_c": 60, "power_w": 100.0}],
                 "host": {"cpu_pct": 20.0, "ram_used_mb": 1000, "ram_total_mb": 8000,
                          "disk_used_pct": 50.0, "disk_free_gb": 100.0}},
             modules={"detector": {"model": "m.engine", "device": "auto", "ms_avg": 8.0, "ms_max": 12.0,
                                   "infer_fps": 40.0},
                      "face": {"loaded": True, "queue": 0}, "mqtt_backlog": 0, "cameras": []})
    for k, v in over.items():
        setattr(n, k, v)
    db.add(n)
    db.commit()
    return n


def _cam(db, id, node=None, enabled=True, zone=True):
    c = Camera(id=id, name=f"CAM-{id:02d}", host="1.2.3.4", node_id=node.id if node else None,
               enabled=enabled, ai_fps=5.0)
    db.add(c)
    db.commit()
    if zone:  # zona aktif ber-behavior = kamera dianalisis vision (worker diharapkan jalan)
        _zone(db, id)
    return c


def _zone(db, camera_id, active=True, behaviors=None):
    db.add(Zone(camera_id=camera_id, name=f"z{camera_id}", type="behavior", polygon=[[0, 0], [1, 0], [1, 1]],
                behaviors=[{"kind": "intrusion"}] if behaviors is None else behaviors, active=active))
    db.commit()


def _stat(id, **over):
    s = {"id": id, "worker": "detect", "state": "streaming", "fps": 5.0, "target_fps": 5.0,
         "last_frame_age_s": 0.3, "reconnects_1h": 0, "motion_skip_pct": 50.0}
    s.update(over)
    return s


def _with_cams(node, db, stats):
    node.modules = {**node.modules, "cameras": stats}
    db.commit()


def _cam_row(snap, id):
    return next(c for c in snap["cameras"] if c["id"] == id)


def test_healthy_camera_and_summary(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [_stat(1)])
    snap = monitoring.snapshot(db, now=NOW)
    assert _cam_row(snap, 1)["health"] == "ok" and _cam_row(snap, 1)["issues"] == []
    assert snap["nodes"][0]["health"] == "ok"
    assert snap["summary"]["cameras"]["ok"] == 1


@pytest.mark.parametrize("stat, issue, health", [
    ({"state": "reconnecting"}, "no_frames", "critical"),
    ({"state": "stalled"}, "no_frames", "critical"),
    ({"last_frame_age_s": 31.0}, "no_frames", "critical"),
    ({"fps": 2.0}, "low_fps", "warning"),
    ({"reconnects_1h": 3}, "reconnects", "warning"),
])
def test_camera_rules(db, stat, issue, health):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [_stat(1, **stat)])
    row = _cam_row(monitoring.snapshot(db, now=NOW), 1)
    assert row["health"] == health and issue in row["issues"]


def test_starting_camera_not_low_fps(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [_stat(1, state="starting", fps=0.0, last_frame_age_s=None)])
    assert _cam_row(monitoring.snapshot(db, now=NOW), 1)["health"] == "ok"


def test_face_and_detect_workers_merged_worst(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [_stat(1), _stat(1, worker="face", state="stalled")])
    row = _cam_row(monitoring.snapshot(db, now=NOW), 1)
    assert row["health"] == "critical" and row["ai"]["state"] == "stalled"


def test_camera_missing_from_heartbeat_not_running(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [])
    assert "not_running" in _cam_row(monitoring.snapshot(db, now=NOW), 1)["issues"]


def test_legacy_heartbeat_no_data(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [{"id": 1}])
    row = _cam_row(monitoring.snapshot(db, now=NOW), 1)
    assert row["health"] == "warning" and "no_data" in row["issues"]


def test_heartbeat_without_cameras_key_no_data(db):
    """Vision lama/pra-statistik: node ada, kamera berjalan, tapi belum ada data statistik."""
    n = _node(db, modules={"detector": {"device": "auto"}, "face": {"loaded": True}})
    _cam(db, 1, n)
    row = _cam_row(monitoring.snapshot(db, now=NOW), 1)
    assert row["health"] == "warning" and "no_data" in row["issues"]


def test_garbage_state_type_does_not_crash(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [{"id": 1, "state": {"weird": 1}, "fps": "x", "target_fps": None}])
    row = _cam_row(monitoring.snapshot(db, now=NOW), 1)
    assert row["ai"]["state"] is None and row["ai"]["fps"] is None


def test_db_down_degrades_without_raise(db, monkeypatch):
    """DB benar-benar mati: snapshot tetap kembali (endpoint 200) dengan database critical."""
    from sqlalchemy.exc import OperationalError

    def boom(*a, **k):
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    for name in ("execute", "query", "get"):
        monkeypatch.setattr(db, name, boom)
    snap = monitoring.snapshot(db, now=NOW)
    svc = {s["key"]: s for s in snap["services"]}
    assert svc["database"]["health"] == "critical"
    assert svc["retention"]["health"] == "warning"
    assert snap["nodes"] == [] and snap["cameras"] == []


def test_node_offline_makes_cameras_critical(db):
    n = _node(db, status="offline")
    _cam(db, 1, n)
    _with_cams(n, db, [_stat(1)])
    snap = monitoring.snapshot(db, now=NOW)
    assert snap["nodes"][0]["health"] == "critical" and "offline" in snap["nodes"][0]["issues"]
    assert "node_offline" in _cam_row(snap, 1)["issues"]
    assert snap["summary"]["health"] == "critical"


def test_camera_without_node_and_disabled(db):
    _node(db)
    _cam(db, 2)              # tidak dianalisis: hanya cek stream go2rtc (cam_2 ada)
    _cam(db, 3)              # cam_3 tidak ada di go2rtc
    _cam(db, 4, enabled=False)
    snap = monitoring.snapshot(db, now=NOW)
    assert _cam_row(snap, 2)["ai"] is None and _cam_row(snap, 2)["health"] == "ok"
    assert _cam_row(snap, 3)["issues"] == ["stream_missing"]
    assert _cam_row(snap, 4)["health"] == "disabled"
    assert snap["summary"]["cameras"]["disabled"] == 1


@pytest.mark.parametrize("patch, issue", [
    ({"hw": {"gpus": [{"idx": 0, "temp_c": 90, "vram_used_mb": 1, "vram_total_mb": 10}], "host": {}}}, "gpu_hot"),
    ({"hw": {"gpus": [{"idx": 0, "temp_c": 50, "vram_used_mb": 95, "vram_total_mb": 100}], "host": {}}}, "vram_high"),
    ({"hw": {"gpus": [], "host": {"ram_used_mb": 95, "ram_total_mb": 100}}}, "ram_high"),
    ({"hw": {"gpus": [], "host": {"cpu_pct": 95.0}}}, "cpu_high"),
    ({"last_seen": NOW - timedelta(seconds=25)}, "heartbeat_late"),
])
def test_node_rules(db, patch, issue):
    _node(db, **patch)
    node = monitoring.snapshot(db, now=NOW)["nodes"][0]
    assert node["health"] == "warning" and issue in node["issues"]


def test_node_mqtt_backlog_warning(db):
    n = _node(db)
    n.modules = {**n.modules, "mqtt_backlog": 5}
    db.commit()
    assert "mqtt_backlog" in monitoring.snapshot(db, now=NOW)["nodes"][0]["issues"]


def test_garbage_json_does_not_crash(db):
    _node(db, hw={"gpus": "x", "host": 5}, modules={"cameras": "junk", "detector": 3})
    snap = monitoring.snapshot(db, now=NOW)
    assert snap["nodes"][0]["gpus"] == [] and snap["nodes"][0]["host"]["cpu_pct"] is None


def test_endpoint_tolerates_garbage_node_json(client, db):
    """Tipe ngawur dari node tidak boleh membuat response validation → 500."""
    n = db.query(Node).filter_by(name="server").one()  # node bootstrap dari lifespan
    n.hw = {"gpus": "x"}
    n.modules = {"cameras": [{"id": 1, "state": 5, "fps": "x"}]}
    db.commit()
    _cam(db, 1, n)
    r = client.get("/api/v1/monitoring", headers=viewer_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"][0]["gpus"] == [] and body["cameras"][0]["ai"]["state"] is None


def test_services_ok_and_failures(db, monkeypatch):
    _node(db)
    db.add(Setting(key="retention_last_sweep", value={"at": (NOW - timedelta(hours=2)).isoformat()}))
    db.commit()
    svc = {s["key"]: s for s in monitoring.snapshot(db, now=NOW)["services"]}
    assert svc["database"]["health"] == "ok" and svc["go2rtc"]["health"] == "ok"
    assert svc["mqtt"]["health"] == "ok" and svc["retention"]["health"] == "ok"
    assert svc["telegram"]["health"] == "unknown"  # belum dikonfigurasi di tes

    monitoring.reset_cache()
    monkeypatch.setattr(monitoring.go2rtc, "probe", lambda: (None, 5000.0))
    monitoring.events_consumer.connected.clear()
    db.query(Setting).filter_by(key="retention_last_sweep").one().value = {"at": (NOW - timedelta(hours=30)).isoformat()}
    db.commit()
    svc = {s["key"]: s for s in monitoring.snapshot(db, now=NOW)["services"]}
    assert svc["go2rtc"]["health"] == "critical" and svc["mqtt"]["health"] == "critical"
    assert svc["retention"]["health"] == "warning"


def test_services_cached_10s(db, monkeypatch):
    calls = []
    monkeypatch.setattr(monitoring.go2rtc, "probe", lambda: calls.append(1) or (set(), 1.0))
    monitoring.snapshot(db, now=NOW)
    monitoring.snapshot(db, now=NOW + timedelta(seconds=5))
    assert len(calls) == 1
    monitoring.snapshot(db, now=NOW + timedelta(seconds=11))
    assert len(calls) == 2


def test_host_stats_proc(tmp_path, monkeypatch):
    from app.services import host_stats
    monkeypatch.setattr(host_stats, "_prev_cpu", None)
    (tmp_path / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    (tmp_path / "meminfo").write_text("MemTotal: 16000000 kB\nMemAvailable: 4000000 kB\n")
    assert host_stats.ram_mb(str(tmp_path)) == (11719, 15625)
    assert host_stats.cpu_pct(str(tmp_path)) is None  # butuh dua sampel
    (tmp_path / "stat").write_text("cpu  200 0 200 900 0 0 0 0 0 0\n")
    assert host_stats.cpu_pct(str(tmp_path)) == 66.7


def test_endpoint_viewer_ok_and_requires_login(client):
    assert client.get("/api/v1/monitoring").status_code == 401
    r = client.get("/api/v1/monitoring", headers=viewer_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert {"generated_at", "summary", "server", "nodes", "cameras", "services"} <= set(body)


def test_camera_without_active_analytics_not_expected_to_run(db):
    # data nyata 2026-09-30: kamera tanpa zona aktif tidak punya worker (live view saja) → bukan "not_running"
    n = _node(db)
    _cam(db, 1, n, zone=False)
    _cam(db, 2, n, zone=False)
    _zone(db, 2, active=False)                 # zona nonaktif
    _cam(db, 3, n, zone=False)
    _zone(db, 3, behaviors=[])                 # zona visual saja
    _with_cams(n, db, [])
    snap = monitoring.snapshot(db, now=NOW)
    for cid in (1, 2, 3):
        row = _cam_row(snap, cid)
        assert row["ai"] is None and row["analyzed"] is False and "not_running" not in row["issues"]
    assert _cam_row(snap, 1)["health"] == "ok" and _cam_row(snap, 2)["health"] == "ok"
    assert _cam_row(snap, 3)["issues"] == ["stream_missing"]  # stub go2rtc tanpa cam_3: cek stream tetap jalan


def test_unanalyzed_camera_unaffected_by_node_offline(db):
    n = _node(db, status="offline")
    _cam(db, 1, n, zone=False)
    row = _cam_row(monitoring.snapshot(db, now=NOW), 1)
    assert row["health"] == "ok" and "node_offline" not in row["issues"]


def test_page_thresholds_follow_health_rules(db):
    from app.services import health_rules
    _node(db, hw={"gpus": [{"idx": 0, "temp_c": 80, "vram_used_mb": 1, "vram_total_mb": 10}], "host": {}})
    assert "gpu_hot" not in monitoring.snapshot(db, now=NOW)["nodes"][0]["issues"]
    health_rules.put(db, {"gpu_temp": {"threshold": 75}})
    monitoring.reset_cache()
    assert "gpu_hot" in monitoring.snapshot(db, now=NOW)["nodes"][0]["issues"]


def test_camera_above_half_target_is_healthy(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [_stat(1, fps=3.0)])
    assert _cam_row(monitoring.snapshot(db, now=NOW), 1)["health"] == "ok"
