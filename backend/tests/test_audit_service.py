from datetime import time

from app.models.audit_log import AuditLog
from app.models.user import User
from app.services import audit


def test_chain_genesis_and_link(db):
    r1 = audit.record(db, action="camera.update", actor_label="admin", changes={"name": "Gerbang"})
    r2 = audit.record(db, action="camera.update", actor_label="admin")
    db.commit()
    assert r1.prev_hash == audit.GENESIS
    assert r2.prev_hash == r1.hash
    assert r1.hash != r2.hash


def test_category_derived_from_action(db):
    r = audit.record(db, action="auth.login", actor_label="admin")
    assert r.category == "auth"


def test_category_maps_entities_to_spec_categories(db):
    assert audit.record(db, action="camera.update", actor_label="admin").category == "config"
    assert audit.record(db, action="zone.delete", actor_label="admin").category == "config"
    assert audit.record(db, action="storage.cleanup", actor_label="admin").category == "config"
    assert audit.record(db, action="employee.create", actor_label="admin").category == "attendance"
    assert audit.record(db, action="attendance.correct", actor_label="admin").category == "attendance"


def test_actor_resolution(db):
    u = User(username="budi", password_hash="x", role="admin")
    db.add(u)
    db.flush()
    r = audit.record(db, action="auth.login", actor=u)
    assert r.actor_id == u.id
    assert r.actor_label == "budi"
    r2 = audit.record(db, action="auth.login_failed", actor_label="budi")
    assert r2.actor_id is None
    assert r2.status == "failed"


def test_sanitize_masks_secret_like_keys(db):
    r = audit.record(db, action="credential_profile.update", actor_label="admin", changes={
        "username": "nvr",
        "secret_ref": "store:cred_1",
        "api_key": "abc123",
        "token": "t",
        "default_credential_id": 7,
    })
    db.commit()
    assert r.changes == {
        "username": "nvr",
        "secret_ref": "***",
        "api_key": "***",
        "token": "***",
        "default_credential_id": "***",
    }


def test_changes_canonicalized_to_json_native(db):
    r = audit.record(db, action="attendance.correct", actor_label="admin",
                     changes={"first_entry": time(7, 30)})
    db.commit()
    assert r.changes == {"first_entry": "07:30:00"}


def test_verify_ok_and_tamper(db):
    audit.record(db, action="zone.create", actor_label="admin")
    audit.record(db, action="zone.delete", actor_label="admin")
    db.commit()
    assert audit.verify(db) == {"ok": True, "checked": 2, "first_break_id": None}
    row = db.query(AuditLog).order_by(AuditLog.id).first()
    row.action = "tampered"
    db.commit()
    result = audit.verify(db)
    assert result["ok"] is False
    assert result["first_break_id"] == row.id
    assert result["checked"] == 0


def test_verify_empty_table(db):
    assert audit.verify(db) == {"ok": True, "checked": 0, "first_break_id": None}
