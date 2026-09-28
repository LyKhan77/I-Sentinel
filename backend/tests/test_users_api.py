import jwt
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from tests.conftest import *  # noqa

PW = "rahasia123"


@pytest.fixture
def client(db, monkeypatch):
    from app.api import auth
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "cookie_secure", True)  # httpx tidak replay cookie secure
    auth._FAILURES.clear()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    auth._FAILURES.clear()


def _login(client, username="admin", password="boot123"):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def _h(client, username="admin", password="boot123"):
    return {"Authorization": f"Bearer {_login(client, username, password).json()['token']}"}


def _create(client, h, username="tv-uji", role="viewer", password=PW):
    r = client.post("/api/v1/users", json={"username": username, "password": password, "role": role}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _token(uid: int, minutes_left: float, tv: int | None = 0) -> str:
    from app.core.config import settings
    claims = {"sub": str(uid), "role": "viewer", "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes_left)}
    if tv is not None:
        claims["tv"] = tv
    return jwt.encode(claims, settings.jwt_secret, settings.jwt_algorithm)


def _me(client, token: str, cookie: bool = False):
    headers = {"Cookie": f"isentinel_token={token}"} if cookie else {"Authorization": f"Bearer {token}"}
    return client.get("/api/v1/auth/me", headers=headers)


def test_login_disabled_403_only_with_right_password(client):
    h = _h(client)
    u = _create(client, h)
    assert client.patch(f"/api/v1/users/{u['id']}", json={"is_active": False}, headers=h).status_code == 200
    assert _login(client, "tv-uji", "salah-sekali").status_code == 401  # status tidak bocor
    r = _login(client, "tv-uji", PW)
    assert r.status_code == 403 and r.json()["detail"] == "account disabled"


def test_deactivate_revokes_active_session_and_reactivate_allows_login(client):
    h = _h(client)
    u = _create(client, h)
    tok = _login(client, "tv-uji", PW).json()["token"]
    assert _me(client, tok).status_code == 200
    client.patch(f"/api/v1/users/{u['id']}", json={"is_active": False}, headers=h)
    assert _me(client, tok).status_code == 401
    client.patch(f"/api/v1/users/{u['id']}", json={"is_active": True}, headers=h)
    assert _me(client, tok).status_code == 401  # versi token sudah naik saat dinonaktifkan
    assert _me(client, _login(client, "tv-uji", PW).json()["token"]).status_code == 200


def test_reset_revokes_old_tokens_including_rolling_cookie(client):
    h = _h(client)
    u = _create(client, h)
    fresh = _login(client, "tv-uji", PW).json()["token"]
    near_expiry = _token(u["id"], 30, tv=0)  # lewat separuh umur → biasanya diperpanjang
    assert _me(client, near_expiry, cookie=True).status_code == 200
    assert client.patch(f"/api/v1/users/{u['id']}", json={"password": "baru-rahasia-1"}, headers=h).status_code == 200
    assert _me(client, fresh).status_code == 401
    r = _me(client, near_expiry, cookie=True)
    assert r.status_code == 401 and "set-cookie" not in r.headers
    assert _login(client, "tv-uji", "baru-rahasia-1").status_code == 200


def test_token_without_tv_claim_valid_while_version_zero(client):
    h = _h(client)
    u = _create(client, h)
    assert _me(client, _token(u["id"], 600, tv=None)).status_code == 200
    client.patch(f"/api/v1/users/{u['id']}", json={"password": "baru-rahasia-1"}, headers=h)
    assert _me(client, _token(u["id"], 600, tv=None)).status_code == 401


def test_login_sets_last_login_and_listing_hides_secrets(client):
    h = _h(client)
    _create(client, h)
    _login(client, "tv-uji", PW)
    rows = {u["username"]: u for u in client.get("/api/v1/users", headers=h).json()}
    assert rows["tv-uji"]["last_login_at"] is not None and rows["tv-uji"]["is_active"] is True
    assert "created_at" in rows["tv-uji"]
    assert not {"password_hash", "token_version", "password"} & set(rows["tv-uji"])
