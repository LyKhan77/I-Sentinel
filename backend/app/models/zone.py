from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base

class Zone(Base):
    __tablename__ = "zone"
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(Integer, ForeignKey("camera.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(16))  # free | restricted | absensi
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True)  # entry | exit
    polygon: Mapped[list] = mapped_column(JSON, nullable=False)
    schedule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    rate_limit_min: Mapped[int] = mapped_column(Integer, default=5)
    loiter_seconds: Mapped[int] = mapped_column(Integer, default=0)  # 0 = off
    speed_limit_mps: Mapped[float] = mapped_column(Float, default=0)  # 0 = off
    snapshot: Mapped[bool] = mapped_column(Boolean, default=True)
    clip: Mapped[bool] = mapped_column(Boolean, default=True)  # toggle rekam clip per zona
    telegram: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    camera: Mapped["Camera"] = relationship(lazy="joined")

    @property
    def camera_name(self) -> str | None:
        return self.camera.name if self.camera else None
