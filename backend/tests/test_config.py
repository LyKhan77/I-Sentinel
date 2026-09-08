import os
from app.core.config import Settings

def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    s = Settings()
    assert s.jwt_algorithm == "HS256"
    assert s.access_token_expire_min == 480
    assert s.retention_days == 30
    assert s.storage_root == "/data/isentinel"
