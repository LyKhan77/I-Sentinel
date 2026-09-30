import pytest

from app.models.setting import Setting
from app.services import health_rules as hr
from tests.conftest import admin_headers, viewer_headers
from tests.test_monitoring import client


def test_defaults_match_catalog():
    rules = hr.get_defaults()
    assert list(rules) == ["camera_no_frames", "camera_low_fps", "gpu_temp", "gpu_vram", "node_ram", "node_cpu",
                           "infer_latency", "mqtt_backlog"]
    assert rules["camera_no_frames"] == {"enabled": True, "threshold": 30, "duration_min": 2,
                                         "severity": "critical", "telegram": True}
    assert rules["gpu_temp"]["threshold"] == 85 and rules["gpu_temp"]["telegram"] is True
    assert rules["camera_low_fps"]["threshold"] == 50 and rules["camera_low_fps"]["telegram"] is False
    assert rules["infer_latency"]["threshold"] == 50 and rules["mqtt_backlog"]["threshold"] == 0


def test_get_merges_stored_and_replaces_corrupt(db):
    db.add(Setting(key=hr.KEY, value={"gpu_temp": {"threshold": 80, "telegram": False},
                                      "node_cpu": {"threshold": "abc", "duration_min": 999, "severity": "loud"},
                                      "unknown_rule": {"enabled": False}}))
    db.commit()
    rules = hr.get(db)
    assert rules["gpu_temp"]["threshold"] == 80 and rules["gpu_temp"]["telegram"] is False
    assert rules["gpu_temp"]["duration_min"] == 5  # default untuk field yang tidak disimpan
    assert rules["node_cpu"] == hr.get_defaults()["node_cpu"]  # nilai rusak → default
    assert "unknown_rule" not in rules


def test_put_partial_and_validation(db):
    out = hr.put(db, {"gpu_temp": {"threshold": 75, "duration_min": 3}, "mqtt_backlog": {"enabled": False}})
    assert out["gpu_temp"]["threshold"] == 75 and out["gpu_temp"]["duration_min"] == 3
    assert out["mqtt_backlog"]["enabled"] is False
    assert hr.get(db)["gpu_temp"]["threshold"] == 75  # tersimpan
    for bad in ({"nope": {"enabled": True}}, {"gpu_temp": {"threshold": 200}}, {"gpu_temp": {"duration_min": 0}},
                {"gpu_temp": {"severity": "info"}}, {"gpu_temp": {"enabled": "yes"}}, {"gpu_temp": {"color": 1}}):
        with pytest.raises(ValueError):
            hr.put(db, bad)
    assert hr.get(db)["gpu_temp"]["threshold"] == 75  # PUT gagal tidak mengubah apa pun


def test_rules_endpoints(client):
    assert client.get("/api/v1/monitoring/rules").status_code == 401
    viewer = viewer_headers(client)
    admin = admin_headers(client)
    client.cookies.clear()  # cookie auth takes precedence over Bearer in this app
    r = client.get("/api/v1/monitoring/rules", headers=viewer)
    assert r.status_code == 200 and r.json()[0]["rule"] == "camera_no_frames"
    assert {"unit", "min", "max", "target", "threshold", "duration_min"} <= set(r.json()[0])
    body = {"gpu_temp": {"threshold": 80, "telegram": False}}
    assert client.put("/api/v1/monitoring/rules", json=body, headers=viewer).status_code == 403
    r = client.put("/api/v1/monitoring/rules", json=body, headers=admin)
    assert r.status_code == 200
    assert next(x for x in r.json() if x["rule"] == "gpu_temp")["threshold"] == 80
    for bad in ({"gpu_temp": {"threshold": 999}}, {"nope": {}}, {"gpu_temp": {"color": "red"}},
                {"gpu_temp": {"enabled": "yes"}}, {"gpu_temp": {"threshold": None}},
                {"gpu_temp": {"threshold": 75}, "node_cpu": {"duration_min": 0}}):
        assert client.put("/api/v1/monitoring/rules", json=bad, headers=admin).status_code == 422
    rules = client.get("/api/v1/monitoring/rules", headers=viewer).json()
    assert next(x for x in rules if x["rule"] == "gpu_temp")["threshold"] == 80


def test_alerts_endpoint_active_and_recent(client, db):
    from datetime import datetime, timedelta, timezone
    from app.models.health_alert import HealthAlert
    from app.models.node import Node
    assert client.get("/api/v1/monitoring/alerts").status_code == 401
    viewer = viewer_headers(client)
    n = db.query(Node).filter_by(name="server").one()
    t = datetime.now(timezone.utc)
    db.add_all([
        HealthAlert(rule="gpu_temp", target=f"gpu:{n.id}:0", node_id=n.id, label="GPU 0 · server", severity="critical",
                    value=90, threshold=85, started_at=t - timedelta(minutes=5)),
        HealthAlert(rule="node_cpu", target=f"node:{n.id}", node_id=n.id, label="server", severity="warning",
                    value=95, threshold=90, started_at=t - timedelta(hours=2), resolved_at=t - timedelta(hours=1)),
    ])
    db.commit()
    body = client.get("/api/v1/monitoring/alerts", headers=viewer).json()
    assert [a["rule"] for a in body["active"]] == ["gpu_temp"] and body["active"][0]["unit"] == "°C"
    assert [a["rule"] for a in body["recent"]] == ["node_cpu"]
    assert datetime.fromisoformat(body["active"][0]["started_at"]).utcoffset() == timedelta(0)
