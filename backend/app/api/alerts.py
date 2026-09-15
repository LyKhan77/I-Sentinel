from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.alert import Alert
from app.models.event import Event
from app.schemas.alert import AlertOut

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

MAX_BY_EVENT_IDS = 100


@router.get("", response_model=list[AlertOut])
def list_alerts(
    event_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Alert)
    if event_id is not None:
        q = q.filter(Alert.event_id == event_id)
    return q.order_by(Alert.created_at.desc()).limit(limit).all()


@router.get("/by-events")
def alerts_by_events(
    ids: str = "",
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Event.event_id (uuid) → latest alert status. One call for a list badge (no N+1)."""
    wanted = [i.strip() for i in ids.split(",") if i.strip()][:MAX_BY_EVENT_IDS]
    if not wanted:
        return {}
    rows = (
        db.query(Event.event_id, Alert.status)
        .join(Alert, Alert.event_id == Event.id)
        .filter(Event.event_id.in_(wanted))
        .order_by(Alert.created_at.asc())
        .all()
    )
    out: dict[str, str] = {}
    for event_uuid, status in rows:  # ascending → latest row wins
        out[event_uuid] = status
    return out
