from datetime import datetime, timezone
from sqlalchemy import JSON, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class Node(Base):
    __tablename__ = "node"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[str] = mapped_column(String(8), default="edge")
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="unknown")
    # hardware probe dari heartbeat vision: {gpus: [...], python_vram_mb} + modules
    hw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    modules: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # GPU pin detektor via config push; None/"" = auto (fallback env VISION_DETECTOR_DEVICE)
    detector_device: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # GPU pin face recognition via config push; None/"" = auto (fallback env VISION_FACE_DEVICE)
    face_device: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
