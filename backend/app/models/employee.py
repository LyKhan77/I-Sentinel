from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base

MIN_PHOTOS = 3  # foto minimal agar wajah dianggap siap (enrollment-status + EmployeeOut)


class Employee(Base):
    __tablename__ = "employee"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    employee_code: Mapped[str] = mapped_column(String(32), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    shift_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("shift.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    shift: Mapped["Shift | None"] = relationship(lazy="joined")
    embeddings: Mapped[list["FaceEmbedding"]] = relationship(lazy="dynamic", cascade="all, delete-orphan")

    @property
    def shift_name(self) -> str | None:
        return self.shift.name if self.shift else None

    @property
    def photo_count(self) -> int:
        return self.embeddings.count()

    @property
    def face_ready(self) -> bool:
        return self.photo_count >= MIN_PHOTOS
