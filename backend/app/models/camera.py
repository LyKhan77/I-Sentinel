from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base

class Camera(Base):
    __tablename__ = "camera"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    host: Mapped[str] = mapped_column(String(64))
    rtsp_main: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rtsp_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    node_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("node.id"), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    probe_main: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    probe_sub: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    node: Mapped["Node"] = relationship()
