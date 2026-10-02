"""Stateless event questions, auditing, and in-process admission contracts."""
from datetime import datetime, timezone
from contextlib import contextmanager

import pytest

from app.core.config import settings
from app.models import Event, EventAi
from app.services import ai_media, llm_client


@pytest.fixture(autouse=True)
def reset():
    from app.services import ask_ai
    ask_ai.reset_rate_limits()
    yield
    ask_ai.reset_rate_limits()


@pytest.fixture
def setup(db, monkeypatch):
    from app.services import ask_ai
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "sk-secret")
    ev = Event(type="idle_zone", ts_event=datetime.now(timezone.utc), snapshot_path="synthetic.jpg")
    db.add(ev); db.commit()
    calls = []
    def chat(messages, **kwargs):
        calls.append(messages)
        assert kwargs["timeout"] == 120
        return llm_client.LlmResult("Terlihat satu orang.", "stop", 1, 1, "test-model")
    monkeypatch.setattr(llm_client, "chat", chat)
    monkeypatch.setattr(ai_media, "snapshot_jpeg", lambda rel: b"jpeg")
    monkeypatch.setattr(ai_media, "clip_duration", lambda rel: 20)
    monkeypatch.setattr(ai_media, "extract_keyframes", lambda rel, times: [(at, b"jpeg") for at in times])
    return ask_ai, ev, calls


@pytest.mark.parametrize("change,body,status,code", [
    ("disabled", {}, 503, "disabled"), ("attendance", {}, 422, "unsupported_type"), ("system", {}, 422, "unsupported_type"),
    (None, {}, 422, "invalid_request"), (None, {"question": "q", "preset": "report"}, 422, "invalid_request"),
    (None, {"question": "x"*501}, 422, "invalid_request"), (None, {"question": "  "}, 422, "invalid_request"),
    ("loitering", {"preset": "fallen"}, 422, "invalid_preset"), ("expired", {"preset": "report"}, 409, "media_expired"),
    ("no_snapshot", {"preset": "report"}, 409, "snapshot_unavailable"), (None, {"preset": "last_person"}, 409, "clip_unavailable"),
])
def test_validation_errors(db, setup, monkeypatch, change, body, status, code):
    service, ev, calls = setup
    if change == "disabled": monkeypatch.setattr(settings, "llm_enabled", False)
    elif change in ("attendance", "system", "loitering"): ev.type = change
    elif change == "expired": ev.media_expired = True
    elif change == "no_snapshot": ev.snapshot_path = None
    with pytest.raises(service.AskError) as exc:
        service.ask(db, ev, user_id=7, **body)
    assert (exc.value.status, exc.value.code) == (status, code)
    assert not calls and db.query(EventAi).count() == 0


def test_preset_cached(db, setup):
    service, ev, calls = setup
    assert not service.ask(db, ev, user_id=7, preset="what_happened").cached
    assert service.ask(db, ev, user_id=7, preset="what_happened").cached
    assert len(calls) == 1
    service.ask(db, ev, user_id=7, question="Apa?")
    service.ask(db, ev, user_id=7, question="Apa?")
    assert len(calls) == 3


def test_rate_limit(db, setup):
    service, ev, calls = setup
    service.ask(db, ev, user_id=7, preset="what_happened")
    for i in range(5):
        service.ask(db, ev, user_id=7, question=f"Pertanyaan {i}")
        assert service.ask(db, ev, user_id=7, preset="what_happened").cached
    with pytest.raises(service.AskError) as exc:
        service.ask(db, ev, user_id=7, question="Ketujuh")
    assert (exc.value.status, exc.value.code) == (429, "rate_limited")
    service.ask(db, ev, user_id=8, question="User lain")
    assert len(calls) == 7


def test_missing_clip_falls_back_to_snapshot(db, setup, monkeypatch):
    service, ev, _ = setup
    ev.clip_path = "missing.mp4"
    def fail(*args, **kwargs): raise ai_media.AiMediaError("missing")
    monkeypatch.setattr(ai_media, "extract_keyframes", fail)
    result = service.ask(db, ev, user_id=7, preset="what_happened")
    assert result.frames_used == 0 and result.answer
    with pytest.raises(service.AskError) as exc:
        service.ask(db, ev, user_id=7, preset="last_person")
    assert (exc.value.status, exc.value.code) == (409, "clip_unavailable")


def test_keyframes_in_prompt(db, setup):
    service, ev, calls = setup
    ev.clip_path = "clip.mp4"
    result = service.ask(db, ev, user_id=7, question="Ke mana?", history=[("q1", "a1"), ("q2", "a2")])
    assert result.frames_used == 6
    content = calls[0][1]["content"]
    assert sum(part.get("text", "").startswith("Frame pada detik") for part in content) == 6
    assert all(text in content[0]["text"] for text in ("q1", "a1", "q2", "a2", "Ke mana?"))
    assert sum(part["type"] == "image_url" for part in content) == 7


def test_llm_error_persists_failed_row_and_502(db, setup, monkeypatch):
    service, ev, _ = setup
    def fail(*args, **kwargs): raise llm_client.LlmError("sk-secret timeout")
    monkeypatch.setattr(llm_client, "chat", fail)
    with pytest.raises(service.AskError) as exc:
        service.ask(db, ev, user_id=7, question="Apa?")
    assert (exc.value.status, exc.value.code) == (502, "llm_error")
    row = db.query(EventAi).one()
    assert row.status == "failed" and "sk-secret" not in row.error and "sk-secret" not in str(exc.value)


def test_busy_is_503(db, setup, monkeypatch):
    service, ev, _ = setup
    @contextmanager
    def busy(*args, **kwargs):
        raise llm_client.LlmBusy("busy")
        yield
    monkeypatch.setattr(llm_client, "slot", busy)
    with pytest.raises(service.AskError) as exc:
        service.ask(db, ev, user_id=7, question="Apa?")
    assert (exc.value.status, exc.value.code) == (503, "busy")


def test_audit_row(db, setup):
    service, ev, _ = setup
    service.ask(db, ev, user_id=7, question="Apa?")
    row = db.query(EventAi).one()
    assert row.kind == "ask" and row.channel == "web" and row.actor == "user:7"
    assert row.question == "Apa?" and row.answer == "Terlihat satu orang." and row.latency_ms >= 0
