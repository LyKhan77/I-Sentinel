"""Move AI captions into Telegram alerts, once, whatever the completion order."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Alert, Camera, EventAi, Zone
from app.services import telegram

logger = logging.getLogger(__name__)

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
    if event is None:  # mustahil lewat FK; tetap eksplisit agar dispatcher gagal cepat, bukan mengirim pesan kosong
        raise ValueError("alert has no event")
    camera = db.get(Camera, alert.camera_id) if alert.camera_id else None
    zone = db.get(Zone, alert.zone_id) if alert.zone_id else None
    return telegram.format_caption(
        event, camera.name if camera else f"cam {alert.camera_id}",
        zone.name if zone else None, telegram.app_url(db), ai_text=ai)


def _release(db: Session, alert_id: int) -> None:
    """Return a failed claim so a later caller (dispatcher or worker) can try again."""
    try:
        db.query(Alert).filter(Alert.id == alert_id).update({"ai_synced": False}, synchronize_session=False)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("could not release ai caption claim for alert %s: %s", alert_id, type(exc).__name__)


def sync_ai_caption(db: Session, event_id: int) -> bool:
    """Edit the delivered photo alert once so its caption carries the AI text.

    Guards: alert sent with a message id, photo message, active chat, token, and an ok caption.
    The edit is claimed with one atomic ``UPDATE ... WHERE ai_synced = false``, so the dispatcher and
    the AI worker can never both edit, whatever stale state their sessions hold (SessionLocal uses
    expire_on_commit=False) and without any lock held across network I/O. A failed edit releases the
    claim. Never raises; Telegram failures only warn (no secret values).
    """
    alert = db.query(Alert).filter_by(event_id=event_id).order_by(Alert.id.desc()).first()
    if alert is None or alert.status != "sent" or not alert.message_id or alert.message_photo is not True:
        return False
    chat = telegram.active_chat(db)
    if chat is None or alert.chat_id != chat.chat_id:
        return False
    token = telegram.get_token()
    text = ai_text(db, event_id)
    if not token or not text:
        return False
    caption = build_caption(db, alert, text)
    alert_id, chat_id, message_id = alert.id, alert.chat_id, alert.message_id  # baca sebelum commit
    claimed = db.query(Alert).filter(Alert.id == alert_id, Alert.ai_synced.is_(False)).update(
        {"ai_synced": True}, synchronize_session=False)
    db.commit()  # tutup transaksi sebelum jaringan; edit tidak boleh memegang transaksi
    if not claimed:
        return False
    try:
        status, error = telegram.edit_caption(token, chat_id, message_id, caption)
    except Exception as exc:
        # str(exception) bisa memuat nilai apa pun (mis. token di pesan); log tanpa detail
        logger.error("telegram caption sync failed for event %s: %s", event_id, type(exc).__name__)
        status, error = "failed", None
    if status != "edited":
        if error:
            logger.warning("telegram caption edit failed for event %s: %s", event_id, error)
        _release(db, alert_id)
        return False
    return True
