"""Move AI captions and intrusion identity into Telegram alerts, once, whatever the order."""
from __future__ import annotations

import logging
import threading

from sqlalchemy.orm import Session

from app.models import Alert, Camera, EventAi, Zone
from app.services import telegram

logger = logging.getLogger(__name__)

# Satu lock modul: edit Telegram dari worker AI dan identitas tidak boleh saling menimpa.
# Lock tidak pernah menahan transaksi DB (klaim + commit dulu, I/O Telegram di dalam lock).
_edit_lock = threading.Lock()


def ai_text(db: Session, event_id: int) -> str | None:
    """Latest successful auto-caption for the event, or None."""
    row = (db.query(EventAi)
             .filter_by(event_id=event_id, kind="caption", status="ok")
             .order_by(EventAi.id.desc())
             .first())
    return row.answer if row is not None else None


def build_caption(db: Session, alert: Alert, ai: str | None) -> str:
    """Caption builder now shared by the dispatcher and the sync paths."""
    event = alert.event
    if event is None:  # mustahil lewat FK; tetap eksplisit agar dispatcher gagal cepat, bukan mengirim pesan kosong
        raise ValueError("alert has no event")
    camera = db.get(Camera, alert.camera_id) if alert.camera_id else None
    zone = db.get(Zone, alert.zone_id) if alert.zone_id else None
    return telegram.format_caption(
        event, camera.name if camera else f"cam {alert.camera_id}",
        zone.name if zone else None, telegram.app_url(db), ai_text=ai)


def _render_fresh(db: Session, alert_id: int, event_id: int) -> str:
    """Caption dari keadaan DB terbaru; dipanggil di dalam ``_edit_lock``, lalu menutup transaksi baca.

    Render di dalam lock: edit yang menunggu lock tidak boleh mengirim caption basi sesudah edit lain
    mengirim yang lengkap; AI atau identitas yang tiba selagi menunggu ikut tampil.
    """
    db.expire_all()  # sesi memuat objek sekali (expire_on_commit=False); tulisan thread lain tak terlihat
    alert = db.get(Alert, alert_id)
    caption = build_caption(db, alert, ai_text(db, event_id))
    db.commit()  # tutup transaksi baca sebelum I/O jaringan
    return caption


def _release(db: Session, alert_id: int, column: str) -> None:
    """Return a failed claim so a later caller (dispatcher or worker) can try again."""
    try:
        db.query(Alert).filter(Alert.id == alert_id).update({column: False},
                                                            synchronize_session=False)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("could not release %s claim for alert %s: %s", column, alert_id,
                     type(exc).__name__)


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
    alert_id, chat_id, message_id = alert.id, alert.chat_id, alert.message_id  # baca sebelum commit
    claimed = db.query(Alert).filter(Alert.id == alert_id, Alert.ai_synced.is_(False)).update(
        {"ai_synced": True}, synchronize_session=False)
    db.commit()  # tutup transaksi sebelum jaringan; edit tidak boleh memegang transaksi
    if not claimed:
        return False
    try:
        with _edit_lock:
            caption = _render_fresh(db, alert_id, event_id)
            status, error = telegram.edit_caption(token, chat_id, message_id, caption)
    except Exception as exc:
        # str(exception) bisa memuat nilai apa pun (mis. token di pesan); log tanpa detail
        logger.error("telegram caption sync failed for event %s: %s", event_id, type(exc).__name__)
        status, error = "failed", None
    if status != "edited":
        if error:
            logger.warning("telegram caption edit failed for event %s: %s", event_id, error)
        _release(db, alert_id, "ai_synced")
        return False
    return True


def sync_face_caption(db: Session, event_id: int) -> bool:
    """Edit the delivered photo alert once so its caption carries the intrusion identity row.

    Guard sama dengan sync_ai_caption tanpa syarat teks AI; identitas dibaca dari
    ``event.payload.face``. Klaim atomik ``face_synced`` + commit sebelum I/O; edit di dalam
    ``_edit_lock`` supaya tidak menimpa edit worker AI yang berlangsung. Gagal melepas klaim.
    """
    alert = db.query(Alert).filter_by(event_id=event_id).order_by(Alert.id.desc()).first()
    if alert is None or alert.status != "sent" or not alert.message_id:
        return False
    if alert.message_photo is not True:  # alert teks tidak bisa diedit caption-nya
        logger.info("identity_skipped_text_only event=%s", event_id)
        return False
    if not (alert.event.payload or {}).get("face"):
        return False  # identitas belum ada: edit tanpa baris identitas sia-sia; consumer memanggil lagi
    chat = telegram.active_chat(db)
    if chat is None or alert.chat_id != chat.chat_id:
        return False
    token = telegram.get_token()
    if not token:
        return False
    alert_id, chat_id, message_id = alert.id, alert.chat_id, alert.message_id
    claimed = db.query(Alert).filter(Alert.id == alert_id, Alert.face_synced.is_(False)).update(
        {"face_synced": True}, synchronize_session=False)
    db.commit()
    if not claimed:
        return False
    try:
        with _edit_lock:
            caption = _render_fresh(db, alert_id, event_id)
            status, error = telegram.edit_caption(token, chat_id, message_id, caption)
    except Exception as exc:
        logger.error("telegram identity sync failed for event %s: %s", event_id, type(exc).__name__)
        status, error = "failed", None
    if status != "edited":
        if error:
            logger.warning("telegram identity edit failed for event %s: %s", event_id, error)
        _release(db, alert_id, "face_synced")
        return False
    return True
