
import pytest

@pytest.fixture
def probe(monkeypatch):
    import app.services.alert_ai as aa
    calls = []
    orig = aa.sync_face_caption
    def wrapped(db_, eid):
        from app.models import Alert
        a = db_.query(Alert).filter_by(event_id=eid).order_by(Alert.id.desc()).first()
        calls.append((a.status if a else None, a.message_id if a else None,
                      a.message_photo if a else None,
                      bool((a.event.payload or {}).get("face")) if a is not None and a.event else None))
        return orig(db_, eid)
    monkeypatch.setattr(aa, "sync_face_caption", wrapped)
    return calls
