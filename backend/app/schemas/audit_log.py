from datetime import datetime

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: int
    ts: datetime
    category: str
    action: str
    actor_id: int | None
    actor_label: str
    target_type: str | None
    target_id: str | None
    target_label: str | None
    changes: dict | None
    ip: str | None
    user_agent: str | None
    status: str
    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    total: int
    items: list[AuditLogOut]


class AuditVerifyOut(BaseModel):
    ok: bool
    checked: int
    first_break_id: int | None
