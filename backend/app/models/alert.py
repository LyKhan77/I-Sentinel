from datetime import datetime, timezone
from sqlalchemy import Boolean, String, Integer, DateTime, ForeignKey, false
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base


class Alert(Base):
    """One row per event — rate-limited/not-configured attempts are recorded too."""
    __tablename__ = "alert"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), unique=True, nullable=False)
    camera_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("camera.id", ondelete="SET NULL"), nullable=True)
    zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # no FK — zones come Fase 2
    type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16), default="info")
    status: Mapped[str] = mapped_column(String(16))  # queued | sent | failed | rate_limited | not_configured
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message_photo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_synced: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    face_synced: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    event: Mapped["Event"] = relationship(lazy="joined")
