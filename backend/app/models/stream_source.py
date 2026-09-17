from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class StreamSource(Base):
    __tablename__ = "stream_source"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="unknown")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=554)
    vendor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_credential_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("credential_profile.id"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    default_credential: Mapped["CredentialProfile | None"] = relationship(
        foreign_keys=[default_credential_id]
    )
