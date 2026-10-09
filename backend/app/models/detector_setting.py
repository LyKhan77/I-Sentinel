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
    face_min_width_px: Mapped[float] = mapped_column(Float, nullable=False, default=80.0)
    face_min_det_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    face_max_yaw: Mapped[float] = mapped_column(Float, nullable=False, default=0.35)
    face_blur_min: Mapped[float] = mapped_column(Float, nullable=False, default=120.0)
    face_min_frames: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    face_match_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.40)
    face_match_margin: Mapped[float] = mapped_column(Float, nullable=False, default=0.15)
    face_max_pitch: Mapped[float] = mapped_column(Float, nullable=False, default=0.30)
    face_best_k: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    face_ident_min_width_px: Mapped[float] = mapped_column(Float, nullable=False, default=60.0)
    face_ident_window_s: Mapped[float] = mapped_column(Float, nullable=False, default=8.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )
