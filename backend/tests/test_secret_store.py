import os
import stat

import pytest

from app.services import secret_store
from app.services.secret_store import SecretStoreError
from app.services.stream_endpoint import StreamEndpointError, _secret


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(secret_store.settings, "storage_root", str(tmp_path / "media"))
    path = tmp_path / "secrets" / "camera-secrets.json"
    monkeypatch.setattr(secret_store.settings, "camera_secrets_file", str(path))
    return path


def test_put_get_delete_roundtrip(store):
    secret_store.put("cred_1", "p@ss:w/rd#1")
    assert secret_store.get("cred_1") == "p@ss:w/rd#1"
    secret_store.delete("cred_1")
    assert secret_store.get("cred_1") is None


def test_put_keeps_other_keys(store):
    secret_store.put("cred_1", "a")
    secret_store.put("cred_2", "b")
    assert (secret_store.get("cred_1"), secret_store.get("cred_2")) == ("a", "b")


def test_file_and_dir_are_owner_only(store):
    secret_store.put("cred_1", "x")
    assert stat.S_IMODE(os.stat(store).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(store.parent).st_mode) == 0o700


def test_missing_file_reads_as_empty(store):
    assert secret_store.get("cred_1") is None


def test_rejects_path_inside_storage_root(tmp_path, monkeypatch):
    monkeypatch.setattr(secret_store.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(secret_store.settings, "camera_secrets_file", str(tmp_path / "s.json"))
    with pytest.raises(SecretStoreError):
        secret_store.put("cred_1", "x")
    assert not (tmp_path / "s.json").exists()


def test_store_ref_resolves_through_stream_endpoint(store):
    secret_store.put("cred_7", "cam-pass")
    assert _secret("store:cred_7") == "cam-pass"
    with pytest.raises(StreamEndpointError, match="unavailable"):
        _secret("store:cred_missing")
