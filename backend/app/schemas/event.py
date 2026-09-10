from pydantic import BaseModel, field_validator
from datetime import datetime
import uuid

class EventIn(BaseModel):
    event_id: str
    type: str
    node_id: int | None = None
    camera_id: int | None = None
    zone_id: int | None = None
    severity: str = "info"
    ts_event: datetime | None = None
    payload: dict | None = None
    clip_path: str | None = None
    snapshot_path: str | None = None
    dedup_key: str | None = None

    @field_validator("event_id")
    @classmethod
    def _uuid(cls, v):
        uuid.UUID(v)
        return v

class EventOut(BaseModel):
    id: int
    event_id: str
    type: str
    node_id: int | None
    camera_id: int | None
    zone_id: int | None
    severity: str
    ts_event: datetime
    payload: dict | None
    clip_path: str | None
    snapshot_path: str | None
    dedup_key: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
