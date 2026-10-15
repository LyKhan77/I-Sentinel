import httpx
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


def _cam(client):
    h = admin_headers(client)
    r = client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4", "node_id": 1}, headers=h)
    return r.json()["id"], h


class _Resp:
    def __init__(self, status=200, content=b"JPEG"):
        self.status_code, self.content = status, content


def test_snapshot_releases_db_session_before_waiting_for_go2rtc(client, db, monkeypatch):
    cam_id, h = _cam(client)
    closed = {"n": 0}
    real_close = db.close

    def tracking_close():
        closed["n"] += 1
        real_close()

    monkeypatch.setattr(db, "close", tracking_close)
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen["closed_before_upstream"] = closed["n"]
        seen["src"] = params["src"]
        return _Resp()

    monkeypatch.setattr("app.api.live.httpx.get", fake_get)
    r = client.get(f"/api/v1/cameras/{cam_id}/snapshot", headers=h)
    assert r.status_code == 200 and r.content == b"JPEG"
    assert r.headers["content-type"] == "image/jpeg" and r.headers["cache-control"] == "no-store"
    assert seen["src"] == f"cam_{cam_id}"
    # koneksi DB harus sudah dilepas saat request ke go2rtc berjalan (bisa 5 dtk), bukan baru di akhir request
    assert seen["closed_before_upstream"] >= 1


def test_snapshot_unknown_camera_404_without_calling_go2rtc(client, monkeypatch):
    h = admin_headers(client)
    called = []
    monkeypatch.setattr("app.api.live.httpx.get", lambda *a, **k: called.append(1) or _Resp())
    assert client.get("/api/v1/cameras/9999/snapshot", headers=h).status_code == 404
    assert called == []


def test_snapshot_go2rtc_errors_map_to_502(client, monkeypatch):
    cam_id, h = _cam(client)

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("app.api.live.httpx.get", boom)
    r = client.get(f"/api/v1/cameras/{cam_id}/snapshot", headers=h)
    assert r.status_code == 502 and r.json()["detail"].startswith("go2rtc unreachable")
    monkeypatch.setattr("app.api.live.httpx.get", lambda *a, **k: _Resp(status=500))
    r = client.get(f"/api/v1/cameras/{cam_id}/snapshot", headers=h)
    assert r.status_code == 502 and r.json()["detail"] == "go2rtc returned 500"
