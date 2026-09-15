"""Alerting: severity gate, per-zone/per-key rate-limit, Telegram send foundation.

Telegram send is best-effort and never blocks ingest: without a token or an
active chat the result is "not_configured" and no network call is made.
"""
import asyncio
import json
import logging
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.alert import Alert
from app.models.event import Event
from app.models.telegram_chat import TelegramChat
from app.models.zone import Zone
from app.ws.hub import hub

logger = logging.getLogger(__name__)

SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}
DEFAULT_RATE_LIMIT_MIN = 5


def _severity(value: str | None) -> int:
    return SEVERITY_ORDER.get(value or "info", 0)


def should_alert(db, event, now: datetime | None = None) -> tuple[bool, str]:
    """Return (True, "") when the event should produce a Telegram send."""
    now = now or datetime.now(timezone.utc)
    if _severity(event.severity) < _severity(settings.alert_min_severity):
        return False, "below_min_severity"

    zone = db.get(Zone, event.zone_id) if event.zone_id else None
    if zone is not None and not zone.telegram:
        return False, "zone_telegram_off"

    window = zone.rate_limit_min if zone is not None else DEFAULT_RATE_LIMIT_MIN
    cutoff = now - timedelta(minutes=window)
    recent = (
        db.query(Alert)
        .filter(
            Alert.camera_id == event.camera_id,
            Alert.zone_id == event.zone_id,
            Alert.type == event.type,
            Alert.created_at > cutoff,
        )
        .first()
    )
    if recent is not None:
        return False, "rate_limited"
    return True, ""


def _format(event) -> str:
    where = f"camera={event.camera_id}" if event.camera_id else "system"
    if event.zone_id:
        where += f" zone={event.zone_id}"
    return f"[{event.severity}] {event.type} {where}"


def _post(url: str, data: dict) -> tuple[str, str | None]:
    """POST JSON via urllib, retrying 3x with 2^attempt backoff."""
    last: str | None = None
    for attempt in range(3):
        try:
            body = json.dumps(data).encode()
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode() or "{}")
            if payload.get("ok"):
                return "sent", None
            last = str(payload.get("description") or "telegram error")[:250]
        except Exception as exc:  # network, timeout, bad JSON …
            last = str(exc)[:250]
        if attempt < 2:
            time.sleep(2 ** attempt)
    return "failed", last


def send_telegram(text: str, photo_path: str | None = None, db=None) -> tuple[str, str | None]:
    """Send text to the first active chat. ("not_configured", None) if unset.

    ponytail: sendMessage only — sendPhoto (snapshot) deferred; add when ops
    actually needs images in the alert.
    """
    token = settings.telegram_bot_token
    chat = db.query(TelegramChat).filter_by(active=True).first() if db is not None else None
    if not token or chat is None:
        return "not_configured", None
    data = {"chat_id": chat.chat_id, "text": text}
    if photo_path:
        data["text"] = f"{text}\n{photo_path}"
    return _post(f"https://api.telegram.org/bot{token}/sendMessage", data)


def handle(db, event, now: datetime | None = None) -> Alert | None:
    """Gate → send → persist an Alert row → broadcast. Never raises."""
    now = now or datetime.now(timezone.utc)
    if event.camera_id is None:
        return None  # alerts are per-camera; Alert.camera_id is NOT NULL
    ok, reason = should_alert(db, event, now)
    if not ok and reason != "rate_limited":
        return None

    if ok:
        chat = db.query(TelegramChat).filter_by(active=True).first()
        status, err = send_telegram(_format(event), event.snapshot_path, db=db)
        chat_id = chat.chat_id if chat else None
    else:
        status, err, chat_id = "rate_limited", None, None

    alert = Alert(
        event_id=event.id,
        camera_id=event.camera_id,
        zone_id=event.zone_id,
        type=event.type,
        severity=event.severity,
        status=status,
        error=err,
        chat_id=chat_id,
        created_at=now,
    )
    db.add(alert)
    db.commit()

    try:
        asyncio.run(hub.broadcast({"kind": "alert", "event_id": event.id, "status": status}))
    except Exception:
        logger.exception("alert broadcast failed for event %s", event.id)
    return alert
