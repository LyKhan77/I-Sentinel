import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from app.core.db import Base

@pytest.fixture
def db():
    # StaticPool + check_same_thread=False: one shared in-memory DB across threads (TestClient portal thread)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def viewer_headers(client):
    """Buat user viewer lewat API admin, lalu login sebagai dia.

    Lewat API (bukan langsung ke DB) supaya helper ini tidak perlu tahu soal
    fixture db. Tiap test punya DB in-memory sendiri, jadi user 'vw' selalu baru.
    """
    client.post(
        "/api/v1/users",
        json={"username": "vw", "password": "pw12345", "role": "viewer"},
        headers=admin_headers(client),
    )
    tok = client.post("/api/v1/auth/login", json={"username": "vw", "password": "pw12345"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(autouse=True)
def _reset_login_ratelimit():
    """Penghitung rate-limit login bersifat level-modul; bersihkan tiap test."""
    from app.api import auth as auth_mod
    auth_mod._FAILURES.clear()
    yield
    auth_mod._FAILURES.clear()
