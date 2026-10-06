"""Move AI captions into Telegram alerts, once, whatever the completion order."""
from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from app.models import Alert, Camera, EventAi, Zone
from app.services import telegram

logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()  # ponytail: satu proses API; antrean terpisah bila Telegram lambat terbukti menunda caption


def ai_text(db: Session, event_id: int) -> str | None:
    """Latest successful auto-caption for the event, or None."""
    row = (db.query(EventAi)
             .filter_by(event_id=event_id, kind="caption", status="ok")
             .order_by(EventAi.id.desc())
             .first())
    return row.answer if row is not None else None


def build_caption(db: Session, alert: Alert, ai: str | None) -> str:
    """Caption builder now shared by the dispatcher and the sync path."""
    event = alert.event
    if event is None:
        return ""
    camera = db.get(Camera, alert.camera_id) if alert.camera_id else None
    zone = db.get(Zone, alert.zone_id) if alert.zone_id else None
    return telegram.format_caption(
        event, camera.name if camera else f"cam {alert.camera_id}",
        zone.name if zone else None, telegram.app_url(db), ai_text=ai)


def sync_ai_caption(db: Session, event_id: int) -> bool:
    """Edit the delivered photo alert once so its caption carries the AI text.

    Guards: alert sent with a message id, photo message, not yet synced, active chat,
    token, and an ok caption. Never raises; Telegram failures only warn (no secret values).
    """
    with _sync_lock:  # worker + dispatcher may race on the same alert
        alert = (db.query(Alert).filter_by(event_id=event_id).order_by(Alert.id.desc()).first())
        if alert is None or alert.status != "sent" or not alert.message_id \
                or alert.message_photo is not True or alert.ai_synced:
            return False
        chat = telegram.active_chat(db)
        if chat is None or alert.chat_id != chat.chat_id:
            return False
        token = telegram.get_token()
        text = ai_text(db, event_id)
        if not token or not text:
            return False
        caption = build_caption(db, alert, text)
        chat_id, message_id = alert.chat_id, alert.message_id  # baca sebelum commit (atribut expired)
        db.commit()  # tutup transaksi baca sebelum jaringan; edit tidak boleh memegang transaksi
        try:
            status, error = telegram.edit_caption(token, chat_id, message_id, caption)
        except Exception as exc:
            # str(exception) bisa memuat nilai apa pun (mis. token di pesan); log tanpa detail
            logger.error("telegram caption sync failed for event %s: %s", event_id, type(exc).__name__)
            db.rollback()
            return False
        if status != "edited":
            logger.warning("telegram caption edit failed for event %s: %s", event_id, error)
            return False
        alert.ai_synced = True
        db.commit()
        return True