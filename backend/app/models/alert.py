from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base


class Alert(Base):
    """One row per event — rate-limited/not-configured attempts are recorded too."""
    __tablename__ = "alert"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), unique=True, nullable=False)
    camera_id: Mapped[int] = mapped_column(Integer, ForeignKey("camera.id"), nullable=False)
    zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # no FK — zones come Fase 2
    type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16), default="info")
    status: Mapped[str] = mapped_column(String(16))  # sent | failed | rate_limited | not_configured
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    event: Mapped["Event"] = relationship(lazy="joined")
