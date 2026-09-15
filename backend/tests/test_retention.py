from datetime import datetime, timezone

from app.models.event import Event


def test_event_defaults_media_expired_false(db):
    ev = Event(type="intrusion", ts_event=datetime.now(timezone.utc))
    db.add(ev)
    db.commit()
    db.refresh(ev)
    assert ev.media_expired is False
