"""Kontrak pesan susulan hasil identitas wajah intrusion (topik isentinel/events/face)."""
from pydantic import BaseModel


class FaceResultIn(BaseModel):
    event_id: str
    camera_id: int | None = None
    node_id: str | None = None
    track_id: int | None = None
    embedding: list[float] | None = None
    quality: float | None = None
    crop_path: str | None = None
    seq: int | None = None  # 0 = hasil pertama, >0 = pembaruan progresif
    stats: dict | None = None
