"""Audit coverage and database rollback at settings service commit boundaries."""
import pytest
from app.models.audit_log import AuditLog
from app.models.setting import Setting
from app.services import audit
from tests.conftest import admin_headers
from tests.test_audit_config import client  # noqa: F401


@pytest.mark.parametrize("path,body,action", [
    ("/api/v1/storage/settings", {"clip_days": 7}, "storage_settings.update"),
    ("/api/v1/ai/settings", {"enabled": False}, "ai_settings.update"),
    ("/api/v1/telegram/settings", {"app_url": "http://10.0.0.5"}, "telegram.update"),
    ("/api/v1/detector-settings", None, "detector_setting.update"),
])
def test_settings_update_audited(client, db, path, body, action):
    h = admin_headers(client)
    if body is None:
        body = client.get(path, headers=h).json()
        body.pop("updated_at", None)
    response = client.put(path, json=body, headers=h)
    assert response.status_code == 200, response.text
    row = db.query(AuditLog).filter_by(action=action).one()
    assert row.category == "config"
    assert row.actor_label == "admin"


@pytest.mark.parametrize("path,body", [
    ("/api/v1/storage/settings", {"clip_days": 7}),
    ("/api/v1/ai/settings", {"enabled": False}),
])
def test_audit_failure_rolls_back_settings(client, db, monkeypatch, path, body):
    h = admin_headers(client)
    before = {r.key: r.value for r in db.query(Setting).all()}
    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(audit, "record", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        client.put(path, json=body, headers=h)
    db.rollback()
    assert {r.key: r.value for r in db.query(Setting).all()} == before
