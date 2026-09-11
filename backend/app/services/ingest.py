from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from app.models.event import Event
from app.models.node import Node

ALLOWED_TYPES = {"intrusion", "loitering", "running", "attendance", "person_detect", "system"}
ALLOWED_SEVERITY = {"critical", "warning", "info"}

def ingest_event(db, data: dict) -> tuple[str, Event | None]:
    # ts_event ISO string → datetime (vision kirim ISO; SQLite butuh objek datetime)
    ts = data.get("ts_event")
    if isinstance(ts, str):
        try:
            data["ts_event"] = datetime.fromisoformat(ts)
        except ValueError:
            data["ts_event"] = None
    # Kontrak vision: node_id = nama node (str). Resolve ke id FK; unknown → None.
    node_id = data.get("node_id")
    if isinstance(node_id, str) and not node_id.isdigit():
        node = db.query(Node).filter(Node.name == node_id).first()
        node_id = node.id if node else None
    ev = Event(
        event_id=data["event_id"],
        type=data["type"],
        node_id=node_id,
        camera_id=data.get("camera_id"),
        zone_id=data.get("zone_id"),
        severity=data.get("severity", "info"),
        ts_event=data.get("ts_event") or datetime.now(timezone.utc),
        payload=data.get("payload"),
        clip_path=data.get("clip_path"),
        snapshot_path=data.get("snapshot_path"),
        dedup_key=data.get("dedup_key"),
    )
    db.add(ev)
    try:
        db.commit()
        return "created", ev
    except IntegrityError:
        db.rollback()
        existing = db.query(Event).filter(Event.event_id == ev.event_id).first()
        if existing is None:
            existing = db.query(Event).filter(Event.dedup_key == ev.dedup_key).first()
        if existing is None:
            raise
        return "duplicate", existing
