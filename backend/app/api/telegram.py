"""Setelan bot Telegram (admin). Token write-only: tak pernah keluar di response/error/log."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.db import get_db
from app.models.alert import Alert
from app.models.telegram_chat import TelegramChat
from app.services import secret_store, telegram

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])


class TelegramSettingsIn(BaseModel):
    token: str | None = Field(default=None, max_length=128)  # write-only
    chat_id: str | None = Field(default=None, max_length=64)
    chat_title: str | None = Field(default=None, max_length=128)
    app_url: str | None = Field(default=None, max_length=256)  # http(s) divalidasi di handler (lihat put_settings)


def _settings_out(db: Session) -> dict:
    chat = telegram.active_chat(db)
    last = db.query(Alert).order_by(Alert.id.desc()).first()
    return {
        "has_token": bool(telegram.get_token()),
        "chat_id": chat.chat_id if chat else None,
        "chat_title": chat.label if chat else None,
        "app_url": telegram.app_url(db),
        "last_alert": ({"status": last.status, "error": last.error, "created_at": last.created_at}
                       if last else None),
    }


@router.get("/status")
def telegram_status(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Ringkasan konfig untuk banner UI — terbuka bagi user terautentikasi (bukan hanya admin)."""
    return {
        "configured": bool(telegram.get_token()),
        "active_chats": db.query(TelegramChat).filter_by(active=True).count(),
    }


@router.get("/settings")
def get_settings(admin=Depends(require_admin), db: Session = Depends(get_db)):
    return _settings_out(db)


@router.put("/settings")
def put_settings(body: TelegramSettingsIn, admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Simpan token (validasi format + getMe sebelum ditulis), grup, dan/atau URL aplikasi.

    Token hanya dibaca-tulis lewat secret_store; tidak pernah di-echo. Field yang tidak dikirim
    tidak diubah (exclude_unset), sehingga PUT sebagian tidak menimpa setelan lain. Semua validasi
    dijalankan sebelum efek samping, agar permintaan yang ditolak tidak mengubah setelan.
    """
    fields = body.model_dump(exclude_unset=True, exclude={"token"})
    app_url = fields.get("app_url")
    if "app_url" in fields and app_url and not app_url.strip().startswith(("http://", "https://")):
        raise HTTPException(422, "app_url must be http(s)")  # hanya tautan http(s): dipakai di caption + href UI
    if body.token is not None:
        token = body.token.strip()
        if not telegram.TOKEN_RE.fullmatch(token):
            raise HTTPException(422, "invalid token format")
        try:
            telegram.get_me(token)
        except telegram.TelegramError:
            raise HTTPException(422, "token rejected by Telegram") from None
        try:
            telegram.set_token(token)
        except secret_store.SecretStoreError as exc:  # pesan SecretStoreError hanya berisi path/IO, bukan token
            logger.error("telegram token store write failed: %s", exc)
            raise HTTPException(500, "failed to store token") from None
    if fields.get("chat_id"):
        telegram.set_chat(db, fields["chat_id"], fields.get("chat_title") or fields["chat_id"])
    if "app_url" in fields:
        telegram.set_app_url(db, app_url)
    db.commit()
    return _settings_out(db)


@router.post("/discover")
def discover(admin=Depends(require_admin)):
    """Daftar grup tempat bot ada (getUpdates). 502 memakai pesan TelegramError yang sudah bebas token."""
    token = telegram.get_token()
    if not token:
        raise HTTPException(409, "token not configured")
    try:
        return {"chats": telegram.get_updates(token)}
    except telegram.TelegramError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post("/test")
def send_test(admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Kirim pesan uji ke grup aktif (1 percobaan, tanpa backoff agar request tak tertahan)."""
    token = telegram.get_token()
    chat = telegram.active_chat(db)
    if not token or chat is None:
        raise HTTPException(409, "telegram not configured")
    status, error = telegram.deliver(token, chat.chat_id, telegram.TEST_TEXT, retries=1)
    return {"status": status, "error": error}
