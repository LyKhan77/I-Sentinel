from app.core.config import Settings
from app.core.db import engine_kwargs


def test_pool_defaults_are_sized_for_many_tv_windows():
    s = Settings()
    assert (s.db_pool_size, s.db_max_overflow, s.db_pool_timeout) == (20, 20, 10.0)


def test_pool_env_override(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "7")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "3")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "2.5")
    s = Settings()
    assert (s.db_pool_size, s.db_max_overflow, s.db_pool_timeout) == (7, 3, 2.5)


def test_engine_kwargs_postgres_uses_pool_settings():
    s = Settings(db_pool_size=9, db_max_overflow=4, db_pool_timeout=3.0)
    kw = engine_kwargs("postgresql+psycopg://u:p@h/db", s)
    assert kw == {"pool_pre_ping": True, "pool_size": 9, "max_overflow": 4, "pool_timeout": 3.0}


def test_engine_kwargs_sqlite_has_no_pool_args():
    # SQLite (tes) memakai pool sendiri; pool_size/max_overflow tidak berlaku
    assert engine_kwargs("sqlite://", Settings()) == {"pool_pre_ping": True}
