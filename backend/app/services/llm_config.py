"""Admin LLM overrides with environment fallback and write-only credential storage."""
from copy import deepcopy
from io import BytesIO
import json
import math
from time import monotonic
from urllib.parse import urlsplit

import httpx
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.setting import Setting
from app.services import llm_client, secret_store

SETTING_KEY = "llm"
KEY_NAME = "llm_api_key"
FIELDS = ("enabled", "api_url", "model", "max_tokens", "timeout_caption_s", "timeout_ask_s",
          "ask_rate_per_min", "caption_min_interval_s", "extra_body")
_BASE = {field: deepcopy(getattr(settings, "llm_" + field)) for field in (*FIELDS, "api_key")}
_ENV_SET = set(settings.model_fields_set)
_overridden: set[str] = set()
_RANGES = {"max_tokens": (100, 8000), "timeout_caption_s": (5, 600), "timeout_ask_s": (5, 600),
           "ask_rate_per_min": (1, 60), "caption_min_interval_s": (0, 3600)}


class ConfigError(ValueError):
    """A rejected settings patch; messages contain field names, never submitted values."""


def _stored(db: Session) -> dict:
    """Read only supported non-secret overrides from the existing setting table."""
    row = db.get(Setting, SETTING_KEY)
    values = row.value or {} if row is not None else {}
    return {field: deepcopy(values[field]) for field in FIELDS if field in values and values[field] is not None}


def _key() -> str:
    """Resolve a stored key, falling back to the startup environment credential."""
    return secret_store.get(KEY_NAME) or _BASE["api_key"]


def _patched(stored: dict, values: dict) -> dict:
    """Merge a partial patch; null removes an override instead of becoming a DB value."""
    if values.keys() - set(FIELDS):
        raise ConfigError("unsupported LLM setting field")
    merged = deepcopy(stored)
    for field, value in values.items():
        if value is None:
            merged.pop(field, None)
        else:
            merged[field] = deepcopy(value)
    return merged


def _effective(stored: dict) -> dict:
    """Resolve DB > environment > code defaults without mutating runtime settings."""
    return {field: deepcopy(stored.get(field, _BASE[field])) for field in FIELDS}


def _validate(values: dict) -> None:
    """Validate the complete effective configuration before any persistent write."""
    if type(values["enabled"]) is not bool:
        raise ConfigError("enabled must be boolean")
    url = values["api_url"]
    if not isinstance(url, str) or len(url) > 255:
        raise ConfigError("api_url must be a string of at most 255 characters")
    if url:
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in ("http", "https") and bool(parsed.hostname) and not any(c.isspace() for c in url)
            parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ConfigError("api_url must be http(s)")
    model = values["model"]
    if not isinstance(model, str) or len(model) > 64:
        raise ConfigError("model must be a string of at most 64 characters")
    if values["enabled"] and (not url.strip() or not model.strip()):
        raise ConfigError("enabled requires api_url and model")
    for field, (low, high) in _RANGES.items():
        value = values[field]
        integer = field in ("max_tokens", "ask_rate_per_min")
        if (type(value) not in (int, float) or not math.isfinite(value)
                or (integer and type(value) is not int) or not low <= value <= high):
            raise ConfigError(f"{field} must be {'an integer ' if integer else ''}between {low} and {high}")
    extra = values["extra_body"]
    if not isinstance(extra, dict):
        raise ConfigError("extra_body must be a JSON object")
    if extra.keys() & {"messages", "model", "max_tokens", "stream"}:
        raise ConfigError("extra_body contains reserved fields")
    try:
        encoded = json.dumps(extra, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        raise ConfigError("extra_body must be a JSON object") from None
    if len(encoded) > 2000:
        raise ConfigError("extra_body must be at most 2000 characters")


def apply(db: Session) -> None:
    """Apply current overrides and restore removed ones; an untouched empty DB is a no-op."""
    stored = _stored(db)
    key = secret_store.get(KEY_NAME)
    if key:
        stored["api_key"] = key
    # ponytail: mengubah singleton settings (satu proses API); multi-worker perlu muat ulang dari DB per worker.
    for field in stored.keys() | _overridden:
        setattr(settings, "llm_" + field, deepcopy(stored.get(field, _BASE[field])))
    _overridden.clear()
    _overridden.update(stored)


def view(db: Session) -> dict:
    """Return effective non-secret values, their provenance, and restart-only limits."""
    stored = _stored(db)
    return {**_effective(stored),
            "sources": {field: "db" if field in stored else "env" if "llm_" + field in _ENV_SET else "default" for field in FIELDS},
            "key_configured": bool(_key()),
            "restart_only": {"concurrency": settings.llm_concurrency, "queue_max": settings.ai_queue_max}}


def save(db: Session, values: dict, *, api_key: str | None = None, clear_api_key: bool = False) -> None:
    """Validate a partial update, persist overrides/key, commit, then hot-apply settings.

    Clearing the stored key restores the environment fallback, not an empty credential.
    Secret-store failures propagate for the API to translate into a value-free error.
    """
    stored = _patched(_stored(db), values)
    _validate(_effective(stored))
    if api_key is not None and not isinstance(api_key, str):
        raise ConfigError("api_key must be a string")
    if clear_api_key and api_key:
        raise ConfigError("api_key and clear_api_key cannot be combined")
    if clear_api_key:
        secret_store.delete(KEY_NAME)
    elif api_key:
        secret_store.put(KEY_NAME, api_key)
    row = db.get(Setting, SETTING_KEY)
    if row is None:
        db.add(Setting(key=SETTING_KEY, value=stored))
    else:
        row.value = stored
    db.commit()
    apply(db)


def test_connection(db: Session, values: dict, api_key: str | None = None, *, client: httpx.Client | None = None) -> dict:
    """Probe form values with text and a synthetic JPEG, without saving or leasing a slot.

    Each call has a 30-second timeout. Text success with a rejected image reports
    ok=True and vision_ok=False; all errors are sanitized, including form credentials.
    """
    started = monotonic()
    stored_key = ""
    result = {"ok": False, "vision_ok": False, "latency_ms": None, "model": None, "error": None}
    try:
        stored_key = _key()
        effective = _effective(_patched(_stored(db), values))
        _validate(effective)
        connection = llm_client.Connection(effective["api_url"], api_key or stored_key, effective["model"],
                                           effective["extra_body"], effective["max_tokens"])
        parts = [llm_client.text_part("Balas satu kata: ok")]
        text = llm_client.chat([{"role": "user", "content": parts}], timeout=30, client=client, connection=connection)
        result.update(ok=True, model=llm_client.clean_error(text.model, api_key or "", stored_key))
        image = BytesIO()
        Image.new("RGB", (64, 64), color="white").save(image, format="JPEG")
        llm_client.chat([{"role": "user", "content": [*parts, llm_client.image_part(image.getvalue())]}],
                        timeout=30, client=client, connection=connection)
        result["vision_ok"] = True
    except Exception as exc:
        result["error"] = llm_client.clean_error(str(exc), api_key or "", stored_key, _BASE["api_key"])[:255]
    result["latency_ms"] = int((monotonic() - started) * 1000)
    return result
