import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class Event(Base):
    __tablename__ = "event"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, default=lambda: str(uuid.uuid4()))
    type: Mapped[str] = mapped_column(String(32))
    node_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("node.id"), nullable=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("camera.id"), nullable=True)
    zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # no FK — zones come Fase 2
    severity: Mapped[str] = mapped_column(String(16), default="info")
    ts_event: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    clip_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
