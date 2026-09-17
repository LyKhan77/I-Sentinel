import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.camera import Camera
from tests.conftest import admin_headers


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


def test_source_group_profile_are_admin_mutations_and_masked(client):
    h = admin_headers(client)
    profile = client.post(
        "/api/v1/credential-profiles",
        json={"name": "nvr-main", "username": "admin", "secret_ref": "env:CAMERA_CRED_MAIN"},
        headers=h,
    )
    assert profile.status_code == 200
    body = profile.json()
    assert body["secret_ref"] == "env:CAMERA_CRED_MAIN"
    assert "password" not in body
    assert "resolved_url" not in body

    source = client.post(
        "/api/v1/stream-sources",
        json={
            "name": "NVR-MAIN",
            "kind": "nvr",
            "host": "10.0.0.5",
            "port": 8554,
            "default_credential_id": body["id"],
        },
        headers=h,
    )
    assert source.status_code == 200
    assert source.json()["default_credential_id"] == body["id"]

    group = client.post(
        "/api/v1/location-groups",
        json={"name": "Lantai 3", "sort_order": 1},
        headers=h,
    )
    assert group.status_code == 200
    assert group.json()["name"] == "Lantai 3"

    assert client.get("/api/v1/stream-sources", headers=h).status_code == 200
    assert client.get("/api/v1/location-groups", headers=h).status_code == 200
    assert client.get("/api/v1/credential-profiles", headers=h).status_code == 200


def test_management_mutations_require_admin(client):
    assert client.post(
        "/api/v1/stream-sources",
        json={"name": "NVR", "host": "10.0.0.1"},
    ).status_code == 401
    assert client.post("/api/v1/location-groups", json={"name": "Lobby"}).status_code == 401
    assert client.post(
        "/api/v1/credential-profiles",
        json={"name": "cred", "secret_ref": "env:CAMERA_CRED"},
    ).status_code == 401


def test_referenced_source_and_group_cannot_be_deleted(client, db):
    h = admin_headers(client)
    source = client.post(
        "/api/v1/stream-sources",
        json={"name": "NVR", "host": "10.0.0.1"},
        headers=h,
    ).json()
    group = client.post(
        "/api/v1/location-groups",
        json={"name": "Lobby"},
        headers=h,
    ).json()
    camera = Camera(
        name="CAM-01",
        host="legacy",
        source_id=source["id"],
        location_group_id=group["id"],
    )
    db.add(camera)
    db.commit()

    assert client.delete(f"/api/v1/stream-sources/{source['id']}", headers=h).status_code == 409
    assert client.delete(f"/api/v1/location-groups/{group['id']}", headers=h).status_code == 409


def test_profile_cannot_be_disabled_while_source_uses_it(client, db):
    h = admin_headers(client)
    profile = client.post(
        "/api/v1/credential-profiles",
        json={"name": "nvr", "secret_ref": "env:CAMERA_CRED"},
        headers=h,
    ).json()
    client.post(
        "/api/v1/stream-sources",
        json={"name": "NVR", "host": "10.0.0.1", "default_credential_id": profile["id"]},
        headers=h,
    )

    response = client.patch(
        f"/api/v1/credential-profiles/{profile['id']}",
        json={"enabled": False},
        headers=h,
    )
    assert response.status_code == 409


def test_source_host_rejects_embedded_credentials(client):
    h = admin_headers(client)
    assert client.post(
        "/api/v1/stream-sources",
        json={"name": "unsafe", "host": "viewer:secret@10.0.0.1"},
        headers=h,
    ).status_code == 422


def test_management_rejects_blank_names_and_missing_updates(client):
    h = admin_headers(client)
    assert client.post(
        "/api/v1/stream-sources", json={"name": " ", "host": "10.0.0.1"}, headers=h
    ).status_code == 422
    assert client.post(
        "/api/v1/location-groups", json={"name": " "}, headers=h
    ).status_code == 422
    assert client.post(
        "/api/v1/credential-profiles", json={"name": " ", "secret_ref": "env:CAMERA_CRED"}, headers=h
    ).status_code == 422
    assert client.patch("/api/v1/stream-sources/999", json={"name": "x"}, headers=h).status_code == 404
    assert client.patch("/api/v1/credential-profiles/999", json={"name": "x"}, headers=h).status_code == 404


def test_source_and_profile_runtime_updates_resync_attached_camera(client, db):
    from unittest.mock import patch

    h = admin_headers(client)
    profile = client.post(
        "/api/v1/credential-profiles",
        json={"name": "runtime-profile", "username": "before", "secret_ref": "env:RUNTIME_SECRET"},
        headers=h,
    ).json()
    source = client.post(
        "/api/v1/stream-sources",
        json={"name": "runtime-source", "host": "10.0.0.1", "default_credential_id": profile["id"]},
        headers=h,
    ).json()
    camera = Camera(name="runtime-camera", host="10.0.0.1", source_id=source["id"], rtsp_main="/main")
    db.add(camera)
    db.commit()

    with patch("app.api.stream_sources.sync_camera") as sync, patch(
        "app.services.config_push.publish_node_config_for_camera"
    ) as config:
        response = client.patch(
            f"/api/v1/stream-sources/{source['id']}",
            json={"host": "10.0.0.2"},
            headers=h,
        )
    db.refresh(camera)
    assert response.status_code == 200
    assert camera.host == "10.0.0.2"
    assert sync.call_count == config.call_count == 1

    with patch("app.api.credential_profiles.sync_camera") as sync, patch(
        "app.services.config_push.publish_node_config_for_camera"
    ) as config:
        response = client.patch(
            f"/api/v1/credential-profiles/{profile['id']}",
            json={"username": "after"},
            headers=h,
        )
    assert response.status_code == 200
    assert sync.call_count == config.call_count == 1
