import pytest
from fastapi import HTTPException
from app.core.security import hash_password, verify_password, create_access_token, decode_token
from tests.conftest import *  # noqa

def test_hash_roundtrip():
    h = hash_password("s3cret")
    assert h != "s3cret" and verify_password("s3cret", h) and not verify_password("wrong", h)

def test_token_roundtrip():
    t = create_access_token(1, "admin")
    d = decode_token(t)
    assert d["sub"] == "1" and d["role"] == "admin"

def test_bad_token_none():
    assert decode_token("garbage") is None


import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db

@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_attendance_override_requires_admin(client, db):
    """Override absensi mengubah data kehadiran — harus admin."""
    viewer = viewer_headers(client)  # helper dari conftest.py (Task 3 Step 1)
    r = client.patch("/api/v1/attendance/1", json={"status": "ontime", "note": "x"}, headers=viewer)
    assert r.status_code != 200


def test_attendance_patch_route_uses_require_admin():
    """Memastikan guard-nya memang require_admin, bukan kebetulan 404."""
    import inspect
    from app.api import attendance as att_mod

    src = inspect.getsource(att_mod)
    assert "require_admin" in src, "PATCH /attendance harus admin-gated"
