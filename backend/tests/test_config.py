from app.core.config import Settings

def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    s = Settings()
    assert s.jwt_algorithm == "HS256"
    assert s.access_token_expire_min == 2880
    assert s.retention_days == 30
    assert s.storage_root == "/data/isentinel"


def test_llm_defaults_and_env_json(monkeypatch):
    s = Settings()
    defaults = {
        "llm_enabled": False, "llm_api_url": "", "llm_api_key": "", "llm_model": "",
        "llm_extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        "llm_max_tokens": 1000, "llm_timeout_caption_s": 60, "llm_timeout_ask_s": 120,
        "llm_concurrency": 2, "llm_ask_rate_per_min": 6,
        "llm_caption_min_interval_s": 60, "ai_queue_max": 100,
    }
    for key, value in defaults.items():
        assert getattr(s, key) == value
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"a":1}')
    assert Settings().llm_extra_body == {"a": 1}
