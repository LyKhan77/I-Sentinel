import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db
from tests.conftest import *  # noqa

@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "cookie_secure", True)  # httpx tidak replay cookie secure → uji 401 tanpa token valid
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:  # context manager memicu startup/bootstrap
        yield c
    app.dependency_overrides.clear()

def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}

def test_create_camera_requires_auth(client):
    assert client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}).status_code == 401

def test_create_camera_as_admin_and_list(client):
    h = _admin_headers(client)
    r = client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4", "node_id": 1}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "cam1" and r.json()["node_id"] == 1
    assert r.json()["enabled"] is True and r.json()["status"] == "unknown"
    assert r.json()["rtsp_main"] is None and r.json()["probe_main"] is None
    names = [c["name"] for c in client.get("/api/v1/cameras", headers=h).json()]
    assert "cam1" in names

def test_create_duplicate_name_same_node_conflict(client):
    h = _admin_headers(client)
    body = {"name": "cam1", "host": "1.2.3.4", "node_id": 1}
    assert client.post("/api/v1/cameras", json=body, headers=h).status_code == 200
    assert client.post("/api/v1/cameras", json=body, headers=h).status_code == 409

def test_create_camera_bad_node_422(client):
    h = _admin_headers(client)
    assert client.post("/api/v1/cameras", json={"name": "c", "host": "h", "node_id": 999}, headers=h).status_code == 422

def test_patch_camera_enabled_false(client):
    h = _admin_headers(client)
    cid = client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/cameras/{cid}", json={"enabled": False}, headers=h)
    assert r.status_code == 200 and r.json()["enabled"] is False

def test_delete_camera_then_get_404(client):
    h = _admin_headers(client)
    cid = client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}, headers=h).json()["id"]
    assert client.delete(f"/api/v1/cameras/{cid}", headers=h).status_code == 200
    assert client.get(f"/api/v1/cameras/{cid}", headers=h).status_code == 404

def test_delete_camera_with_attendance_409(client, db):
    import datetime as dt
    from app.models.attendance import AttendanceEvent
    from app.models.employee import Employee
    h = _admin_headers(client)
    cid = client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}, headers=h).json()["id"]
    emp = Employee(name="Budi", employee_code="E001")
    db.add(emp); db.commit()
    db.add(AttendanceEvent(employee_id=emp.id, camera_id=cid, direction="entry",
                           ts_event=dt.datetime.now(dt.timezone.utc)))
    db.commit()
    assert client.delete(f"/api/v1/cameras/{cid}", headers=h).status_code == 409

def test_nodes_list_seeded(client):
    h = _admin_headers(client)
    r = client.get("/api/v1/nodes", headers=h)
    assert r.status_code == 200
    names = [(n["name"], n["type"], n["status"]) for n in r.json()]
    assert ("server", "server", "unknown") in names

def test_probe_persists_result_with_camera_id(client, monkeypatch):
    from unittest.mock import patch
    h = _admin_headers(client)
    cam = client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}, headers=h).json()
    fake = {"main": {"res": "2560x1440", "fps": 25.0, "codec": "h264"}, "sub": None,
            "main_path": "rtsp://x/main", "sub_path": None}
    with patch("app.api.probe.probe_camera", return_value=fake):
        r = client.post("/api/v1/cameras/probe", json={"host": "1.2.3.4", "camera_id": cam["id"]}, headers=h)
    assert r.status_code == 200 and r.json() == fake
    listed = [c for c in client.get("/api/v1/cameras", headers=h).json() if c["id"] == cam["id"]][0]
    assert listed["probe_main"] == fake["main"] and listed["probe_sub"] is None
    assert listed["status"] == "online"

    fake_off = {"main": None, "sub": None, "main_path": None, "sub_path": None}
    with patch("app.api.probe.probe_camera", return_value=fake_off):
        client.post("/api/v1/cameras/probe", json={"host": "1.2.3.4", "camera_id": cam["id"]}, headers=h)
    listed = [c for c in client.get("/api/v1/cameras", headers=h).json() if c["id"] == cam["id"]][0]
    assert listed["status"] == "offline"

def test_probe_without_camera_id_does_not_persist(client, monkeypatch):
    from unittest.mock import patch
    h = _admin_headers(client)
    client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}, headers=h)
    fake = {"main": {"res": "640x360", "fps": 15.0, "codec": "h264"}, "sub": None,
            "main_path": "rtsp://x/main", "sub_path": None}
    with patch("app.api.probe.probe_camera", return_value=fake):
        assert client.post("/api/v1/cameras/probe", json={"host": "1.2.3.4"}, headers=h).status_code == 200
    listed = client.get("/api/v1/cameras", headers=h).json()[0]
    assert listed["probe_main"] is None and listed["status"] == "unknown"

def test_patch_camera_persists_probe_metadata(client):
    h = _admin_headers(client)
    cid = client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}, headers=h).json()["id"]
    probe = {"res": "2560x1440", "fps": 25.0, "codec": "h264"}
    r = client.patch(f"/api/v1/cameras/{cid}", json={
        "host": "1.2.3.5", "rtsp_main": "/Streaming/Channels/101", "rtsp_sub": "/Streaming/Channels/102",
        "probe_main": probe, "probe_sub": None, "status": "online",
    }, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["host"] == "1.2.3.5"
    assert body["probe_main"] == probe and body["probe_sub"] is None and body["status"] == "online"
    listed = [c for c in client.get("/api/v1/cameras", headers=h).json() if c["id"] == cid][0]
    assert listed["probe_main"] == probe and listed["probe_sub"] is None and listed["status"] == "online"

    # patch metadata saja tidak menimpa probe tersimpan
    r = client.patch(f"/api/v1/cameras/{cid}", json={"name": "cam2"}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "cam2"
    assert r.json()["probe_main"] == probe and r.json()["status"] == "online"

def test_import_camera_inventory_matches_default_rtsp_port_and_applies(client):
    from unittest.mock import patch

    h = _admin_headers(client)
    client.post("/api/v1/cameras", json={
        "name": "old-1", "location": "old", "host": "192.168.2.184",
        "rtsp_main": "/Streaming/Channels/101", "rtsp_sub": "/Streaming/Channels/102",
    }, headers=h)
    entries = [{
        "name": "NVR-CAM-01", "location": "Lantai 3 - IOT samping",
        "host": "192.168.2.184:554",
        "rtsp_main": "/Streaming/Channels/101", "rtsp_sub": "/Streaming/Channels/102",
    }]

    preview = client.post("/api/v1/cameras/import", json={"entries": entries}, headers=h)
    assert preview.status_code == 200
    assert preview.json()["applied"] is False
    assert preview.json()["matched"] == 1 and preview.json()["updated"] == 1
    assert preview.json()["unmatched"] == [] and preview.json()["errors"] == []
    assert client.get("/api/v1/cameras", headers=h).json()[0]["name"] == "old-1"

    with patch("app.api.cameras.sync_camera"), patch("app.api.cameras._config_push"):
        applied = client.post("/api/v1/cameras/import?apply=true", json={"entries": entries}, headers=h)
    assert applied.status_code == 200 and applied.json()["applied"] is True
    row = client.get("/api/v1/cameras", headers=h).json()[0]
    assert row["name"] == "NVR-CAM-01" and row["location"] == "Lantai 3 - IOT samping"
    assert row["host"] == "192.168.2.184" and row["rtsp_main"].endswith("/101")

def test_import_camera_inventory_refuses_unmatched_apply(client):
    h = _admin_headers(client)
    entries = [{
        "name": "NVR-CAM-99", "location": "Unknown", "host": "192.168.2.184:554",
        "rtsp_main": "/Streaming/Channels/9901", "rtsp_sub": "/Streaming/Channels/9902",
    }]
    preview = client.post("/api/v1/cameras/import", json={"entries": entries}, headers=h)
    assert preview.status_code == 200
    assert preview.json()["matched"] == 0 and len(preview.json()["unmatched"]) == 1
    applied = client.post("/api/v1/cameras/import?apply=true", json={"entries": entries}, headers=h)
    assert applied.status_code == 200 and applied.json()["applied"] is False

def test_import_camera_inventory_requires_admin(client):
    entries = [{
        "name": "NVR-CAM-01", "location": "Lantai 3", "host": "192.168.2.184",
        "rtsp_main": "/Streaming/Channels/101", "rtsp_sub": "/Streaming/Channels/102",
    }]
    assert client.post("/api/v1/cameras/import", json={"entries": entries}).status_code == 401


def test_source_camera_crud_preserves_exact_paths_and_hides_credentials(client):
    from unittest.mock import patch

    h = _admin_headers(client)
    profile = client.post(
        "/api/v1/credential-profiles",
        json={"name": "nvr-main", "username": "viewer", "secret_ref": "env:CAMERA_TEST_SECRET"},
        headers=h,
    ).json()
    source = client.post(
        "/api/v1/stream-sources",
        json={
            "name": "NVR-A",
            "kind": "nvr",
            "host": "10.0.0.5",
            "port": 8554,
            "default_credential_id": profile["id"],
        },
        headers=h,
    ).json()
    group = client.post(
        "/api/v1/location-groups",
        json={"name": "Lantai 1"},
        headers=h,
    ).json()
    with patch("app.api.cameras.sync_camera"), patch("app.api.cameras._config_push"):
        response = client.post(
            "/api/v1/cameras",
            json={
                "name": "CAM-A",
                "source_id": source["id"],
                "location_group_id": group["id"],
                "credential_override_id": profile["id"],
                "main_path": "/vendor/main?profile=high&channel=01",
                "sub_path": "/vendor/sub?profile=low&channel=02",
            },
            headers=h,
        )
    assert response.status_code == 200
    camera = response.json()
    assert camera["host"] == "10.0.0.5:8554"
    assert camera["rtsp_main"] == "/vendor/main?profile=high&channel=01"
    assert camera["main_path"] == camera["rtsp_main"]
    assert camera["sub_path"] == "/vendor/sub?profile=low&channel=02"
    assert camera["source"]["name"] == "NVR-A"
    assert camera["location_group"]["name"] == "Lantai 1"
    assert camera["credential_override"]["name"] == "nvr-main"
    assert "secret_ref" not in camera["credential_override"]
    assert "password" not in camera

    with patch("app.api.cameras.sync_camera"), patch("app.api.cameras._config_push"):
        response = client.patch(
            f"/api/v1/cameras/{camera['id']}",
            json={"main_path": "/vendor/other?profile=recording"},
            headers=h,
        )
    assert response.status_code == 200
    updated = response.json()
    assert updated["main_path"] == "/vendor/other?profile=recording"
    assert updated["sub_path"] == "/vendor/sub?profile=low&channel=02"


def test_same_exact_path_is_allowed_on_different_sources(client):
    from unittest.mock import patch

    h = _admin_headers(client)
    sources = [
        client.post(
            "/api/v1/stream-sources",
            json={"name": name, "kind": "ip_camera", "host": host},
            headers=h,
        ).json()
        for name, host in (("IP-A", "10.0.0.10"), ("IP-B", "10.0.0.11"))
    ]
    payload = {
        "source_id": sources[0]["id"],
        "main_path": "/live/main?profile=ai",
        "sub_path": "/live/sub?profile=ai",
    }
    with patch("app.api.cameras.sync_camera"), patch("app.api.cameras._config_push"):
        first = client.post(
            "/api/v1/cameras",
            json={"name": "A", **payload},
            headers=h,
        )
        second = client.post(
            "/api/v1/cameras",
            json={"name": "B", **{**payload, "source_id": sources[1]["id"]}},
            headers=h,
        )
        duplicate = client.post("/api/v1/cameras", json={"name": "A2", **payload}, headers=h)
    assert first.status_code == 200
    assert second.status_code == 200
    assert duplicate.status_code == 409


def test_probe_camera_with_paths_uses_exact_endpoint(client):
    from unittest.mock import patch

    h = _admin_headers(client)
    source = client.post(
        "/api/v1/stream-sources",
        json={"name": "NVR-Probe", "kind": "nvr", "host": "10.0.0.20"},
        headers=h,
    ).json()
    with patch("app.api.cameras.sync_camera"), patch("app.api.cameras._config_push"):
        camera = client.post(
            "/api/v1/cameras",
            json={
                "name": "Probe-CAM",
                "source_id": source["id"],
                "main_path": "/vendor/high?x=01",
                "sub_path": "/vendor/low?x=02",
            },
            headers=h,
        ).json()
    fake = {
        "main": {"res": "1920x1080", "fps": 25.0, "codec": "h264"},
        "sub": None,
        "main_path": "/vendor/high?x=01",
        "sub_path": "/vendor/low?x=02",
    }
    with patch("app.api.probe.probe_exact", return_value=fake) as exact, patch(
        "app.api.probe.probe_camera"
    ) as discovery:
        response = client.post(
            "/api/v1/cameras/probe",
            json={"camera_id": camera["id"]},
            headers=h,
        )
    assert response.status_code == 200 and response.json() == fake
    assert exact.call_count == 1
    stream = exact.call_args.args[0]
    assert stream.host == "10.0.0.20"
    assert stream.main_path == "/vendor/high?x=01"
    assert not discovery.called


def test_generalized_import_reports_credential_update_and_orphan(client):
    from unittest.mock import patch

    h = _admin_headers(client)
    profile = client.post(
        "/api/v1/credential-profiles",
        json={"name": "import-profile", "username": "u", "secret_ref": "env:IMPORT_SECRET"},
        headers=h,
    ).json()
    source = client.post(
        "/api/v1/stream-sources",
        json={"name": "Import-NVR", "kind": "nvr", "host": "10.0.0.30"},
        headers=h,
    ).json()
    group = client.post(
        "/api/v1/location-groups",
        json={"name": "Gudang"},
        headers=h,
    ).json()
    with patch("app.api.cameras.sync_camera"), patch("app.api.cameras._config_push"):
        current = client.post(
            "/api/v1/cameras",
            json={
                "name": "old-name",
                "source_id": source["id"],
                "location_group_id": group["id"],
                "main_path": "/vendor/main",
                "sub_path": "/vendor/sub",
            },
            headers=h,
        ).json()
        client.post(
            "/api/v1/cameras",
            json={"name": "orphan", "source_id": source["id"], "main_path": "/vendor/orphan"},
            headers=h,
        )
    entry = {
        "name": "new-name",
        "source": "Import-NVR",
        "location_group": "Gudang",
        "credential_profile": "import-profile",
        "main_path": "/vendor/main",
        "sub_path": "/vendor/sub",
    }
    preview = client.post("/api/v1/cameras/import", json={"entries": [entry]}, headers=h)
    assert preview.status_code == 200
    planned = preview.json()
    assert planned["matched"] == 1
    assert planned["updated"] == 1
    assert planned["items"][0]["classification"] == "CREDENTIAL"
    assert planned["unmatched"] == []
    assert len(planned["orphans"]) == 1

    with patch("app.api.cameras.sync_camera"), patch("app.api.cameras._config_push"):
        applied = client.post(
            "/api/v1/cameras/import?apply=true",
            json={"entries": [entry]},
            headers=h,
        )
    assert applied.status_code == 200 and applied.json()["applied"] is True
    row = client.get(f"/api/v1/cameras/{current['id']}", headers=h).json()
    assert row["name"] == "new-name"
    assert row["credential_override_id"] == profile["id"]


def test_import_create_requires_explicit_authorization(client):
    from unittest.mock import patch

    h = _admin_headers(client)
    entry = {
        "name": "created-camera",
        "host": "10.0.0.40",
        "main_path": "/vendor/main",
        "sub_path": "/vendor/sub",
    }
    preview = client.post("/api/v1/cameras/import", json={"entries": [entry]}, headers=h)
    assert preview.status_code == 200
    assert preview.json()["items"][0]["classification"] == "CREATE"
    assert len(preview.json()["unmatched"]) == 1
    refused = client.post(
        "/api/v1/cameras/import?apply=true",
        json={"entries": [entry]},
        headers=h,
    )
    assert refused.status_code == 200 and refused.json()["applied"] is False

    with patch("app.api.cameras.sync_camera") as sync, patch("app.api.cameras._config_push") as config_push:
        applied = client.post(
            "/api/v1/cameras/import?apply=true&allow_create=true",
            json={"entries": [entry]},
            headers=h,
        )
    assert applied.status_code == 200
    assert applied.json()["applied"] is True and applied.json()["created"] == 1
    assert sync.call_count == 1
    assert config_push.call_count == 1


def test_import_unknown_source_is_unresolved(client):
    h = _admin_headers(client)
    entry = {
        "name": "unknown-source-camera",
        "source": "does-not-exist",
        "main_path": "/vendor/main",
    }
    result = client.post("/api/v1/cameras/import", json={"entries": [entry]}, headers=h)
    assert result.status_code == 200
    body = result.json()
    assert body["items"][0]["classification"] == "NEW SOURCE"
    assert body["unmatched"]
    assert any("NEW SOURCE" in error for error in body["errors"])


def test_source_detach_clears_inherited_override_and_rejects_conflicting_paths(client):
    from unittest.mock import patch

    h = _admin_headers(client)
    profile = client.post(
        "/api/v1/credential-profiles",
        json={"name": "override", "secret_ref": "env:CAMERA_OVERRIDE"},
        headers=h,
    ).json()
    source = client.post(
        "/api/v1/stream-sources",
        json={"name": "NVR-detach", "host": "10.0.0.50"},
        headers=h,
    ).json()
    with patch("app.api.cameras.sync_camera"), patch("app.api.cameras._config_push"):
        camera = client.post(
            "/api/v1/cameras",
            json={
                "name": "detach-camera",
                "source_id": source["id"],
                "credential_override_id": profile["id"],
                "main_path": "/main",
            },
            headers=h,
        ).json()
        detached = client.patch(
            f"/api/v1/cameras/{camera['id']}",
            json={"source_id": None},
            headers=h,
        )
        conflict = client.patch(
            f"/api/v1/cameras/{camera['id']}",
            json={"main_path": "/main-a", "rtsp_main": "/main-b"},
            headers=h,
        )
    assert detached.status_code == 200
    assert detached.json()["source_id"] is None
    assert detached.json()["credential_override_id"] is None
    assert conflict.status_code == 422


def test_import_rejects_conflicting_selectors_and_existing_create_name(client):
    h = _admin_headers(client)
    source_a = client.post(
        "/api/v1/stream-sources",
        json={"name": "source-a", "host": "10.0.0.61"},
        headers=h,
    ).json()
    client.post(
        "/api/v1/stream-sources",
        json={"name": "source-b", "host": "10.0.0.62"},
        headers=h,
    )
    client.post(
        "/api/v1/cameras",
        json={"name": "existing-name", "host": "10.0.0.70"},
        headers=h,
    )
    mismatch = client.post(
        "/api/v1/cameras/import",
        json={"entries": [{"name": "mismatch", "source_id": source_a["id"], "source": "source-b", "main_path": "/main"}]},
        headers=h,
    ).json()
    duplicate = client.post(
        "/api/v1/cameras/import?apply=true&allow_create=true",
        json={"entries": [{"name": "existing-name", "host": "10.0.0.71", "main_path": "/main"}]},
        headers=h,
    ).json()
    assert mismatch["errors"] and mismatch["applied"] is False
    assert duplicate["items"][0]["classification"] == "DUPLICATE"
    assert duplicate["applied"] is False


def test_source_suggestion_probe_uses_resolved_credentials(client, monkeypatch):
    from unittest.mock import patch

    h = _admin_headers(client)
    monkeypatch.setenv("CAMERA_PROBE_SECRET", "probe-pass")
    profile = client.post(
        "/api/v1/credential-profiles",
        json={"name": "probe-profile", "username": "probe-user", "secret_ref": "env:CAMERA_PROBE_SECRET"},
        headers=h,
    ).json()
    source = client.post(
        "/api/v1/stream-sources",
        json={"name": "probe-source", "host": "10.0.0.80", "default_credential_id": profile["id"]},
        headers=h,
    ).json()
    result = {"main": None, "sub": None, "main_path": None, "sub_path": None}
    with patch("app.api.probe.probe_camera", return_value=result) as suggestion:
        response = client.post(
            "/api/v1/cameras/probe",
            json={"source_id": source["id"]},
            headers=h,
        )
    assert response.status_code == 200
    assert suggestion.call_args.args == ("10.0.0.80", "probe-user", "probe-pass")


def test_location_text_auto_groups(client):
    h = _admin_headers(client)
    r1 = client.post("/api/v1/cameras", json={"name": "camA", "host": "1.2.3.4", "location": "Lantai 1 - Lorong"}, headers=h)
    r2 = client.post("/api/v1/cameras", json={"name": "camB", "host": "1.2.3.5", "location": "Lantai 1 - Lorong"}, headers=h)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["location_group_id"] == r2.json()["location_group_id"]
    assert r1.json()["location_group"]["name"] == "Lantai 1 - Lorong"
    # ubah lokasi → grup ikut terderivasi ulang
    r3 = client.patch(f"/api/v1/cameras/{r1.json()['id']}", json={"location": "Gudang"}, headers=h)
    assert r3.json()["location_group"]["name"] == "Gudang"
    assert r3.json()["location_group_id"] != r1.json()["location_group_id"]


def test_scan_camera_endpoint(client, monkeypatch):
    from unittest.mock import patch
    h = _admin_headers(client)
    assert client.post("/api/v1/cameras/scan", json={"host": "1.2.3.4"}).status_code == 401
    fake = [{"channel": 1, "main": {"res": "1920x1080", "fps": 25.0, "codec": "h264"},
             "sub": {"res": "640x480", "fps": 25.0, "codec": "h264"},
             "main_path": "/Streaming/Channels/101", "sub_path": "/Streaming/Channels/102"}]
    with patch("app.api.probe.scan_camera_channels", return_value=fake) as scan:
        r = client.post("/api/v1/cameras/scan", json={"host": "192.168.2.184"}, headers=h)
    assert r.status_code == 200 and r.json() == {"streams": fake}
    assert scan.call_args.kwargs["max_channel"] == 32


def test_alert_camera_nullable_allows_camera_delete(client, db):
    h = _admin_headers(client)
    cam = client.post("/api/v1/cameras", json={"name": "camA", "host": "1.2.3.4"}, headers=h).json()
    from datetime import datetime, timezone
    from app.models.event import Event
    from app.models.alert import Alert
    ev = Event(type="intrusion", ts_event=datetime.now(timezone.utc), camera_id=cam["id"])
    db.add(ev)
    db.flush()
    db.add(Alert(camera_id=cam["id"], event_id=ev.id, type="intrusion", severity="critical", status="new"))
    db.commit()
    assert client.delete(f"/api/v1/cameras/{cam['id']}", headers=h).status_code == 200
    assert db.query(Alert).count() == 1 and db.query(Alert).first().camera_id is None
