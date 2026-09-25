import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.services import secret_store, telegram
from tests.conftest import admin_headers

TOKEN = "123456:" + "C" * 35
OTHER = "654321:" + "D" * 35


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "media"))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def tg(monkeypatch):
    calls = []
    monkeypatch.setattr(telegram, "get_me", lambda token: calls.append(("getMe", token)) or {"username": "bot"})
    monkeypatch.setattr(telegram, "get_updates", lambda token: [{"chat_id": "-1001", "title": "Satpam", "type": "supergroup"}])
    monkeypatch.setattr(telegram, "deliver", lambda token, chat, text, photo=None, **kw: calls.append(("send", chat, text, kw)) or ("sent", None))
    return calls


def test_settings_empty(client):
    body = client.get("/api/v1/telegram/settings", headers=admin_headers(client)).json()
    assert body == {"has_token": False, "chat_id": None, "chat_title": None, "app_url": None, "last_alert": None}


def test_put_token_chat_and_url(client, tg):
    h = admin_headers(client)
    r = client.put("/api/v1/telegram/settings", json={
        "token": TOKEN, "chat_id": "-1001", "chat_title": "Satpam", "app_url": "http://10.0.0.1:5173/",
    }, headers=h)
    assert r.status_code == 200
    assert r.json() == {"has_token": True, "chat_id": "-1001", "chat_title": "Satpam",
                        "app_url": "http://10.0.0.1:5173", "last_alert": None}
    assert TOKEN not in r.text
    assert secret_store.get(telegram.TOKEN_KEY) == TOKEN


def test_put_token_rejected_keeps_old_and_no_echo(client, tg, monkeypatch):
    h = admin_headers(client)
    client.put("/api/v1/telegram/settings", json={"token": TOKEN}, headers=h)

    def reject(token):
        raise telegram.TelegramError("Unauthorized")

    monkeypatch.setattr(telegram, "get_me", reject)
    r = client.put("/api/v1/telegram/settings", json={"token": OTHER}, headers=h)
    assert r.status_code == 422 and OTHER not in r.text
    bad_format = client.put("/api/v1/telegram/settings", json={"token": "bukan-token"}, headers=h)
    assert bad_format.status_code == 422 and "bukan-token" not in bad_format.text
    assert telegram.get_token() == TOKEN


def test_discover_and_test_message(client, tg):
    h = admin_headers(client)
    assert client.post("/api/v1/telegram/discover", headers=h).status_code == 409
    assert client.post("/api/v1/telegram/test", headers=h).status_code == 409
    client.put("/api/v1/telegram/settings", json={"token": TOKEN}, headers=h)
    assert client.post("/api/v1/telegram/discover", headers=h).json() == {
        "chats": [{"chat_id": "-1001", "title": "Satpam", "type": "supergroup"}]}
    client.put("/api/v1/telegram/settings", json={"chat_id": "-1001", "chat_title": "Satpam"}, headers=h)
    assert client.post("/api/v1/telegram/test", headers=h).json() == {"status": "sent", "error": None}
    send = [c for c in tg if c[0] == "send"][0]
    assert send[1] == "-1001" and send[2] == telegram.TEST_TEXT and send[3] == {"retries": 1}


def test_discover_telegram_error_is_502_without_token(client, tg, monkeypatch):
    h = admin_headers(client)
    client.put("/api/v1/telegram/settings", json={"token": TOKEN}, headers=h)

    def boom(token):
        raise telegram.TelegramError("Conflict: webhook is active")

    monkeypatch.setattr(telegram, "get_updates", boom)
    r = client.post("/api/v1/telegram/discover", headers=h)
    assert r.status_code == 502 and TOKEN not in r.text
    assert r.json()["detail"] == "Conflict: webhook is active"


def test_viewer_cannot_manage(client, db):
    from app.core.security import hash_password
    from app.models.user import User
    db.add(User(username="viewer", password_hash=hash_password("viewerpass1"), role="viewer"))
    db.commit()
    tok = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "viewerpass1"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/v1/telegram/settings", headers=h).status_code == 403
    assert client.put("/api/v1/telegram/settings", json={"app_url": "x"}, headers=h).status_code == 403
    assert client.get("/api/v1/telegram/status", headers=h).status_code == 200


def test_over_length_token_not_echoed(client):
    """Token > max_length → 422 dari pydantic, tapi handler global membuang `input` → token tak bocor."""
    over = "123456:" + "Z" * 200
    r = client.put("/api/v1/telegram/settings", json={"token": over}, headers=admin_headers(client))
    assert r.status_code == 422
    assert over not in r.text and "Z" * 30 not in r.text
    assert "input" not in r.json()["detail"][0]


def test_put_chat_only_preserves_url_and_token(client, tg):
    """PUT sebagian (hanya grup) tidak menimpa token atau app_url yang sudah ada."""
    h = admin_headers(client)
    client.put("/api/v1/telegram/settings", json={"token": TOKEN, "app_url": "http://10.0.0.1:5173"}, headers=h)
    assert client.put("/api/v1/telegram/settings", json={"chat_id": "-1001", "chat_title": "Satpam"}, headers=h).status_code == 200
    body = client.get("/api/v1/telegram/settings", headers=h).json()
    assert body["has_token"] is True and body["app_url"] == "http://10.0.0.1:5173" and body["chat_id"] == "-1001"


def test_put_rejects_non_http_app_url(client, tg):
    """app_url non-http(s) ditolak 422 (dipakai di tautan caption/href) tanpa mengubah setelan yang ada."""
    h = admin_headers(client)
    client.put("/api/v1/telegram/settings", json={"app_url": "http://10.0.0.1:5173"}, headers=h)
    r = client.put("/api/v1/telegram/settings", json={"app_url": "javascript:alert(1)"}, headers=h)
    assert r.status_code == 422 and "javascript" not in r.text
    assert client.get("/api/v1/telegram/settings", headers=h).json()["app_url"] == "http://10.0.0.1:5173"
