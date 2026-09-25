from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import String, Integer, Float, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base


def _path_only(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if "://" in raw:
        parsed = urlsplit(raw)
        raw = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return raw if raw.startswith("/") else f"/{raw}"

class Camera(Base):
    __tablename__ = "camera"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    host: Mapped[str] = mapped_column(String(64))
    rtsp_main: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rtsp_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    node_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("node.id"), nullable=True)
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("stream_source.id"), nullable=True, index=True
    )
    location_group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("location_group.id"), nullable=True, index=True
    )
    credential_override_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("credential_profile.id"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    probe_main: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    probe_sub: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="unknown")
    meters_per_pixel: Mapped[float | None] = mapped_column(Float, nullable=True)  # null = belum dikalibrasi
    # R5 "Detection & Model": override per kamera (null = pakai nilai global).
    ai_fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Daftar analyzer aktif utk kamera ini; null = semua, [] = tanpa analitik (hemat GPU).
    # deprecated: tidak dibaca (zona = satu-satunya aturan); tanpa migrasi
    analyzers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    motion_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    node: Mapped["Node"] = relationship()
    source: Mapped["StreamSource | None"] = relationship(foreign_keys=[source_id])
    location_group: Mapped["LocationGroup | None"] = relationship(foreign_keys=[location_group_id])
    credential_override: Mapped["CredentialProfile | None"] = relationship(
        foreign_keys=[credential_override_id]
    )
    
    @property
    def main_path(self) -> str | None:
        return _path_only(self.rtsp_main)

    @property
    def sub_path(self) -> str | None:
        return _path_only(self.rtsp_sub)
