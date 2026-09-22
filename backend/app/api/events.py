import logging
import os
import uuid
from datetime import datetime, date, time, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import func
from app.core.db import get_db
from app.api.deps import COOKIE, get_current_user
from app.core.security import decode_token
from app.core.config import settings
from app.models.event import Event
from app.models.node import Node, mark_stale_nodes
from app.schemas.event import EventIn, EventOut
from app.services.ingest import ingest_event, ALLOWED_TYPES, ALLOWED_SEVERITY
from app.ws.hub import hub

router = APIRouter()

logger = logging.getLogger(__name__)

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

BLOB_KINDS = {"clip": "mp4", "snapshot": "jpg", "crop": "jpg", "face": "jpg"}
MAX_BLOB_SIZE = 200 * 1024 * 1024

@router.post("/internal/nodes/{node_id}/blobs")
async def upload_blob(node_id: str, kind: str, request: Request, authorization: str = Header("")):
    if authorization != f"Bearer {settings.node_api_key}":
        raise HTTPException(401, "invalid node api key")
    if kind not in BLOB_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(BLOB_KINDS)}")
    length = int(request.headers.get("content-length") or 0)
    if length > MAX_BLOB_SIZE:
        raise HTTPException(413, "blob too large")
    rel = f"{kind}s/{datetime.now(timezone.utc):%Y/%m/%d}/{uuid.uuid4()}.{BLOB_KINDS[kind]}"
    dest = Path(settings.storage_root) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = await request.body()
    if len(body) > MAX_BLOB_SIZE:
        raise HTTPException(413, "blob too large")
    dest.write_bytes(body)
    return {"path": rel}

@router.post("/internal/nodes/{node_id}/heartbeat")
async def heartbeat(node_id: int, authorization: str = Header(""), db=Depends(get_db)):
    if authorization != f"Bearer {settings.node_api_key}":
        raise HTTPException(401, "invalid node api key")
    node = db.get(Node, node_id)
    if not node:
        raise HTTPException(404, "node not found")
    node.status = "online"
    node.last_seen = datetime.now(timezone.utc)
    db.commit()
    logger.debug("heartbeat from node %s", node_id)  # body ignored: dashboard only needs status+last_seen
    return {"status": "ok", "node_id": node_id, "seen": True}

@router.post("/internal/maintenance/mark-stale")
def mark_stale(authorization: str = Header(""), db=Depends(get_db)):
    if authorization != f"Bearer {settings.node_api_key}":
        raise HTTPException(401, "invalid node api key")
    return {"status": "ok", "marked": mark_stale_nodes(db)}

@router.get("/api/v1/media/{path:path}")
def media(path: str, user=Depends(get_current_user)):
    root = os.path.realpath(settings.storage_root)
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        raise HTTPException(404, "media not found")
    media_type = "video/mp4" if full.endswith(".mp4") else "image/jpeg"
    return FileResponse(full, media_type=media_type)

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
    # UI memakai cookie httpOnly — token query hanya fallback (klien non-browser).
    token = ws.query_params.get("token", "") or ws.cookies.get(COOKIE, "")
    if not decode_token(token):
        await ws.close(code=1008)
        return
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive; client never sends meaningful data
    except WebSocketDisconnect:
        hub.disconnect(ws)
