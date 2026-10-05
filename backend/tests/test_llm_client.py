"""LLM protocol and secret safety, using only in-memory HTTP transport."""
import json
import threading

import httpx
import pytest


@pytest.fixture
def llm(monkeypatch):
    from app.services import llm_client
    monkeypatch.setattr(llm_client.settings, "llm_api_url", "https://llm.test/v1/")
    monkeypatch.setattr(llm_client.settings, "llm_api_key", "sk-secret")
    monkeypatch.setattr(llm_client.settings, "llm_model", "test-model")
    return llm_client


def response(text="Terlihat seseorang.", finish="stop"):
    return httpx.Response(200, json={"model": "test-model", "choices": [{"message": {"content": text}, "finish_reason": finish}],
                                    "usage": {"prompt_tokens": 12, "completion_tokens": 4}})


def test_request_shape(llm):
    def handler(req):
        assert str(req.url) == "https://llm.test/v1/chat/completions"
        assert req.method == "POST" and req.headers["Authorization"] == "Bearer sk-secret"
        body = json.loads(req.content)
        assert body["model"] == "test-model" and body["max_tokens"] == 1000
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        return response()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = llm.chat([{"role": "user", "content": [llm.text_part("Deskripsi"), llm.image_part(b"jpeg")]}], timeout=60, client=client)
    assert result.text == "Terlihat seseorang." and result.prompt_tokens == 12 and result.completion_tokens == 4


@pytest.mark.parametrize("text,finish,match", [("potongan", "length", "terpotong"), ("", "stop", "kosong")])
def test_finish_length_is_error(llm, text, finish, match):
    with httpx.Client(transport=httpx.MockTransport(lambda req: response(text, finish))) as client:
        with pytest.raises(llm.LlmError, match=match):
            llm.chat([], timeout=1, client=client)


@pytest.mark.parametrize("timeout", [False, True])
def test_http_500_and_timeout_are_llm_error(llm, timeout):
    def handler(req):
        if timeout:
            raise httpx.ReadTimeout("sk-secret", request=req)
        return httpx.Response(500, text="sk-secret")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(llm.LlmError) as exc:
            llm.chat([], timeout=1, client=client)
    assert "sk-secret" not in str(exc.value)


def test_error_never_contains_key(llm):
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(400, text="sk-secret"))) as client:
        with pytest.raises(llm.LlmError) as exc:
            llm.chat([], timeout=1, client=client)
    assert "sk-secret" not in str(exc.value)


def test_unconfigured_raises(llm, monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_api_url", "")
    with pytest.raises(llm.LlmError):
        llm.chat([], timeout=1)


def test_slot_busy(llm, monkeypatch):
    monkeypatch.setattr(llm, "_semaphore", threading.BoundedSemaphore(1))
    with llm.slot():
        with pytest.raises(llm.LlmBusy):
            with llm.slot(timeout=0.05):
                pytest.fail("A second request must not enter")
    with llm.slot(timeout=0):
        pass


def test_no_authorization_header_without_key(llm, monkeypatch):
    """Endpoint tanpa kunci: 'Bearer ' (spasi di ujung) ditolak httpx/h11 sebagai header ilegal."""
    monkeypatch.setattr(llm.settings, "llm_api_key", "")
    seen = {}
    def handler(req):
        seen["headers"] = dict(req.headers)
        return response()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        llm.chat([], timeout=1, client=client)
    assert "authorization" not in seen["headers"]
