"""Synchronous OpenAI-compatible multimodal client with shared concurrency limits."""
from base64 import b64encode
from contextlib import contextmanager
from dataclasses import dataclass
from threading import BoundedSemaphore

import httpx

from app.core.config import settings


class LlmError(Exception):
    """A sanitized protocol, configuration, or transport failure."""


class LlmBusy(LlmError):
    """The shared caption/question capacity is exhausted."""


@dataclass(frozen=True)
class LlmResult:
    """Usable text and non-sensitive accounting from a completion."""

    text: str
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    model: str


_semaphore = BoundedSemaphore(settings.llm_concurrency)


def clean_error(text: str) -> str:
    """Redact the configured credential before any error is exposed or persisted."""
    return text.replace(settings.llm_api_key, "[redacted]") if settings.llm_api_key else text


def text_part(text: str) -> dict:
    """Encode a textual multimodal content part."""
    return {"type": "text", "text": text}


def image_part(jpeg: bytes) -> dict:
    """Encode an in-memory JPEG; never log the image or data URI."""
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64encode(jpeg).decode("ascii")}}


@contextmanager
def slot(timeout: float = 5.0):
    """Lease one shared LLM slot, always releasing it after success or failure."""
    if not _semaphore.acquire(timeout=timeout):
        raise LlmBusy("AI sibuk")
    try:
        yield
    finally:
        _semaphore.release()


def chat(messages: list[dict], *, timeout: float, client: httpx.Client | None = None) -> LlmResult:
    """Request one completion without leaking response bodies or transport secrets.

    Callers own the slot lease. A supplied client remains owned by its caller.
    Truncated or empty completions are failures, not usable answers.
    """
    if not settings.llm_api_url or not settings.llm_model:
        raise LlmError("LLM belum dikonfigurasi")
    body = {"model": settings.llm_model, "messages": messages, "max_tokens": settings.llm_max_tokens,
            "temperature": 0.2, **settings.llm_extra_body}
    owned = client is None
    http = client if client is not None else httpx.Client()
    try:
        response = http.post(settings.llm_api_url.rstrip("/") + "/chat/completions", json=body,
                             headers={"Authorization": f"Bearer {settings.llm_api_key}"}, timeout=timeout)
        if response.is_error:
            raise LlmError(f"LLM HTTP {response.status_code}")
        data = response.json()
        choice = data["choices"][0]
        finish = choice.get("finish_reason")
        if finish == "length":
            raise LlmError("Jawaban LLM terpotong")
        text = choice["message"].get("content")
        if not isinstance(text, str) or not text.strip():
            raise LlmError("Jawaban LLM kosong")
        usage = data.get("usage") or {}
        return LlmResult(clean_error(text.strip()), finish, usage.get("prompt_tokens"),
                         usage.get("completion_tokens"), clean_error(str(data.get("model") or settings.llm_model))[:64])
    except httpx.TimeoutException:
        raise LlmError("LLM timeout") from None
    except httpx.HTTPError:
        raise LlmError("Koneksi LLM gagal") from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise LlmError("Respons LLM tidak valid") from None
    except LlmError as exc:
        raise LlmError(clean_error(str(exc))) from None
    finally:
        if owned:
            http.close()
