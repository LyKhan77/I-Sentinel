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
        json={"username": "viewer", "password": "rahasia123", "role": "viewer"},
        headers=admin_headers(client),
    )
    tok = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "rahasia123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(autouse=True)
def _reset_login_ratelimit():
    """Penghitung rate-limit login bersifat level-modul; bersihkan tiap test."""
    from app.api import auth as auth_mod
    auth_mod._FAILURES.clear()
    yield
    auth_mod._FAILURES.clear()


@pytest.fixture(autouse=True)
def _quiet_node_monitor(monkeypatch):
    """Monitor node latar tidak boleh menyentuh DB nyata selama tes (interval panjang)."""
    from app.services import node_health
    monkeypatch.setattr(node_health.monitor, "interval_s", 3600)


@pytest.fixture(autouse=True)
def _quiet_attendance_closer(monkeypatch):
    """Penutup hari latar tidak boleh menyentuh DB nyata selama tes."""
    from app.services import attendance
    monkeypatch.setattr(attendance.closer, "interval_s", 3600)
    monkeypatch.setattr(attendance.closer, "run_on_start", False)


@pytest.fixture(autouse=True)
def _quiet_history():
    """Bucket riwayat di memori modul: kosongkan antar tes; sampler latar tidak boleh menyentuh DB nyata."""
    from app.services import monitoring_history
    monitoring_history.reset()
    old = monitoring_history.sampler.interval_s
    monitoring_history.sampler.interval_s = 3600
    yield
    monitoring_history.sampler.interval_s = old
    monitoring_history.reset()


@pytest.fixture(autouse=True)
def _isolated_secret_store(tmp_path, monkeypatch):
    """Tes tidak pernah membaca/menulis file rahasia asli di ~/.isentinel."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "camera_secrets_file", str(tmp_path / "secrets" / "store.json"))


@pytest.fixture(autouse=True)
def _no_external_sockets(monkeypatch):
    """Keep the test suite independent of live TCP services."""
    import socket
    original = socket.socket.connect

    def fake_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise OSError("External TCP is disabled in tests")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", fake_connect)


@pytest.fixture(autouse=True)
def _quiet_app_consumer(monkeypatch):
    """Fake the app-owned MQTT lifecycle; unit tests still use the real consumer class."""
    from app import main

    class FakeConsumer:
        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(main, "EventConsumer", FakeConsumer)
