"""Alerting: gerbang Telegram per behavior + rate-limit, lalu antre ke dispatcher.

Tidak ada I/O jaringan di sini: thread konsumen MQTT tidak boleh tertahan Telegram. Kirim
(tunggu snapshot, sendPhoto/sendMessage, retry) dikerjakan `alert_dispatcher`.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.event import Event
from app.models.zone import Zone
from app.services import alert_dispatcher
from app.ws.hub import hub

logger = logging.getLogger(__name__)

RATE_LIMIT_MIN = {"critical": 0}
DEFAULT_RATE_LIMIT_MIN = 2


def _track(event: Event):
    return (event.payload or {}).get("track_id")


def _telegram_on(zone: Zone, kind: str) -> bool:
    """Toggle per behavior; item tanpa key → flag zona; zona pra-R5 (behaviors null) → flag zona."""
    if zone.behaviors is None:
        return bool(zone.telegram)
    for b in zone.behaviors:
        if isinstance(b, dict) and b.get("kind") == kind:
            return bool(b.get("telegram", zone.telegram))
    return False


def alert_type(event: Event) -> str:
    """Wajah tidak dikenal punya kunci rate-limit sendiri, terpisah dari absensi tercatat."""
    if event.type == "attendance" and (event.payload or {}).get("match_reason") == "no_match":
        return "attendance_unknown"
    return event.type


def should_alert(db: Session, event: Event, now: datetime | None = None) -> tuple[bool, str]:
    """Gerbang Telegram → (boleh_kirim, alasan).

    Alasan: `""` (kirim) | `no_zone` | `telegram_off` | `attendance_skipped` | `rate_limited`.
    Window rate-limit per (camera, zone, type, track_id): critical tanpa batas,
    severity lain 2 menit; baris `rate_limited` tidak memperpanjang window.
    Attendance `matched` melewati rate-limit (duplikat dicegah cooldown/already_in).
    Pra-syarat: `event.camera_id` tidak None (dijaga `handle`).
    """
    now = now or datetime.now(timezone.utc)
    zone = db.get(Zone, event.zone_id) if event.zone_id else None
    if zone is None:
        return False, "no_zone"
    if not _telegram_on(zone, event.type):
        return False, "telegram_off"
    if event.type == "attendance":
        payload = event.payload or {}
        if payload.get("match_reason") == "matched":
            return True, ""  # duplikat sudah dicegah cooldown/already_in absensi
        if payload.get("match_reason") != "no_match" or payload.get("employee_id") is not None:
            return False, "attendance_skipped"
    window = RATE_LIMIT_MIN.get(event.severity, DEFAULT_RATE_LIMIT_MIN)
    if window <= 0:
        return True, ""
    cutoff = now - timedelta(minutes=window)
    recent = (
        db.query(Alert)
        .filter(
            Alert.camera_id == event.camera_id,
            Alert.zone_id == event.zone_id,
            Alert.type == alert_type(event),
            Alert.status != "rate_limited",  # alert yang disuppres tidak ikut menahan alert berikutnya
            Alert.created_at > cutoff,
        )
        .all()
    )
    track = _track(event)
    if any(a.event is not None and _track(a.event) == track for a in recent):
        return False, "rate_limited"
    return True, ""


def handle(db: Session, event: Event, now: datetime | None = None) -> Alert | None:
    """Gerbang → baris alert (queued / rate_limited) → antre → broadcast. Tidak pernah raise."""
    now = now or datetime.now(timezone.utc)
    if event.camera_id is None:
        return None
    ok, reason = should_alert(db, event, now)
    if not ok and reason != "rate_limited":
        return None
    alert = Alert(
        event_id=event.id,
        camera_id=event.camera_id,
        zone_id=event.zone_id,
        type=alert_type(event),
        severity=event.severity,
        status="queued" if ok else "rate_limited",
        created_at=now,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    if ok and not alert_dispatcher.dispatcher.enqueue(alert.id):
        alert.status, alert.error = "failed", "queue full"
        db.commit()
    try:
        asyncio.run(hub.broadcast({"kind": "alert", "event_id": event.id, "status": alert.status}))
    except Exception:
        logger.exception("alert broadcast failed for event %s", event.id)
    return alert
