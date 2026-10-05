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
class Connection:
    """Explicit provider configuration for a request that must not change settings."""

    url: str
    api_key: str
    model: str
    extra_body: dict
    max_tokens: int


def current_connection() -> Connection:
    """Snapshot the runtime provider configuration used by caption and ask callers."""
    return Connection(settings.llm_api_url, settings.llm_api_key, settings.llm_model,
                      settings.llm_extra_body.copy(), settings.llm_max_tokens)


@dataclass(frozen=True)
class LlmResult:
    """Usable text and non-sensitive accounting from a completion."""

    text: str
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    model: str


_semaphore = BoundedSemaphore(settings.llm_concurrency)


def clean_error(text: str, *secrets: str) -> str:
    """Redact runtime and request-specific credentials before exposing text."""
    for secret in sorted({settings.llm_api_key, *secrets} - {""}, key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    return text


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


def chat(messages: list[dict], *, timeout: float, client: httpx.Client | None = None,
         connection: Connection | None = None) -> LlmResult:
    """Request one completion without leaking response bodies or transport secrets.

    Callers own the slot lease. A supplied client remains owned by its caller.
    Truncated or empty completions are failures, not usable answers.
    """
    conn = connection or current_connection()
    if not conn.url or not conn.model:
        raise LlmError("LLM belum dikonfigurasi")
    body = {"model": conn.model, "messages": messages, "max_tokens": conn.max_tokens,
            "temperature": 0.2, **conn.extra_body}
    owned = client is None
    http = client if client is not None else httpx.Client()
    try:
        response = http.post(conn.url.rstrip("/") + "/chat/completions", json=body,
                             headers={"Authorization": f"Bearer {conn.api_key}"} if conn.api_key else {},
                             timeout=timeout)
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
        return LlmResult(clean_error(text.strip(), conn.api_key), finish, usage.get("prompt_tokens"),
                         usage.get("completion_tokens"), clean_error(str(data.get("model") or conn.model), conn.api_key)[:64])
    except httpx.TimeoutException:
        raise LlmError("LLM timeout") from None
    except httpx.HTTPError:
        raise LlmError("Koneksi LLM gagal") from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise LlmError("Respons LLM tidak valid") from None
    except LlmError as exc:
        raise LlmError(clean_error(str(exc), conn.api_key)) from None
    finally:
        if owned:
            http.close()
