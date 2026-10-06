"""Runtime LLM settings, validation, and credential-safe mock connection checks."""
from copy import deepcopy
import json

import httpx
import pytest

from app.core.config import settings
from app.models.setting import Setting
from app.services import secret_store


@pytest.fixture
def config(db, monkeypatch, tmp_path):
    from app.services import llm_config
    snapshot = {name: deepcopy(getattr(settings, "llm_" + name)) for name in (*llm_config.FIELDS, "api_key")}
    original_overrides = set(llm_config._overridden)
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "camera_secrets_file", str(tmp_path / "secrets" / "store.json"))
    base = deepcopy(llm_config._BASE)
    base.update(enabled=False, api_url="", model="", api_key="")
    monkeypatch.setattr(llm_config, "_BASE", base)
    monkeypatch.setattr(llm_config, "_ENV_SET", set())
    llm_config._overridden.clear()
    yield llm_config
    row = db.get(Setting, "llm")
    if row is not None:
        db.delete(row)
        db.commit()
    secret_store.delete("llm_api_key")
    llm_config.apply(db)
    for name, value in snapshot.items():
        setattr(settings, "llm_" + name, value)
    llm_config._overridden.clear()
    llm_config._overridden.update(original_overrides)


def test_precedence_env_db_clear(config, db):
    config.save(db, {"model": "m1", "max_tokens": 500, "enabled": False})
    assert settings.llm_model == "m1"
    assert config.view(db)["sources"]["model"] == "db"
    config.save(db, {"model": None, "max_tokens": None, "enabled": None})
    for name in ("model", "max_tokens", "enabled"):
        assert getattr(settings, "llm_" + name) == config._BASE[name]
        assert config.view(db)["sources"][name] == "default"
        assert name not in db.get(Setting, "llm").value


def test_key_only_in_secret_store(config, db):
    config.save(db, {}, api_key="sk-secret")
    assert secret_store.get("llm_api_key") == "sk-secret"
    assert settings.llm_api_key == "sk-secret"
    assert config.view(db)["key_configured"] is True
    assert "sk-secret" not in json.dumps(config.view(db))
    assert "api_key" not in db.get(Setting, "llm").value
    assert "sk-secret" not in json.dumps(db.get(Setting, "llm").value)
    config.save(db, {}, clear_api_key=True)
    assert config.view(db)["key_configured"] is False
    assert settings.llm_api_key == config._BASE["api_key"]


INVALID = [
    {"api_url": "ftp://x"}, {"api_url": "http://"}, {"api_url": "https://" + "x" * 250},
    {"model": "m" * 65}, {"max_tokens": 99}, {"max_tokens": 8001},
    {"max_tokens": True}, {"max_tokens": 100.5},
    {"timeout_caption_s": 4}, {"timeout_caption_s": 601},
    {"timeout_ask_s": 4}, {"timeout_ask_s": 601},
    {"ask_rate_per_min": 0}, {"ask_rate_per_min": 61},
    {"caption_min_interval_s": -1}, {"caption_min_interval_s": 3601},
    {"extra_body": []}, {"extra_body": {"messages": []}}, {"extra_body": {"model": "m"}},
    {"extra_body": {"max_tokens": 100}}, {"extra_body": {"stream": True}},
    {"extra_body": {"x": "x" * 2000}}, {"extra_body": {"x": float("nan")}},
    {"enabled": True}, {"enabled": "yes"}, {"api_key": "sk-in-db"},
]


@pytest.mark.parametrize("values", INVALID)
def test_invalid_save_has_no_side_effects(config, db, values, monkeypatch):
    config.save(db, {"model": "before"}, api_key="sk-secret")
    before = deepcopy(db.get(Setting, "llm").value)
    writes = []
    monkeypatch.setattr(secret_store, "put", lambda *args: writes.append(args))
    monkeypatch.setattr(secret_store, "delete", lambda *args: writes.append(args))
    with pytest.raises(config.ConfigError):
        config.save(db, values, api_key="sk-new")
    assert writes == []
    assert db.get(Setting, "llm").value == before
    assert secret_store.get("llm_api_key") == "sk-secret"
    assert settings.llm_model == "before"


def test_apply_restores_base_when_row_removed(config, db):
    config.save(db, {"model": "override"})
    db.delete(db.get(Setting, "llm"))
    db.commit()
    config.apply(db)
    assert settings.llm_model == config._BASE["model"]


def test_apply_is_noop_when_nothing_overridden(config, db, monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_model", "patched")
    config.apply(db)
    assert settings.llm_enabled is True and settings.llm_model == "patched"


def test_sources_env(config, db):
    config._BASE["model"] = "env-model"
    config._ENV_SET.add("llm_model")
    assert config.view(db)["model"] == "env-model"
    assert config.view(db)["sources"]["model"] == "env"
    config.save(db, {"model": "db-model"})
    config.save(db, {"model": None})
    assert settings.llm_model == "env-model"
    assert config.view(db)["sources"]["model"] == "env"


def test_clear_key_restores_env(config, db):
    config._BASE["api_key"] = "sk-env"
    config.save(db, {}, api_key="sk-secret")
    config.save(db, {}, clear_api_key=True)
    assert settings.llm_api_key == "sk-env"
    assert config.view(db)["key_configured"] is True


def test_valid_boundaries(config, db):
    config.save(db, {"enabled": True, "api_url": "https://llm.test/v1", "model": "m" * 64,
                     "max_tokens": 100, "timeout_caption_s": 5, "timeout_ask_s": 600,
                     "ask_rate_per_min": 60, "caption_min_interval_s": 0, "extra_body": {}})
    config.save(db, {"max_tokens": 8000, "caption_min_interval_s": 3600, "ask_rate_per_min": 1})
    assert settings.llm_enabled is True and settings.llm_max_tokens == 8000
    assert config.view(db)["restart_only"] == {"concurrency": settings.llm_concurrency, "queue_max": settings.ai_queue_max}


def completion():
    return httpx.Response(200, json={"model": "form-model", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})


@pytest.mark.parametrize("mode", ["ok", "vision_rejected", "timeout", "reflected"])
def test_connection_vision_and_errors(config, db, mode, monkeypatch):
    config.save(db, {}, api_key="sk-secret")
    db.delete(db.get(Setting, "llm"))
    db.commit()
    snapshot = {field: deepcopy(getattr(settings, "llm_" + field)) for field in config.FIELDS}
    requests = []

    def handler(req):
        requests.append(req)
        assert req.headers["Authorization"] == "Bearer sk-form"
        assert req.extensions["timeout"]["read"] == 30
        body = json.loads(req.content)
        assert body["model"] == "form-model"
        if mode == "timeout":
            raise httpx.ReadTimeout("sk-form sk-secret", request=req)
        if mode == "reflected":
            return httpx.Response(400, text="echo sk-form sk-secret")
        if len(requests) == 2 and mode == "vision_rejected":
            return httpx.Response(400)
        return completion()

    def no_slot(*args, **kwargs):
        pytest.fail("Admin connection tests must not lease worker slots")

    monkeypatch.setattr(config.llm_client, "slot", no_slot)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = config.test_connection(db, {"api_url": "https://form.test/v1", "model": "form-model"}, "sk-form", client=client)
    assert result["ok"] is (mode in ("ok", "vision_rejected"))
    assert result["vision_ok"] is (mode == "ok")
    assert "sk-form" not in json.dumps(result) and "sk-secret" not in json.dumps(result)
    assert db.get(Setting, "llm") is None
    assert snapshot == {field: getattr(settings, "llm_" + field) for field in config.FIELDS}
    if mode == "ok":
        from base64 import b64decode
        from io import BytesIO
        from PIL import Image
        parts = json.loads(requests[1].content)["messages"][0]["content"]
        image = Image.open(BytesIO(b64decode(parts[1]["image_url"]["url"].split(",")[1])))
        assert image.format == "JPEG" and image.size == (64, 64)
        assert isinstance(result["latency_ms"], int)


@pytest.mark.parametrize("key", [None, ""])
def test_connection_empty_form_key_uses_stored_key(config, db, key):
    config.save(db, {}, api_key="sk-secret")

    def handler(req):
        assert req.headers["Authorization"] == "Bearer sk-secret"
        return completion()

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = config.test_connection(db, {"api_url": "https://llm.test/v1", "model": "m"}, key, client=client)
    assert result["ok"] is True


def test_connection_redacts_form_and_stored_error(config, db, monkeypatch):
    config.save(db, {}, api_key="sk-secret")

    def fail(*args, **kwargs):
        raise config.llm_client.LlmError("echo sk-form sk-secret")

    monkeypatch.setattr(config.llm_client, "chat", fail)
    result = config.test_connection(db, {"api_url": "https://llm.test/v1", "model": "m"}, "sk-form")
    assert result["ok"] is False
    assert result["error"] == "echo [redacted] [redacted]"


def test_connection_invalid_form_returns_failure(config, db):
    result = config.test_connection(db, {"max_tokens": 99}, "sk-form")
    assert result["ok"] is False and result["error"]
    assert db.get(Setting, "llm") is None


def test_api_key_is_stripped_before_storage_and_use(config, db):
    """Kunci hasil tempel berspasi/newline ditolak h11 sebagai header ilegal; harus dibersihkan."""
    config.save(db, {}, api_key="  sk-pasted\n")
    assert secret_store.get("llm_api_key") == "sk-pasted"
    assert settings.llm_api_key == "sk-pasted"

    def handler(req):
        assert req.headers["Authorization"] == "Bearer sk-form"
        return completion()

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = config.test_connection(db, {"api_url": "https://llm.test/v1", "model": "m"}, " sk-form\t", client=client)
    assert result["ok"] is True


@pytest.mark.parametrize("bad", ["   ", "sk with space", "sk\nnewline", "k" * 513])
def test_invalid_api_key_is_rejected_without_side_effects(config, db, bad):
    config.save(db, {}, api_key="sk-old")
    before = settings.llm_api_key
    with pytest.raises(config.ConfigError) as exc:
        config.save(db, {"model": "m2"}, api_key=bad)
    assert bad.strip() not in str(exc.value) or not bad.strip()
    assert secret_store.get("llm_api_key") == "sk-old" and settings.llm_api_key == before
    assert config.view(db)["model"] != "m2"
    result = config.test_connection(db, {"api_url": "https://llm.test/v1", "model": "m"}, bad)
    assert result["ok"] is False and result["error"]
    assert not bad.strip() or bad.strip() not in result["error"]


@pytest.mark.parametrize("url", ["http://user:pw@llm.test/v1", "https://token@llm.test/v1"])
def test_api_url_with_credentials_is_rejected(config, db, url):
    """Kredensial di URL akan tersimpan plaintext di tabel setting dan dikembalikan oleh GET."""
    with pytest.raises(config.ConfigError, match="credentials") as exc:
        config.save(db, {"api_url": url}, api_key="sk-new")
    assert "pw" not in str(exc.value) and "token@" not in str(exc.value)
    assert db.get(Setting, "llm") is None and secret_store.get("llm_api_key") is None


def test_unreadable_secret_store_keeps_db_overrides_and_view(config, db, monkeypatch):
    """File rahasia rusak/izin salah tidak boleh membuang override DB atau membuat halaman admin 500."""
    config.save(db, {"model": "dari-db"})
    monkeypatch.setattr(settings, "llm_model", "")
    config._overridden.clear()

    def broken(name):
        raise secret_store.SecretStoreError("unreadable")

    monkeypatch.setattr(secret_store, "get", broken)
    config.apply(db)
    assert settings.llm_model == "dari-db"
    view = config.view(db)
    assert view["model"] == "dari-db" and view["key_configured"] is False


def test_key_source_distinguishes_stored_env_and_none(config, db, monkeypatch):
    """Kunci dari env tidak boleh terbaca 'tersimpan': hapus kunci hanya menghapus entri secret_store."""
    assert config.view(db)["key_source"] == "none" and config.view(db)["key_configured"] is False
    monkeypatch.setitem(config._BASE, "api_key", "sk-env")
    assert config.view(db)["key_source"] == "env" and config.view(db)["key_configured"] is True
    config.save(db, {}, api_key="sk-db")
    assert config.view(db)["key_source"] == "db"
    config.save(db, {}, clear_api_key=True)
    assert config.view(db)["key_source"] == "env"
    assert "sk-env" not in json.dumps(config.view(db))


def test_apply_and_current_connection_share_one_lock(config, db):
    """apply() menulis settings field demi field; pembacaan Connection tidak boleh menyelinap di tengahnya."""
    import threading
    lock = config.llm_client.config_lock
    applied, read = threading.Event(), threading.Event()
    with lock:
        threading.Thread(target=lambda: (config.apply(db), applied.set()), daemon=True).start()
        threading.Thread(target=lambda: (config.llm_client.current_connection(), read.set()), daemon=True).start()
        assert not applied.wait(0.2) and not read.wait(0.2)
    assert applied.wait(2) and read.wait(2)
