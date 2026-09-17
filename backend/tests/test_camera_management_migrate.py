import pytest

from datetime import datetime, timezone

from app.core.config import settings
from app.models.camera import Camera
from app.models.credential_profile import CredentialProfile
from app.models.location_group import LocationGroup
from app.models.stream_source import StreamSource
from app.models.event import Event
from app.models.zone import Zone
from scripts.camera_management_migrate import apply_backfill, preview_backfill


def _camera(db, name, host, path, location):
    camera = Camera(
        name=name,
        host=host,
        rtsp_main=path,
        rtsp_sub=path.replace("101", "102"),
        location=location,
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


def test_preview_does_not_write_and_apply_is_idempotent(db, monkeypatch):
    monkeypatch.setattr(settings, "cam_username", "admin")
    monkeypatch.setattr(settings, "cam_password", "legacy-pass")
    camera_a = _camera(db, "CAM-01", "10.0.0.1:554", "/Streaming/Channels/101", "Lantai 1")
    camera_b = _camera(db, "CAM-02", "10.0.0.1:554", "/Streaming/Channels/201", "Lantai 1")

    preview = preview_backfill(db)

    assert preview["applied"] is False
    assert preview["camera_count"] == 2
    assert preview["source_count"] == 1
    assert preview["location_group_count"] == 1
    assert preview["credential_profile_count"] == 1
    assert camera_a.source_id is None and camera_b.source_id is None

    result = apply_backfill(db)
    db.refresh(camera_a)
    db.refresh(camera_b)
    assert result["applied"] is True
    assert result["created_sources"] == 1
    assert result["created_location_groups"] == 1
    assert result["created_credential_profiles"] == 1
    assert camera_a.id != camera_b.id
    assert camera_a.source_id == camera_b.source_id
    assert camera_a.location_group_id == camera_b.location_group_id
    assert camera_a.rtsp_main == "/Streaming/Channels/101"

    again = apply_backfill(db)
    assert again["created_sources"] == 0
    assert again["created_location_groups"] == 0
    assert again["created_credential_profiles"] == 0


def test_backfill_preserves_event_and_zone_camera_identity(db, monkeypatch):
    monkeypatch.setattr(settings, "cam_username", "")
    monkeypatch.setattr(settings, "cam_password", "")
    camera = _camera(db, "CAM-01", "10.0.0.2", "/main", "Lobby")
    event = Event(type="person_detect", camera_id=camera.id, ts_event=datetime.now(timezone.utc))
    zone = Zone(
        camera_id=camera.id,
        name="Lobby zone",
        type="restricted",
        polygon=[[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]],
    )
    db.add_all([event, zone])
    db.commit()

    apply_backfill(db)

    assert db.get(Event, event.id).camera_id == camera.id
    assert db.get(Zone, zone.id).camera_id == camera.id


def test_backfill_preserves_existing_references(db, monkeypatch):
    monkeypatch.setattr(settings, "cam_username", "")
    monkeypatch.setattr(settings, "cam_password", "")
    source = StreamSource(name="chosen-source", kind="nvr", host="10.0.0.9")
    group = LocationGroup(name="chosen-group")
    db.add_all([source, group])
    db.commit()
    camera = _camera(db, "CAM-01", "10.0.0.2", "/main", "Legacy group")
    camera.source_id = source.id
    camera.location_group_id = group.id
    db.commit()

    apply_backfill(db)
    db.refresh(camera)

    assert camera.source_id == source.id
    assert camera.location_group_id == group.id


def test_backfill_detects_canonical_duplicate_paths_without_writing(db, monkeypatch):
    monkeypatch.setattr(settings, "cam_username", "")
    monkeypatch.setattr(settings, "cam_password", "")
    _camera(db, "CAM-01", "10.0.0.2", "/main?channel=1", "Lobby")
    _camera(db, "CAM-02", "10.0.0.2", "rtsp://10.0.0.2/main?channel=1", "Lobby")

    preview = preview_backfill(db)

    assert preview["ambiguous"][0]["camera_ids"]
    with pytest.raises(ValueError, match="ambiguous"):
        apply_backfill(db)
