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
    assert any("src=cam_7" in u and "src=cam_7_main" not in u for _, u in calls)
    assert any("src=cam_7_main" in u for _, u in calls)

def test_live_endpoint_shape_and_404(client, monkeypatch):
    h = _admin_headers(client)
    assert client.get("/api/v1/cameras/999/live", headers=h).status_code == 404
    cid = client.post("/api/v1/cameras", json={"name": "camx", "host": "10.0.0.9"}, headers=h).json()["id"]
    r = client.get(f"/api/v1/cameras/{cid}/live", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["camera_id"] == cid
    assert body["streams"]["sub"] == f"cam_{cid}" and body["streams"]["main"] == f"cam_{cid}_main"
    # playback live view = MAINSTREAM (cam_N_main); substream hanya untuk AI + fallback snapshot
    base = "http://testserver:1984"
    assert body["webrtc"] == f"{base}/api/ws?src=cam_{cid}_main"
    assert body["mse"] == f"{base}/api/stream.mse?src=cam_{cid}_main"
    assert body["hls"] == f"{base}/api/stream.m3u8?src=cam_{cid}_main"
    # snapshot bukan URL go2rtc: port 1984 tidak terjangkau dari LAN, jadi lewat proxy API
    assert body["snapshot"] == f"/api/v1/cameras/{cid}/snapshot"


def test_live_endpoint_rewrites_host_to_request_host(client):
    h = _admin_headers(client)
    cid = client.post("/api/v1/cameras", json={"name": "camz", "host": "10.0.0.9"}, headers=h).json()["id"]
    # request dari LAN browser (192.168.2.50) → URL go2rtc host diganti, port go2rtc tetap
    r = client.get(f"/api/v1/cameras/{cid}/live", headers={**h, "Host": "192.168.2.50:8000"})
    assert r.status_code == 200
    assert r.json()["webrtc"].startswith("http://192.168.2.50:1984/api/ws?src=")
    assert r.json()["mse"].startswith("http://192.168.2.50:1984/")


def test_live_endpoint_prefers_go2rtc_public_host_over_request_host(client, monkeypatch):
    """Di belakang reverse proxy header Host hilang (proxy Vite dev mengirim
    localhost:8000) → klien LAN dapat localhost:1984 dan live view mati.
    GO2RTC_PUBLIC_HOST harus menang atas header Host."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "go2rtc_public_host", "192.168.2.133")
    h = _admin_headers(client)
    cid = client.post("/api/v1/cameras", json={"name": "campub", "host": "10.0.0.9"}, headers=h).json()["id"]
    r = client.get(f"/api/v1/cameras/{cid}/live", headers={**h, "Host": "localhost:8000"})
    assert r.status_code == 200
    assert r.json()["webrtc"].startswith("http://192.168.2.133:1984/api/ws?src=")


def test_live_endpoint_public_host_blank_falls_back_to_request(client, monkeypatch):
    """Kosong = perilaku lama (host dari request) — tidak boleh berubah."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "go2rtc_public_host", "  ")
    h = _admin_headers(client)
    cid = client.post("/api/v1/cameras", json={"name": "camfb", "host": "10.0.0.9"}, headers=h).json()["id"]
    r = client.get(f"/api/v1/cameras/{cid}/live", headers={**h, "Host": "10.1.2.3:8000"})
    assert r.json()["webrtc"].startswith("http://10.1.2.3:1984/api/ws?src=")


def test_snapshot_proxies_go2rtc_and_requires_auth(client, monkeypatch):
    """Port go2rtc (1984) diblokir firewall server, jadi snapshot harus lewat API."""
    import httpx
    from app.api import live as live_mod

    calls = []

    class FakeResp:
        status_code = 200
        content = b"\xff\xd8fake-jpeg"

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return FakeResp()

    monkeypatch.setattr(live_mod.httpx, "get", fake_get)

    # tanpa login → ditolak
    assert client.get("/api/v1/cameras/1/snapshot").status_code == 401

    h = _admin_headers(client)
    cid = client.post("/api/v1/cameras", json={"name": "camsnap", "host": "10.0.0.9"}, headers=h).json()["id"]
    r = client.get(f"/api/v1/cameras/{cid}/snapshot", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == b"\xff\xd8fake-jpeg"
    assert calls and calls[0][1] == {"src": f"cam_{cid}"}

    # kamera tidak ada
    assert client.get("/api/v1/cameras/99999/snapshot", headers=h).status_code == 404


def test_snapshot_returns_502_when_go2rtc_unreachable(client, monkeypatch):
    from app.api import live as live_mod

    def boom(*a, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(live_mod.httpx, "get", boom)
    h = _admin_headers(client)
    cid = client.post("/api/v1/cameras", json={"name": "camdown", "host": "10.0.0.9"}, headers=h).json()["id"]
    r = client.get(f"/api/v1/cameras/{cid}/snapshot", headers=h)
    assert r.status_code == 502
    assert "go2rtc unreachable" in r.json()["detail"]
