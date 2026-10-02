"""Authenticated AI HTTP contracts with SQLite and mocked inference."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.db import get_db
from app.models import Event, EventAi
from app.services import ai_media, ask_ai, llm_client
from tests.conftest import admin_headers, viewer_headers


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "cookie_secure", True)
    ask_ai.reset_rate_limits()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    ask_ai.reset_rate_limits()


@pytest.fixture
def ev(db, monkeypatch):
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: llm_client.LlmResult("Satu orang.", "stop", 1, 1, "test-model"))
    monkeypatch.setattr(ai_media, "snapshot_jpeg", lambda rel: b"jpeg")
    event = Event(type="idle_zone", snapshot_path="test.jpg", ts_event=datetime.now(timezone.utc))
    db.add(event); db.commit()
    return event


@pytest.mark.parametrize("method,path", [("get", "/api/v1/ai/status"), ("get", "/api/v1/events/1/ai"), ("post", "/api/v1/events/1/ask")])
def test_ai_requires_login(client, method, path):
    kwargs = {"json": {"question": "Apa?"}} if method == "post" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_status(client, monkeypatch):
    h = admin_headers(client)
    assert client.get("/api/v1/ai/status", headers=h).json()["enabled"] is False
    monkeypatch.setattr(settings, "llm_enabled", True)
    status = client.get("/api/v1/ai/status", headers=h).json()
    assert status["enabled"] is True and "last_person" in status["presets"]["idle_zone"]
    assert status["caption_prompts"]["idle_zone"] and "attendance" not in status["presets"] and "system" not in status["presets"]


def test_event_ai_caption_and_bounded_history(client, db, ev):
    h = admin_headers(client)
    assert client.get("/api/v1/events/999/ai", headers=h).status_code == 404
    path = f"/api/v1/events/{ev.id}/ai"
    assert client.get(path, headers=h).json() == {"caption": None, "history": []}
    caption = EventAi(event_id=ev.id, kind="caption", status="ok", answer="Caption", channel="auto")
    db.add(caption)
    for i in range(23):
        db.add(EventAi(event_id=ev.id, kind="ask", question=f"q{i}", status="ok", answer="a", channel="web"))
    db.commit()
    body = client.get(path, headers=h).json()
    assert body["caption"]["answer"] == "Caption"
    assert len(body["history"]) == 20 and body["history"][0]["question"] == "q22"
    assert body["history"][-1]["question"] == "q3"


def test_ask_viewer_and_history_limits(client, ev, monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    h = viewer_headers(client)
    path = f"/api/v1/events/{ev.id}/ask"
    r = client.post(path, headers=h, json={"question": "Apa?"})
    assert r.status_code == 200 and set(r.json()) == {"answer", "frames_used", "cached", "latency_ms", "model"}
    for history in ([{"q": "q", "a": "a"}]*7, [{"q": "q", "a": "a"*2001}]):
        assert client.post(path, headers=h, json={"question": "Apa?", "history": history}).status_code == 422


@pytest.mark.parametrize("change,status,code", [("disabled", 503, "disabled"), ("expired", 409, "media_expired"),
                                               ("attendance", 422, "unsupported_type"), ("rate", 429, "rate_limited"),
                                               ("llm", 502, "llm_error")])
def test_ask_error_mapping(client, ev, monkeypatch, change, status, code):
    h = admin_headers(client)
    monkeypatch.setattr(settings, "llm_enabled", change != "disabled")
    if change == "expired": ev.media_expired = True
    elif change == "attendance": ev.type = "attendance"
    elif change == "rate": monkeypatch.setattr(settings, "llm_ask_rate_per_min", 0)
    elif change == "llm":
        def fail(*args, **kwargs): raise llm_client.LlmError("timeout")
        monkeypatch.setattr(llm_client, "chat", fail)
    r = client.post(f"/api/v1/events/{ev.id}/ask", json={"question": "Apa?"}, headers=h)
    assert r.status_code == status and r.json()["detail"] == code


@pytest.mark.parametrize("suffix,method", [("ai", "get"), ("ask", "post")])
def test_ai_event_id_int4_bound(client, suffix, method):
    h = admin_headers(client)
    kwargs = {"json": {"question": "Apa?"}} if method == "post" else {}
    assert getattr(client, method)(f"/api/v1/events/2147483648/{suffix}", headers=h, **kwargs).status_code == 422
