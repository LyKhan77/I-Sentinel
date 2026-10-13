from datetime import datetime, timezone

from app.models.audit_log import AuditLog


def test_audit_log_table_exists(db):
    row = AuditLog(
        ts=datetime.now(timezone.utc), category="config", action="camera.update",
        actor_id=None, actor_label="admin", target_type="camera", target_id="3",
        target_label="Gerbang", changes={"name": "Gerbang"}, ip="10.0.0.1",
        user_agent="pytest", status="ok", prev_hash="0" * 64, hash="a" * 64,
    )
    db.add(row)
    db.commit()
    assert db.query(AuditLog).count() == 1
    assert db.query(AuditLog).one().actor_label == "admin"
