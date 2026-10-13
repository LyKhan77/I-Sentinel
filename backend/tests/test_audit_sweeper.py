from datetime import datetime, timedelta, timezone

from app.models.audit_log import AuditLog
from app.services import audit, audit_sweeper


def _old_row(db, days_old: int):
    row = audit.record(db, action="camera.update", actor_label="admin")
    row.ts = datetime.now(timezone.utc) - timedelta(days=days_old)
    return row


def test_sweep_removes_only_expired(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "audit_retention_days", 90)
    _old_row(db, 91)
    _old_row(db, 91)
    audit.record(db, action="camera.update", actor_label="admin")  # baru
    db.commit()

    removed = audit_sweeper.sweep_once(db)

    assert removed == 2
    assert db.query(AuditLog).count() == 1


def test_sweep_respects_retention_setting(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "audit_retention_days", 7)
    _old_row(db, 10)
    db.commit()
    assert audit_sweeper.sweep_once(db) == 1
    assert db.query(AuditLog).count() == 0
