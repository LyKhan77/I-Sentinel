"""Admin-only LLM configuration endpoints; no real provider calls."""
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_db
from app.main import app
from app.models.setting import Setting
from app.services import llm_config, secret_store
from tests.conftest import admin_headers, viewer_headers
from tests.test_llm_config import config  # noqa: F401 — shared isolated settings fixture

URL = "/api/v1/ai/settings"
RESULT = {"ok": True, "vision_ok": True, "latency_ms": 12, "model": "mock-model", "error": None}


@pytest.fixture
def app_db(db, config, monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "cookie_secure", True)
    app.dependency_overrides[get_db] = lambda: db
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(app_db, monkeypatch):
    monkeypatch.setattr(llm_config, "test_connection", lambda *args, **kwargs: dict(RESULT))
    with TestClient(app_db) as client:
        yield client


@pytest.mark.parametrize("method,path", [("get", URL), ("put", URL), ("post", URL + "/test")])
def test_endpoints_require_admin(client, method, path):
    call = getattr(client, method)
    body = {} if method == "get" else {"json": {}}
    assert call(path, **body).status_code == 401
    assert call(path, headers=viewer_headers(client), **body).status_code == 403
    assert call(path, headers=admin_headers(client), **body).status_code == 200


def test_get_never_returns_key(client, db):
    headers = admin_headers(client)
    put = client.put(URL, json={"api_key": "sk-secret"}, headers=headers)
    assert put.status_code == 200
    get = client.get(URL, headers=headers)
    for response in (put, get):
        assert response.status_code == 200 and response.json()["key_configured"] is True
        assert "sk-secret" not in response.text and '"api_key"' not in response.text
    assert "api_key" not in db.get(Setting, "llm").value
    assert client.get("/api/v1/ai/status", headers=headers).json().keys() == {"enabled", "presets", "caption_prompts"}


def test_put_partial_null_and_clear(client):
    headers = admin_headers(client)
    before = client.get(URL, headers=headers).json()
    put = client.put(URL, json={"model": "m", "max_tokens": 777, "enabled": False, "api_key": "sk-secret"}, headers=headers)
    assert put.status_code == 200 and settings.llm_model == "m"
    assert put.json()["timeout_ask_s"] == before["timeout_ask_s"]
    reset = client.put(URL, json={"model": None, "max_tokens": None, "enabled": None, "clear_api_key": True}, headers=headers)
    assert reset.status_code == 200
    for field in ("model", "max_tokens", "enabled"):
        assert reset.json()[field] == before[field]
    assert reset.json()["key_configured"] is False
    rejected = client.put(URL, json={"enabled": True}, headers=headers)
    assert rejected.status_code == 422
    assert client.get(URL, headers=headers).json() == reset.json()


def test_invalid_put_with_key_does_not_write_secret_store(client, db, monkeypatch):
    writes = []
    monkeypatch.setattr(secret_store, "put", lambda *args: writes.append(args))
    headers = admin_headers(client)
    for patch in ({"max_tokens": 99}, {"api_url": "ftp://bad.test"}, {"extra_body": {"messages": []}}):
        response = client.put(URL, json={**patch, "api_key": "sk-new"}, headers=headers)
        assert response.status_code == 422 and "sk-new" not in response.text
    assert writes == [] and db.get(Setting, "llm") is None


def test_test_endpoint_passes_form_values(client, monkeypatch):
    seen = []

    def fake(db, values, api_key=None, clear_api_key=False):
        seen.append((values, api_key))
        return dict(RESULT)

    monkeypatch.setattr(llm_config, "test_connection", fake)
    response = client.post(URL + "/test", json={"model": "form-model", "max_tokens": None, "api_key": "sk-form"}, headers=admin_headers(client))
    assert response.status_code == 200 and response.json() == RESULT
    assert seen == [({"model": "form-model", "max_tokens": None}, "sk-form")]


def test_secret_store_failure_is_sanitized(client, db, monkeypatch):
    def fail(*args):
        raise secret_store.SecretStoreError("echo sk-secret")

    monkeypatch.setattr(secret_store, "put", fail)
    response = client.put(URL, json={"model": "m", "api_key": "sk-secret"}, headers=admin_headers(client))
    assert response.status_code == 500 and response.json() == {"detail": "failed to store key"}
    assert "sk-secret" not in response.text and db.get(Setting, "llm") is None


def test_update_log_has_actor_and_field_names_only(client, caplog):
    with caplog.at_level(logging.INFO):
        response = client.put(URL, json={"model": "private-model-value", "api_key": "sk-secret"}, headers=admin_headers(client))
    assert response.status_code == 200
    messages = [record.message for record in caplog.records if "llm settings updated" in record.message]
    assert len(messages) == 1 and "user:1" in messages[0]
    assert "model" in messages[0] and "api_key" in messages[0]
    assert "private-model-value" not in messages[0] and "sk-secret" not in caplog.text


def test_lifespan_applies_db_settings(app_db, db):
    db.add(Setting(key="llm", value={"model": "dari-db"}))
    db.commit()
    with TestClient(app_db):
        assert settings.llm_model == "dari-db"


def test_lifespan_apply_failure_does_not_stop_startup(app_db, monkeypatch, caplog):
    called = []

    def fail(db):
        called.append(True)
        raise RuntimeError("echo sk-secret")

    with monkeypatch.context() as patch:
        patch.setattr(llm_config, "apply", fail)
        with TestClient(app_db) as client:
            assert client.get("/api/v1/health").status_code == 200
    assert called == [True]
    assert "LLM settings apply at startup failed" in caplog.text
    assert "sk-secret" not in caplog.text


def test_get_survives_unreadable_secret_store(client, monkeypatch):
    """Admin harus tetap bisa membuka halaman untuk memperbaiki konfigurasi."""
    def broken(name):
        raise secret_store.SecretStoreError("unreadable")

    monkeypatch.setattr(secret_store, "get", broken)
    r = client.get(URL, headers=admin_headers(client))
    assert r.status_code == 200 and r.json()["key_configured"] is False


def test_get_reports_key_source_without_key(client):
    h = admin_headers(client)
    assert client.get(URL, headers=h).json()["key_source"] == "none"
    r = client.put(URL, json={"api_key": "sk-secret"}, headers=h)
    assert r.json()["key_source"] == "db" and "sk-secret" not in r.text


def test_test_endpoint_forwards_pending_key_clear(client, monkeypatch):
    seen = []

    def fake(db, values, api_key=None, clear_api_key=False):
        seen.append((values, api_key, clear_api_key))
        return dict(RESULT)

    monkeypatch.setattr(llm_config, "test_connection", fake)
    response = client.post(URL + "/test", json={"clear_api_key": True}, headers=admin_headers(client))
    assert response.status_code == 200
    assert seen == [({}, None, True)]
