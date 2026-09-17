import pytest
from sqlalchemy.exc import IntegrityError

from app.models.camera import Camera
from app.models.credential_profile import CredentialProfile
from app.models.location_group import LocationGroup
from app.models.stream_source import StreamSource


def test_camera_references_source_group_and_credential(db):
    profile = CredentialProfile(name="nvr-main", username="admin", secret_ref="env:CAMERA_CRED_MAIN")
    source = StreamSource(
        name="NVR-MAIN",
        kind="nvr",
        host="192.168.2.184",
        port=554,
        default_credential=profile,
    )
    group = LocationGroup(name="Lantai 3", sort_order=1)
    camera = Camera(
        name="NVR-CAM-01",
        location="Lantai 3 - IOT samping",
        host="192.168.2.184",
        rtsp_main="/Streaming/Channels/101",
        rtsp_sub="/Streaming/Channels/102",
        source=source,
        location_group=group,
        credential_override=profile,
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)

    assert camera.id is not None
    assert camera.source_id == source.id
    assert camera.location_group_id == group.id
    assert camera.credential_override_id == profile.id
    assert camera.source.host == "192.168.2.184"
    assert camera.rtsp_main == "/Streaming/Channels/101"


def test_source_name_is_unique(db):
    db.add_all(
        [
            StreamSource(name="same", kind="nvr", host="10.0.0.1", port=554),
            StreamSource(name="same", kind="ip_camera", host="10.0.0.2", port=554),
        ]
    )
    with pytest.raises(IntegrityError):
        db.commit()
