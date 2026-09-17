from unittest.mock import patch

import pytest

from app.models.camera import Camera
from app.models.credential_profile import CredentialProfile
from app.models.stream_source import StreamSource
from app.services.probe import probe_exact
from app.services.stream_endpoint import (
    EffectiveStream,
    StreamEndpointError,
    build_rtsp_url,
    resolve_camera_stream,
)


def test_camera_override_wins_and_path_stays_exact(db, monkeypatch):
    monkeypatch.setenv("CAMERA_CRED_DEFAULT", "default-pass")
    monkeypatch.setenv("CAMERA_CRED_OVERRIDE", "override-pass")
    default = CredentialProfile(name="default", username="nvr", secret_ref="env:CAMERA_CRED_DEFAULT")
    override = CredentialProfile(name="override", username="cam", secret_ref="env:CAMERA_CRED_OVERRIDE")
    source = StreamSource(
        name="NVR",
        kind="nvr",
        host="10.0.0.5",
        port=8554,
        default_credential=default,
    )
    camera = Camera(
        name="CAM-01",
        host="legacy",
        source=source,
        credential_override=override,
        rtsp_main="/vendor/main?profile=high&x=01",
        rtsp_sub="/vendor/sub?profile=low",
    )
    db.add(camera)
    db.commit()

    stream = resolve_camera_stream(camera)

    assert stream.host == "10.0.0.5"
    assert stream.port == 8554
    assert stream.username == "cam"
    assert stream.password == "override-pass"
    assert stream.main_path == "/vendor/main?profile=high&x=01"
    assert build_rtsp_url(stream, stream.main_path) == (
        "rtsp://cam:override-pass@10.0.0.5:8554/vendor/main?profile=high&x=01"
    )


def test_same_path_on_different_sources_remains_distinct(db, monkeypatch):
    monkeypatch.setenv("CAMERA_CRED_A", "a")
    monkeypatch.setenv("CAMERA_CRED_B", "b")
    source_a = StreamSource(
        name="A",
        kind="ip_camera",
        host="10.0.0.1",
        port=554,
        default_credential=CredentialProfile(name="cred-a", username="u", secret_ref="env:CAMERA_CRED_A"),
    )
    source_b = StreamSource(
        name="B",
        kind="ip_camera",
        host="10.0.0.2",
        port=554,
        default_credential=CredentialProfile(name="cred-b", username="u", secret_ref="env:CAMERA_CRED_B"),
    )
    camera_a = Camera(name="A-1", host="legacy-a", source=source_a, rtsp_main="/stream/main")
    camera_b = Camera(name="B-1", host="legacy-b", source=source_b, rtsp_main="/stream/main")
    db.add_all([camera_a, camera_b])
    db.commit()

    assert build_rtsp_url(resolve_camera_stream(camera_a), camera_a.rtsp_main) != build_rtsp_url(
        resolve_camera_stream(camera_b), camera_b.rtsp_main
    )


def test_missing_credential_reference_fails_closed(db):
    profile = CredentialProfile(name="missing", username="admin", secret_ref="env:NOT_SET")
    source = StreamSource(name="NVR", kind="nvr", host="10.0.0.5", default_credential=profile)
    camera = Camera(name="CAM-01", host="legacy", source=source, rtsp_main="/main")
    db.add(camera)
    db.commit()

    with pytest.raises(StreamEndpointError, match="unavailable"):
        resolve_camera_stream(camera)


def test_probe_exact_uses_only_selected_paths(monkeypatch):
    stream = EffectiveStream(
        host="10.0.0.5",
        port=554,
        username="u",
        password="p",
        main_path="/vendor/main",
        sub_path="/vendor/sub?profile=low",
    )
    with patch("app.services.probe.probe_url", side_effect=[{"res": "1x1"}, None]) as probe:
        result = probe_exact(stream)

    assert result["main_path"] == "/vendor/main"
    assert result["sub_path"] == "/vendor/sub?profile=low"
    assert [call.args[0] for call in probe.call_args_list] == [
        "rtsp://u:p@10.0.0.5/vendor/main",
        "rtsp://u:p@10.0.0.5/vendor/sub?profile=low",
    ]


def test_legacy_profile_reads_configured_camera_password(db, monkeypatch):
    from app.core.config import settings

    monkeypatch.delenv("CAM_PASSWORD", raising=False)
    monkeypatch.setattr(settings, "cam_password", "configured-pass")
    profile = CredentialProfile(name="legacy", username="admin", secret_ref="env:CAM_PASSWORD")
    source = StreamSource(name="legacy-source", kind="nvr", host="10.0.0.5", default_credential=profile)
    camera = Camera(name="CAM-01", host="10.0.0.5", source=source, rtsp_main="/main")
    db.add(camera)
    db.commit()

    assert resolve_camera_stream(camera).password == "configured-pass"
