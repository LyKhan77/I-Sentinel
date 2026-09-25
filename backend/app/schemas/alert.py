from datetime import datetime
from pydantic import BaseModel


class AlertOut(BaseModel):
    id: int
    event_id: int
    camera_id: int | None
    zone_id: int | None
    type: str
    severity: str
    status: str
    error: str | None
    chat_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
