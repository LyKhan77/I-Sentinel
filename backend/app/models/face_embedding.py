from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class FaceEmbedding(Base):
    __tablename__ = "face_embedding"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("employee.id", ondelete="CASCADE"), nullable=False, index=True)
    vector: Mapped[list] = mapped_column(JSON, nullable=False)  # list[float], 512-d
    source_image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
