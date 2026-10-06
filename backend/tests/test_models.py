from app.models.user import User
from app.models.camera import Camera
from app.models.node import Node

def test_user_roundtrip(db):
    u = User(username="admin", password_hash="h", role="admin")
    db.add(u); db.commit()
    assert db.query(User).filter_by(username="admin").one().role == "admin"

def test_camera_belongs_to_node(db):
    n = Node(name="server", type="server"); db.add(n); db.commit()
    c = Camera(name="CAM-01", host="192.168.1.108", node_id=n.id,
               probe_main={"res": "2560x1440", "fps": 25, "codec": "h264"})
    db.add(c); db.commit()
    assert c.node.name == "server"
    assert c.probe_main["fps"] == 25


def test_event_ai_requires_existing_event(db):
    from datetime import datetime, timezone
    import pytest
    from sqlalchemy.exc import IntegrityError
    from app.models.event import Event
    from app.models.event_ai import EventAi

    ev = Event(type="intrusion", ts_event=datetime.now(timezone.utc))
    db.add(ev)
    db.commit()
    row = EventAi(event_id=ev.id, kind="caption", channel="auto")
    db.add(row)
    db.commit()
    assert db.get(EventAi, row.id).status == "pending"
    db.add(EventAi(event_id=999, kind="ask", channel="web"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
