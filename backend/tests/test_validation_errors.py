"""422 tidak boleh menggemakan input klien (password kamera / login) — zero-secret."""
import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from tests.conftest import admin_headers


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "camera_secrets_file", str(tmp_path / "s" / "cams.json"))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_credential_profile_422_does_not_echo_password(client):
    h = admin_headers(client)
    both = client.post(
        "/api/v1/credential-profiles",
        json={"name": "a", "secret_ref": "env:CAMERA_CRED", "password": "SANGAT_RAHASIA"},
        headers=h,
    )
    too_long = client.post(
        "/api/v1/credential-profiles", json={"name": "b", "password": "Y" * 300}, headers=h
    )
    created = client.post(
        "/api/v1/credential-profiles", json={"name": "c", "password": "ok"}, headers=h
    ).json()
    patch = client.patch(
        f"/api/v1/credential-profiles/{created['id']}",
        json={"password": "PATCH_RAHASIA", "secret_ref": "env:CAMERA_CRED"},
        headers=h,
    )
    assert (both.status_code, too_long.status_code, patch.status_code) == (422, 422, 422)
    assert "SANGAT_RAHASIA" not in both.text
    assert "Y" * 300 not in too_long.text
    assert "PATCH_RAHASIA" not in patch.text
    # pesan tetap informatif untuk klien
    assert both.json()["detail"][0]["msg"]
    assert too_long.json()["detail"][0]["loc"] == ["body", "password"]


def test_login_422_does_not_echo_password(client):
    r = client.post("/api/v1/auth/login", json={"password": "LOGIN_RAHASIA"})
    assert r.status_code == 422
    assert "LOGIN_RAHASIA" not in r.text
