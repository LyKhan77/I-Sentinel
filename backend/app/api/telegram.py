from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.models.telegram_chat import TelegramChat

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])


@router.get("/status")
def telegram_status(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "configured": bool(settings.telegram_bot_token),
        "active_chats": db.query(TelegramChat).filter_by(active=True).count(),
    }
