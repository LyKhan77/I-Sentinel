from datetime import datetime, timezone, date
from sqlalchemy import String, Integer, Float, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class AttendanceEvent(Base):
    __tablename__ = "attendance_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    camera_id: Mapped[int] = mapped_column(Integer, ForeignKey("camera.id"), nullable=False)
    zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # no FK — zones Fase 2
    direction: Mapped[str] = mapped_column(String(8))  # entry | exit
    ts_event: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_id: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AttendanceDay(Base):
    __tablename__ = "attendance_day"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    first_entry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_exit: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="waiting")  # ontime|late|waiting|no_exit|absent
    late_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    override_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (UniqueConstraint("employee_id", "date"),)
