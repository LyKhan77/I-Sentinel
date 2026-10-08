import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db
from tests.conftest import *  # noqa

@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "cookie_secure", True)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}

VALID = {"camera_id": 1, "name": "z1", "type": "restricted",
         "polygon": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]]}

def _camera(client, h, name="cam1"):
    return client.post("/api/v1/cameras", json={"name": name, "host": "1.2.3.4"}, headers=h).json()

def test_create_zone_requires_auth(client):
    assert client.post("/api/v1/zones", json=VALID).status_code == 401

def test_create_zone_as_admin(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "z1" and body["type"] == "restricted"
    assert body["camera_id"] == cam["id"] and body["camera_name"] == "cam1"
    assert body["severity"] == "warning" and body["rate_limit_min"] == 5
    assert body["snapshot"] is True and body["telegram"] is False and body["active"] is True
    assert body["direction"] is None and body["schedule"] is None

def test_create_zone_polygon_two_points_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "polygon": [[0.1, 0.1], [0.5, 0.5]]}, headers=h)
    assert r.status_code == 422

def test_create_zone_polygon_coord_out_of_range_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "polygon": [[0.1, 0.1], [1.5, 0.1], [0.5, 0.5]]}, headers=h)
    assert r.status_code == 422

def test_create_zone_absensi_without_direction_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "absensi"}, headers=h)
    assert r.status_code == 422

def test_create_zone_bad_type_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "nope"}, headers=h)
    assert r.status_code == 422

def test_list_zones_filter_camera_id(client):
    h = _admin_headers(client)
    cam1 = _camera(client, h, "cam1")
    cam2 = _camera(client, h, "cam2")
    client.post("/api/v1/zones", json={**VALID, "camera_id": cam1["id"]}, headers=h)
    client.post("/api/v1/zones", json={**VALID, "name": "z2", "camera_id": cam2["id"]}, headers=h)
    all_zones = client.get("/api/v1/zones", headers=h).json()
    assert len(all_zones) == 2
    filtered = client.get(f"/api/v1/zones?camera_id={cam2['id']}", headers=h).json()
    assert [z["name"] for z in filtered] == ["z2"]

def test_patch_zone_severity(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/zones/{zid}", json={"severity": "critical"}, headers=h)
    assert r.status_code == 200 and r.json()["severity"] == "critical"

def test_delete_zone_then_get_404(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    assert client.delete(f"/api/v1/zones/{zid}", headers=h).status_code == 200
    assert client.get(f"/api/v1/zones/{zid}", headers=h).status_code == 404

def test_create_zone_invalid_schedule_day_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    sched = {"days": [0, 1], "start": "08:00", "end": "17:00"}
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "schedule": sched}, headers=h)
    assert r.status_code == 422

def test_patch_to_absensi_without_direction_rejected(client):
    h = _admin_headers(client)
    cam = client.post("/api/v1/cameras", headers=h, json={"name": "z-cam", "host": "1.2.3.4", "node_id": 1}).json()
    z = client.post("/api/v1/zones", headers=h, json={"name": "z", "type": "restricted", "camera_id": cam["id"], "polygon": [[0,0],[1,0],[1,1]]}).json()
    r = client.patch(f"/api/v1/zones/{z['id']}", headers=h, json={"type": "absensi"})
    assert r.status_code == 422


def test_zone_dwell_seconds_default_zero(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    z = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()
    assert z["dwell_seconds"] == 0


def test_patch_zone_dwell_seconds(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/zones/{zid}", json={"dwell_seconds": 3}, headers=h)
    assert r.status_code == 200 and r.json()["dwell_seconds"] == 3


def test_patch_zone_dwell_seconds_negative_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    assert client.patch(f"/api/v1/zones/{zid}", json={"dwell_seconds": -1}, headers=h).status_code == 422


def test_zone_behaviors_roundtrip(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    behaviors = [{"kind": "intrusion", "trigger_seconds": 0},
                 {"kind": "loitering", "trigger_seconds": 30}]
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"],
                                           "type": "behavior", "behaviors": behaviors}, headers=h)
    assert r.status_code == 200, r.text
    z = r.json()
    assert z["behaviors"] == behaviors
    assert z["type"] == "behavior"
    assert client.get(f"/api/v1/zones/{z['id']}", headers=h).json()["behaviors"] == behaviors


def test_zone_attendance_trigger_seconds_roundtrip(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "attendance",
                                           "direction": "entry", "trigger_seconds": 3}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["trigger_seconds"] == 3


def test_zone_behaviors_default_empty(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    z = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()
    assert z["behaviors"] == [] and z["trigger_seconds"] == 0


def test_zone_behavior_invalid_kind_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                           "behaviors": [{"kind": "dance", "trigger_seconds": 0}]}, headers=h)
    assert r.status_code == 422


def test_zone_behavior_negative_trigger_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                           "behaviors": [{"kind": "intrusion", "trigger_seconds": -1}]}, headers=h)
    assert r.status_code == 422


def test_patch_zone_behaviors(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    behaviors = [{"kind": "running", "trigger_seconds": 0, "speed_limit_mps": 1.2}]
    r = client.patch(f"/api/v1/zones/{zid}", json={"behaviors": behaviors}, headers=h)
    assert r.status_code == 200 and r.json()["behaviors"] == behaviors


def test_patch_zone_to_attendance_without_direction_rejected(client):
    """Type baru `attendance` wajib direction, sama seperti `absensi` lama."""
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/zones/{zid}", json={"type": "attendance"}, headers=h)
    assert r.status_code == 422

GATE_BEHAVIORS = [{"kind": "attendance", "trigger_seconds": 0}]


def _gate(client, h, cam_id, direction, active=True, name="g"):
    return client.post("/api/v1/zones", json={
        **VALID, "camera_id": cam_id, "name": name, "type": "attendance",
        "direction": direction, "behaviors": GATE_BEHAVIORS, "active": active,
    }, headers=h)


def test_behavior_media_flags_roundtrip_and_validation(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    behaviors = [{"kind": "intrusion", "trigger_seconds": 0, "clip": False},
                 {"kind": "loitering", "trigger_seconds": 30, "snapshot": False}]
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                           "behaviors": behaviors}, headers=h)
    assert r.status_code == 200 and r.json()["behaviors"] == behaviors
    bad = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                             "behaviors": [{"kind": "intrusion", "clip": "no"}]}, headers=h)
    assert bad.status_code == 422


def test_attendance_direction_conflict_rejected_on_create(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    assert _gate(client, h, cam["id"], "entry").status_code == 200
    assert _gate(client, h, cam["id"], "entry", name="g2").status_code == 200  # arah sama boleh
    conflict = _gate(client, h, cam["id"], "exit", name="g3")
    assert conflict.status_code == 422
    assert "another direction" in conflict.json()["detail"]
    assert _gate(client, h, cam["id"], "exit", active=False, name="g4").status_code == 200  # nonaktif tidak dihitung


def test_attendance_direction_conflict_rejected_on_patch(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    assert _gate(client, h, cam["id"], "entry").status_code == 200
    exit_gate = _gate(client, h, cam["id"], "exit", active=False, name="keluar").json()
    r = client.patch(f"/api/v1/zones/{exit_gate['id']}", json={"active": True}, headers=h)
    assert r.status_code == 422
    assert client.get(f"/api/v1/zones/{exit_gate['id']}", headers=h).json()["active"] is False
    ok = client.patch(f"/api/v1/zones/{exit_gate['id']}", json={"active": True, "direction": "entry"}, headers=h)
    assert ok.status_code == 200


def test_attendance_gates_on_different_cameras_do_not_conflict(client):
    h = _admin_headers(client)
    a, b = _camera(client, h, "cam-a"), _camera(client, h, "cam-b")
    assert _gate(client, h, a["id"], "entry").status_code == 200
    assert _gate(client, h, b["id"], "exit").status_code == 200


def test_patch_flip_type_to_attendance_with_conflicting_direction_rejected(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    assert _gate(client, h, cam["id"], "entry").status_code == 200
    zone = client.post("/api/v1/zones", json={
        **VALID, "camera_id": cam["id"], "name": "b", "type": "behavior",
        "behaviors": [{"kind": "intrusion", "trigger_seconds": 0}],
    }, headers=h).json()
    r = client.patch(f"/api/v1/zones/{zone['id']}", json={
        "type": "attendance", "direction": "exit", "behaviors": GATE_BEHAVIORS,
    }, headers=h)
    assert r.status_code == 422
    assert client.get(f"/api/v1/zones/{zone['id']}", headers=h).json()["type"] == "behavior"


def test_patch_direction_of_active_gate_into_conflict_rejected(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    assert _gate(client, h, cam["id"], "entry").status_code == 200
    other = _gate(client, h, cam["id"], "entry", name="g2").json()
    r = client.patch(f"/api/v1/zones/{other['id']}", json={"direction": "exit"}, headers=h)
    assert r.status_code == 422
    assert client.get(f"/api/v1/zones/{other['id']}", headers=h).json()["direction"] == "entry"


def test_behavior_telegram_flag_roundtrip_and_validation(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    behaviors = [{"kind": "intrusion", "trigger_seconds": 0, "telegram": True}]
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                           "behaviors": behaviors}, headers=h)
    assert r.status_code == 200 and r.json()["behaviors"] == behaviors
    bad = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                             "behaviors": [{"kind": "intrusion", "telegram": "ya"}]}, headers=h)
    assert bad.status_code == 422


def _behavior_zone(client, h, cam_id, behaviors, schedule=None):
    return client.post("/api/v1/zones", json={**VALID, "camera_id": cam_id, "type": "behavior",
                                              "behaviors": behaviors, "schedule": schedule}, headers=h)


def test_idle_and_crowd_kinds_validation(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    ok = _behavior_zone(client, h, cam["id"], [
        {"kind": "idle_zone", "trigger_seconds": 300, "reminder_minutes": 15},
        {"kind": "crowd", "trigger_seconds": 30, "min_count": 5, "reminder_minutes": 0}])
    assert ok.status_code == 200
    for bad in ([{"kind": "crowd", "trigger_seconds": 30}],
                [{"kind": "crowd", "trigger_seconds": 30, "min_count": 0}],
                [{"kind": "idle_zone", "trigger_seconds": 60, "reminder_minutes": -1}],
                [{"kind": "idle_zone", "trigger_seconds": 60, "reminder_minutes": "15"}]):
        assert _behavior_zone(client, h, cam["id"], bad).status_code == 422


def test_zone_schedule_follows_shift(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    shift = client.post("/api/v1/shifts", json={"name": "Pagi", "start_time": "08:00", "end_time": "17:00"},
                        headers=h).json()
    r = _behavior_zone(client, h, cam["id"], [{"kind": "idle_zone", "trigger_seconds": 60}],
                       schedule={"shift_id": shift["id"]})
    assert r.status_code == 200 and r.json()["schedule"] == {"shift_id": shift["id"]}


def test_zone_schedule_unknown_shift_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = _behavior_zone(client, h, cam["id"], [], schedule={"shift_id": 999})
    assert r.status_code == 422 and "shift" in str(r.json()["detail"])
    assert _behavior_zone(client, h, cam["id"], [], schedule={"shift_id": "x"}).status_code == 422


def test_behavior_without_any_media_rejected(client):
    """Event = bukti visual: behavior aktif wajib Snapshot atau Clip (attendance wajib Snapshot)."""
    h = _admin_headers(client)
    cam = _camera(client, h)
    def post(behaviors, type_="behavior", **extra):
        return client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": type_,
                                                  "behaviors": behaviors, **extra}, headers=h)
    r = post([{"kind": "intrusion", "trigger_seconds": 0, "snapshot": False, "clip": False}])
    assert r.status_code == 422 and "snapshot or clip" in str(r.json()["detail"])
    assert post([{"kind": "intrusion", "trigger_seconds": 0, "snapshot": False, "clip": True}]).status_code == 200
    assert post([{"kind": "loitering", "trigger_seconds": 0, "snapshot": True, "clip": False}]).status_code == 200
    r = post([{"kind": "attendance", "trigger_seconds": 0, "snapshot": False}], type_="attendance", direction="entry")
    assert r.status_code == 422
    zid = post([{"kind": "running", "trigger_seconds": 0}]).json()["id"]  # legacy: tanpa flag = ikut zona
    r = client.patch(f"/api/v1/zones/{zid}", json={"behaviors": [
        {"kind": "running", "trigger_seconds": 0, "snapshot": False, "clip": False}]}, headers=h)
    assert r.status_code == 422


def test_create_zone_ai_fields(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    base = {**VALID, "camera_id": cam["id"]}
    default = client.post("/api/v1/zones", json=base, headers=h).json()
    assert default["ai_caption"] is False and default["ai_prompt"] is None
    custom = client.post("/api/v1/zones", json={
        **base, "ai_caption": True, "ai_prompt": "  Fokus helm  ",
    }, headers=h).json()
    assert custom["ai_caption"] is True and custom["ai_prompt"] == "Fokus helm"


def test_patch_ai_prompt_blank_becomes_null(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    for value in ("   ", None):
        r = client.patch(f"/api/v1/zones/{zid}", json={"ai_prompt": value}, headers=h)
        assert r.status_code == 200 and r.json()["ai_prompt"] is None
    assert client.patch(f"/api/v1/zones/{zid}", json={"ai_prompt": "x"*601}, headers=h).status_code == 422
    r = client.patch(f"/api/v1/zones/{zid}", json={"ai_prompt": "x"*600, "ai_caption": True}, headers=h)
    assert r.status_code == 200 and r.json()["ai_caption"] is True and len(r.json()["ai_prompt"]) == 600


def test_patch_ai_fields_viewer_forbidden(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/zones/{zid}", json={"ai_caption": True, "ai_prompt": "Fokus helm"},
                     headers=viewer_headers(client))
    assert r.status_code == 403


def test_patch_ai_caption_null_is_rejected(client):
    """null pada kolom NOT NULL harus 422, bukan IntegrityError/500."""
    h = _admin_headers(client)
    cam = _camera(client, h)
    zone = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()
    r = client.patch(f"/api/v1/zones/{zone['id']}", json={"ai_caption": None}, headers=h)
    assert r.status_code == 422
    assert client.get(f"/api/v1/zones/{zone['id']}", headers=h).json()["ai_caption"] is False


def test_zone_list_survives_oversized_stored_prompt(client, db):
    """Batas 600 berlaku saat menulis; nilai lama/ubahan manual di DB tidak boleh membuat daftar zona 500."""
    from app.models.zone import Zone
    h = _admin_headers(client)
    cam = _camera(client, h)
    zone = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()
    db.get(Zone, zone["id"]).ai_prompt = "x" * 601
    db.commit()
    r = client.get("/api/v1/zones", headers=h)
    assert r.status_code == 200 and len(r.json()[0]["ai_prompt"]) == 601


def test_behavior_telegram_unknown_flag_roundtrip_and_validation(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    bad = client.post("/api/v1/zones", json={
        **VALID, "camera_id": cam["id"], "type": "attendance", "direction": "entry",
        "behaviors": [{"kind": "attendance", "telegram_unknown": "no"}],
    }, headers=h)
    assert bad.status_code == 422
    for flag in (True, False):
        behaviors = [{"kind": "attendance", "trigger_seconds": 0, "telegram_unknown": flag}]
        r = client.post("/api/v1/zones", json={
            **VALID, "camera_id": cam["id"], "type": "attendance", "direction": "entry",
            "behaviors": behaviors,
        }, headers=h)
        assert r.status_code == 200 and r.json()["behaviors"] == behaviors


def test_behavior_record_flag_roundtrip_and_validation(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    bad = client.post("/api/v1/zones", json={
        **VALID, "camera_id": cam["id"], "type": "attendance", "direction": "entry",
        "behaviors": [{"kind": "attendance", "record": "no"}],
    }, headers=h)
    assert bad.status_code == 422
    for flag in (True, False):
        behaviors = [{"kind": "attendance", "trigger_seconds": 0, "record": flag}]
        r = client.post("/api/v1/zones", json={
            **VALID, "camera_id": cam["id"], "type": "attendance", "direction": "entry",
            "behaviors": behaviors,
        }, headers=h)
        assert r.status_code == 200 and r.json()["behaviors"] == behaviors


def test_behavior_face_id_flag_roundtrip_and_validation(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    behaviors = [{"kind": "intrusion", "trigger_seconds": 0, "face_id": True}]
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                           "behaviors": behaviors}, headers=h)
    assert r.status_code == 200 and r.json()["behaviors"] == behaviors
    bad = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                             "behaviors": [{"kind": "intrusion", "face_id": "true"}]},
                      headers=h)
    assert bad.status_code == 422
