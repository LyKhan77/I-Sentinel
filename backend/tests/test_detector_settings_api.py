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
}


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


def test_viewer_cannot_change_detector_settings(client):
    response = client.put("/api/v1/detector-settings", json=VALUES, headers=viewer_headers(client))
    assert response.status_code == 403


def test_get_without_row_returns_env_defaults(client):
    response = client.get("/api/v1/detector-settings", headers=admin_headers(client))

    assert response.status_code == 200
    assert response.json()["default_ai_fps"] == settings.default_ai_fps
    assert response.json()["updated_at"] is not None
