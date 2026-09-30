import pytest

from app.models.setting import Setting
from app.services import health_rules as hr


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
