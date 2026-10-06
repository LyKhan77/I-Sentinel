"""Admin LLM settings contracts with write-only credentials and explicit null resets."""
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AiTestIn(BaseModel):
    """Unsaved partial form values; omitted fields retain their effective configuration."""

    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool | None = None
    api_url: str | None = None
    model: str | None = None
    max_tokens: int | None = None
    timeout_caption_s: float | None = None
    timeout_ask_s: float | None = None
    ask_rate_per_min: int | None = None
    caption_min_interval_s: float | None = None
    extra_body: dict | None = None
    api_key: str | None = None
    clear_api_key: bool = False


class AiSettingsIn(AiTestIn):
    """A partial saved update; clear_api_key restores the environment credential."""


class RestartOnly(BaseModel):
    """Startup-only limits whose underlying semaphore and queue cannot hot-reload."""

    concurrency: int
    queue_max: int


class AiSettingsOut(BaseModel):
    """Effective settings and provenance, never a provider credential."""

    enabled: bool
    api_url: str
    model: str
    max_tokens: int
    timeout_caption_s: float
    timeout_ask_s: float
    ask_rate_per_min: int
    caption_min_interval_s: float
    extra_body: dict
    key_configured: bool
    key_source: Literal["db", "env", "none"]
    sources: dict[str, Literal["db", "env", "default"]]
    restart_only: RestartOnly


class AiTestOut(BaseModel):
    """A sanitized probe result; text and vision support are reported separately."""

    ok: bool
    vision_ok: bool
    latency_ms: int | None
    model: str | None
    error: str | None
