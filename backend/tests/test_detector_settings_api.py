import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_db
from app.main import app
from app.models.camera import Camera
from app.models.node import Node
from app.services import config_push
from app.services.config_push import build_node_config
from tests.conftest import admin_headers, viewer_headers


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(config_push, "republish_all", lambda _db: True)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


VALUES = {
    "default_ai_fps": 8.0, "default_confidence": 0.45,
    "motion_enabled": False, "motion_threshold": 30.0,
    "motion_min_area": 0.02, "motion_force_interval_s": 3.0,
    "face_min_width_px": 100.0, "face_min_det_score": 0.7, "face_max_yaw": 0.3,
    "face_blur_min": 90.0, "face_min_frames": 4,
    "face_match_threshold": 0.45, "face_match_margin": 0.2, "face_max_pitch": 0.4,
    "face_best_k": 6, "face_ident_min_width_px": 70.0, "face_ident_window_s": 9.0,
}

NEW_FACE_FIELDS = ("face_match_threshold", "face_match_margin", "face_max_pitch",
                   "face_best_k", "face_ident_min_width_px", "face_ident_window_s")


def test_admin_put_persists_global_settings_and_config_uses_them(client, db):
    node = db.query(Node).filter_by(name="server").one()
    camera = Camera(name="Cam", host="127.0.0.1", node_id=node.id)
    db.add(camera); db.commit()

    response = client.put("/api/v1/detector-settings", json=VALUES, headers=admin_headers(client))

    assert response.status_code == 200
    assert {key: response.json()[key] for key in VALUES} == VALUES
    config = build_node_config(db, node)["cameras"][0]
    assert config["ai_fps"] == 8.0
    assert config["confidence"] == 0.45
    assert config["motion"] == {"enabled": False, "threshold": 30.0, "min_area": 0.02, "force_interval_s": 3.0}
    face = build_node_config(db, node)["face"]
    assert face == {
        "device": "", "min_width_px": 100.0, "min_det_score": 0.7,
        "max_yaw": 0.3, "blur_min": 90.0, "min_frames": 4,
        "ident": {"min_width_px": 70.0, "max_pitch": 0.4, "best_k": 6, "window_s": 9.0},
    }


def test_viewer_cannot_change_detector_settings(client):
    response = client.put("/api/v1/detector-settings", json=VALUES, headers=viewer_headers(client))
    assert response.status_code == 403


def test_get_without_row_returns_env_defaults(client):
    response = client.get("/api/v1/detector-settings", headers=admin_headers(client))

    assert response.status_code == 200
    assert response.json()["default_ai_fps"] == settings.default_ai_fps
    assert response.json()["updated_at"] is not None
    assert (response.json()["face_min_width_px"], response.json()["face_min_frames"]) == (80.0, 3)
    assert tuple(response.json()[key] for key in NEW_FACE_FIELDS) == (0.40, 0.15, 0.30, 5, 60.0, 8.0)


def test_new_face_fields_round_trip(client):
    response = client.put("/api/v1/detector-settings", json=VALUES, headers=admin_headers(client))
    assert response.status_code == 200

    got = client.get("/api/v1/detector-settings", headers=admin_headers(client)).json()
    assert {key: got[key] for key in NEW_FACE_FIELDS} == {key: VALUES[key] for key in NEW_FACE_FIELDS}


@pytest.mark.parametrize("field,value", [
    ("face_match_threshold", 0.05), ("face_match_margin", 0.6), ("face_max_pitch", 0.01),
    ("face_best_k", 11), ("face_ident_min_width_px", 10), ("face_ident_window_s", 16),
])
def test_new_face_fields_out_of_range_rejected(client, field, value):
    client.put("/api/v1/detector-settings", json=VALUES, headers=admin_headers(client))

    response = client.put("/api/v1/detector-settings", json={**VALUES, field: value},
                          headers=admin_headers(client))

    assert response.status_code == 422
    got = client.get("/api/v1/detector-settings", headers=admin_headers(client)).json()
    assert got[field] == VALUES[field]


def test_identity_window_upper_bound_stays_below_unverified_timer(client):
    """Jendela + unggah crop (≤ 6 dtk) + antrean harus muat di bawah UNVERIFIED_AFTER_S (20 dtk)."""
    headers = admin_headers(client)

    over = client.put("/api/v1/detector-settings", json={**VALUES, "face_ident_window_s": 11.0}, headers=headers)
    edge = client.put("/api/v1/detector-settings", json={**VALUES, "face_ident_window_s": 10.0}, headers=headers)

    assert over.status_code == 422
    assert edge.status_code == 200 and edge.json()["face_ident_window_s"] == 10.0


def test_face_settings_validated(client):
    bad = {**VALUES, "face_min_frames": 0}
    response = client.put("/api/v1/detector-settings", json=bad, headers=admin_headers(client))
    assert response.status_code == 422


def test_face_fields_required_on_put(client):
    values = {key: value for key, value in VALUES.items() if not key.startswith("face_")}
    response = client.put("/api/v1/detector-settings", json=values, headers=admin_headers(client))
    assert response.status_code == 422
