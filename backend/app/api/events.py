from datetime import datetime, date, time
from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from app.core.db import get_db
from app.api.deps import get_current_user
from app.core.security import decode_token
from app.core.config import settings
from app.models.event import Event
from app.models.node import Node
from app.schemas.event import EventIn, EventOut
from app.services.ingest import ingest_event, ALLOWED_TYPES, ALLOWED_SEVERITY
from app.ws.hub import hub

router = APIRouter()

@router.post("/internal/nodes/{node_id}/events")
async def ingest(node_id: int, body: EventIn, authorization: str = Header(""), db=Depends(get_db)):
    if authorization != f"Bearer {settings.node_api_key}":
        raise HTTPException(401, "invalid node api key")
    if body.type not in ALLOWED_TYPES:
        raise HTTPException(422, f"type must be one of {sorted(ALLOWED_TYPES)}")
    if body.severity not in ALLOWED_SEVERITY:
        raise HTTPException(422, f"severity must be one of {sorted(ALLOWED_SEVERITY)}")
    data = body.model_dump()
    data["node_id"] = node_id
    status, ev = ingest_event(db, data)
    if status == "created":
        node = db.get(Node, node_id)
        if node:
            node.last_seen = datetime.now().astimezone()
            db.commit()
        await hub.broadcast(EventOut.model_validate(ev).model_dump(mode="json"))
    return {"status": status, "id": ev.id}

@router.get("/api/v1/events", response_model=list[EventOut])
def list_events(
    camera_id: int | None = None,
    type: str | None = None,
    since: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    q = db.query(Event)
    if camera_id is not None: q = q.filter(Event.camera_id == camera_id)
    if type: q = q.filter(Event.type == type)
    if since: q = q.filter(Event.ts_event >= since)
    return q.order_by(Event.ts_event.desc()).limit(limit).all()

@router.get("/api/v1/events/stats/today")
def stats_today(user=Depends(get_current_user), db=Depends(get_db)):
    midnight = datetime.combine(date.today(), time.min).astimezone()
    rows = (
        db.query(Event.type, func.count(Event.id))
        .filter(Event.ts_event >= midnight)
        .group_by(Event.type)
        .all()
    )
    return {"total": sum(c for _, c in rows), "by_type": {t: c for t, c in rows}}

@router.websocket("/api/v1/ws/events")
async def ws_events(ws: WebSocket):
    token = ws.query_params.get("token", "")
    if not decode_token(token):
        await ws.close(code=1008)
        return
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive; client never sends meaningful data
    except WebSocketDisconnect:
        hub.disconnect(ws)
