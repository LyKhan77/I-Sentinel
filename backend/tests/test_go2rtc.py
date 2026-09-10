import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.core.config import settings
from app.services import go2rtc
from tests.conftest import *  # noqa

@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}

def _fake_transport(handler):
    """Patch _client() to use httpx.MockTransport."""
    def factory():
        return httpx.Client(transport=httpx.MockTransport(handler), base_url=settings.go2rtc_url, timeout=5.0)
    return factory

def test_add_stream_2xx_true(monkeypatch):
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        return httpx.Response(200, json={})
    monkeypatch.setattr(go2rtc, "_client", _fake_transport(handler))
    assert go2rtc.add_stream("cam_1", "rtsp://u:p@1.2.3.4/sub") is True
    method, url = calls[0]
    assert method == "PUT"
    assert "name=cam_1" in url and "src=rtsp" in url

def test_add_stream_connection_error_false(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(go2rtc, "_client", _fake_transport(handler))
    assert go2rtc.add_stream("cam_1", "rtsp://x") is False

def test_remove_stream_2xx_true_and_error_false(monkeypatch):
    def handler(request):
        return httpx.Response(200)
    monkeypatch.setattr(go2rtc, "_client", _fake_transport(handler))
    assert go2rtc.remove_stream("cam_1") is True
    def handler_err(request):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(go2rtc, "_client", _fake_transport(handler_err))
    assert go2rtc.remove_stream("cam_1") is False

def test_stream_info(monkeypatch):
    def handler(request):
        assert "src=cam_1" in str(request.url)
        return httpx.Response(200, json={"producers": []})
    monkeypatch.setattr(go2rtc, "_client", _fake_transport(handler))
    assert go2rtc.stream_info("cam_1") == {"producers": []}
    def handler_err(request):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(go2rtc, "_client", _fake_transport(handler_err))
    assert go2rtc.stream_info("cam_1") is None

def test_build_rtsp_url_quoting_and_paths(monkeypatch):
    monkeypatch.setattr(settings, "cam_username", "admin")
    monkeypatch.setattr(settings, "cam_password", "p@ss w")
    cam = type("Cam", (), {"id": 7, "host": "10.0.0.5", "rtsp_sub": "/Streaming/Channels/102", "rtsp_main": "/Streaming/Channels/101"})()
    assert go2rtc.build_rtsp_url(cam, "rtsp_sub") == "rtsp://admin:p%40ss%20w@10.0.0.5/Streaming/Channels/102"
    assert go2rtc.build_rtsp_url(cam, "rtsp_main") == "rtsp://admin:p%40ss%20w@10.0.0.5/Streaming/Channels/101"
    cam2 = type("Cam", (), {"id": 8, "host": "h", "rtsp_sub": None, "rtsp_main": None})()
    assert go2rtc.build_rtsp_url(cam2, "rtsp_sub") is None

def test_sync_camera_names(monkeypatch):
    calls = []
    def handler(request):
        calls.append((request.method, str(request.url)))
        return httpx.Response(200)
    monkeypatch.setattr(go2rtc, "_client", _fake_transport(handler))
    cam = type("Cam", (), {"id": 7, "host": "10.0.0.5", "rtsp_sub": "/sub", "rtsp_main": "/main"})()
    monkeypatch.setattr(settings, "cam_username", "u")
    monkeypatch.setattr(settings, "cam_password", "p")
    go2rtc.sync_camera(cam)
    urls = [u for _, u in calls]
    assert any("name=cam_7" in u and "name=cam_7_main" not in u for u in urls)
    assert any("name=cam_7_main" in u for u in urls)
    assert not any("DELETE" in m for m, _ in calls)
    calls.clear()
    go2rtc.sync_camera(cam, delete=True)
    assert all(m == "DELETE" for m, _ in calls)
    assert any("name=cam_7" in u and "name=cam_7_main" not in u for _, u in calls)
    assert any("name=cam_7_main" in u for _, u in calls)

def test_live_endpoint_shape_and_404(client, monkeypatch):
    h = _admin_headers(client)
    assert client.get("/api/v1/cameras/999/live", headers=h).status_code == 404
    cid = client.post("/api/v1/cameras", json={"name": "camx", "host": "10.0.0.9"}, headers=h).json()["id"]
    r = client.get(f"/api/v1/cameras/{cid}/live", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["camera_id"] == cid
    assert body["streams"]["sub"] == f"cam_{cid}" and body["streams"]["main"] == f"cam_{cid}_main"
    base = settings.go2rtc_url.rstrip("/")
    assert body["webrtc"] == f"{base}/api/ws?src=cam_{cid}"
    assert body["mse"] == f"{base}/api/stream.mse?src=cam_{cid}"
    assert body["hls"] == f"{base}/api/stream.m3u8?src=cam_{cid}"
    assert body["snapshot"] == f"{base}/api/frame.jpeg?src=cam_{cid}"
