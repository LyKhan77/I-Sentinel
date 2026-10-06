"""Validate resolved Compose contracts without a running Docker daemon."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

DOCKER = Path(__file__).resolve().parents[1]


def config(vision=True, env=None):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose CLI unavailable")
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode:
        pytest.skip("Docker Compose CLI unavailable")
    args = ["docker", "compose", "-f", str(DOCKER / "compose.yml"),
            "--env-file", str(DOCKER / ".env.example")]
    if vision:
        args += ["--profile", "vision"]
    result = subprocess.run(args + ["config", "--format", "json"],
                            env={**os.environ, "COMPOSE_PROFILES": "", **(env or {})}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def services():
    return config()["services"]


def test_only_fixed_lan_ports_published(services):
    ports = {(str(port["published"]), port.get("protocol", "tcp"), int(port["target"]))
             for service in services.values() for port in service.get("ports", [])}
    assert ports == {("7700", "tcp", 7700), ("7701", "tcp", 7701), ("7702", "tcp", 7702),
                     ("7703", "tcp", 7703), ("7703", "udp", 7703), ("7704", "tcp", 7704)}


def test_vision_is_opt_in_profile(services):
    assert services["vision"]["profiles"] == ["vision"]
    assert "vision" not in config(False)["services"]


def test_service_urls_include_explicit_port(services):
    for service in services.values():
        for key, value in service.get("environment", {}).items():
            if key.endswith("_URL") and value:
                assert re.search(r":\d+(?:/|$)", str(value)), (key, value)


def test_postgres_uses_named_volume(services):
    assert any(v["type"] == "volume" and v["source"] == "pgdata" for v in services["postgres"]["volumes"])
    assert "pgdata" in config()["volumes"]


def test_restart_and_bounded_logs(services):
    for service in services.values():
        assert service["restart"] == "unless-stopped"
        assert service["logging"]["driver"] == "json-file"
        assert service["logging"]["options"] == {"max-size": "10m", "max-file": "5"}


def test_core_services_have_healthchecks(services):
    for name in ["api", "postgres", "mosquitto", "go2rtc", "web"]:
        assert services[name]["healthcheck"]["test"]


def test_only_vision_requests_gpu(services):
    devices = services["vision"]["deploy"]["resources"]["reservations"]["devices"]
    assert devices == [{"capabilities": ["gpu"], "count": -1, "driver": "nvidia"}]
    assert "deploy" not in services["api"]


def test_api_password_only_in_database_url(services):
    environment = services["api"]["environment"]
    assert "POSTGRES_PASSWORD" not in environment
    assert "@postgres:5432/isentinel" in environment["DATABASE_URL"]


def test_uid_and_persistent_go2rtc(services):
    for name in ["api", "vision", "retention", "mosquitto", "go2rtc"]:
        assert services[name]["user"] == "1000:1000"
    assert "user" not in services["postgres"]
    assert "user" not in services["web"]
    mount = next(v for v in services["go2rtc"]["volumes"] if v["target"] == "/config")
    assert mount["type"] == "bind"
    assert not mount.get("read_only", False)


def test_api_receives_camera_credentials_from_optional_env_file(tmp_path):
    """CAM_* dan CAMERA_CREDENTIAL_* dibaca kode dari environment (probe, stream_endpoint)."""
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/camera.env").write_text(
        "CAM_USERNAME=admin\nCAM_PASSWORD='p#ss1'\nCAMERA_CREDENTIAL_NVR_A='x1'\n")
    environment = config(env={"DATA_DIR": str(tmp_path)})["services"]["api"]["environment"]
    assert environment["CAM_USERNAME"] == "admin"
    assert environment["CAM_PASSWORD"] == "p#ss1"
    assert environment["CAMERA_CREDENTIAL_NVR_A"] == "x1"


def test_camera_credentials_reach_only_api(tmp_path):
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/camera.env").write_text("CAM_PASSWORD=secret-value\n")
    services = config(env={"DATA_DIR": str(tmp_path)})["services"]
    for name, service in services.items():
        has = "CAM_PASSWORD" in service.get("environment", {})
        assert has == (name == "api"), name


def test_vision_waits_for_mqtt_config_instead_of_exiting(services):
    """Tanpa kamera statis, node yang tidak menunggu config keluar dan restart-loop."""
    assert services["vision"]["environment"]["VISION_AWAIT_CONFIG"] == "true"
    assert not services["vision"]["environment"].get("VISION_CAMERAS_JSON")



def test_api_receives_llm_settings_from_optional_env_file(tmp_path):
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/llm.env").write_text("LLM_ENABLED=true\nLLM_API_KEY='k#1'\n")
    environment = config(env={"DATA_DIR": str(tmp_path)})["services"]["api"]["environment"]
    assert environment["LLM_ENABLED"] == "true" and environment["LLM_API_KEY"] == "k#1"


def test_llm_key_reaches_only_api(tmp_path):
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/llm.env").write_text("LLM_API_KEY='synthetic'\n")
    for name, service in config(env={"DATA_DIR": str(tmp_path)})["services"].items():
        assert ("LLM_API_KEY" in service.get("environment", {})) == (name == "api")
