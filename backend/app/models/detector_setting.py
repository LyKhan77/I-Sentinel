from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DetectorSetting(Base):
    __tablename__ = "detector_setting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    default_ai_fps: Mapped[float] = mapped_column(Float, nullable=False)
    default_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    motion_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    motion_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    motion_min_area: Mapped[float] = mapped_column(Float, nullable=False)
    motion_force_interval_s: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )
