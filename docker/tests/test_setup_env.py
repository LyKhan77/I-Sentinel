"""Run setup's real env-only path without Docker or server data."""
import os
from pathlib import Path
import re
import shlex
import subprocess

DOCKER = Path(__file__).resolve().parents[1]


def values(path):
    return {line.split("=", 1)[0]: (shlex.split(line.split("=", 1)[1]) or [""])[0]
            for line in path.read_text().splitlines() if line and not line.startswith("#")}


def invoke(tmp_path, *args, ip="192.0.2.10"):
    env = {**os.environ, "DATA_DIR": str(tmp_path / "data with spaces"),
           "ENV_FILE": str(tmp_path / "stack.env"), "GO2RTC_PUBLIC_HOST": ip}
    result = subprocess.run(["bash", str(DOCKER / "setup.sh"), "--env-only", *args],
                            env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return result


def test_env_created_with_strong_secrets_and_0600(tmp_path):
    invoke(tmp_path)
    path = tmp_path / "stack.env"
    assert path.stat().st_mode & 0o777 == 0o600
    env = values(path)
    assert values(DOCKER / ".env.example").keys() <= env.keys()
    for key in ["JWT_SECRET", "NODE_API_KEY", "ADMIN_PASSWORD", "MQTT_PASSWORD", "POSTGRES_PASSWORD"]:
        assert re.fullmatch(r"[0-9a-f]{32,}", env[key]), key
    assert len({env[key] for key in ["JWT_SECRET", "NODE_API_KEY", "ADMIN_PASSWORD", "MQTT_PASSWORD", "POSTGRES_PASSWORD"]}) == 5


def test_rerun_keeps_env_byte_identical(tmp_path):
    invoke(tmp_path)
    before = (tmp_path / "stack.env").read_bytes()
    invoke(tmp_path, ip="192.0.2.11")
    assert (tmp_path / "stack.env").read_bytes() == before


def test_go2rtc_yaml_rendered_once_0600(tmp_path):
    invoke(tmp_path)
    path = tmp_path / "data with spaces/go2rtc/go2rtc.yaml"
    assert "192.0.2.10:7703" in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    path.write_text(path.read_text() + "streams: {test: 'rtsp://placeholder:7705/test'}\n")
    before = path.read_bytes()
    invoke(tmp_path, ip="192.0.2.11")
    assert path.read_bytes() == before


def test_rehearse_disables_vision_profile(tmp_path):
    invoke(tmp_path, "--rehearse")
    assert values(tmp_path / "stack.env")["COMPOSE_PROFILES"] == ""


def test_default_enables_vision_profile(tmp_path):
    invoke(tmp_path)
    assert values(tmp_path / "stack.env")["COMPOSE_PROFILES"] == "vision"


def test_data_dirs_created(tmp_path):
    invoke(tmp_path)
    for name in ["api", "vision", "models", "go2rtc", "mosquitto/data", "secrets"]:
        assert (tmp_path / "data with spaces" / name).is_dir()


def test_admin_credentials_printed_only_when_env_is_created(tmp_path):
    first = invoke(tmp_path)
    env = values(tmp_path / "stack.env")
    assert f"ADMIN_USERNAME={env['ADMIN_USERNAME']}" in first.stdout
    assert f"ADMIN_PASSWORD={env['ADMIN_PASSWORD']}" in first.stdout
    second = invoke(tmp_path)
    assert env["ADMIN_PASSWORD"] not in second.stdout + second.stderr


def test_env_only_never_calls_docker_and_keeps_passwd(tmp_path, monkeypatch):
    fake = tmp_path / "docker"
    fake.write_text('#!/usr/bin/env bash\necho called >> "$DOCKER_CALLS"\nexit 99\n')
    fake.chmod(0o755)
    calls = tmp_path / "calls"
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("DOCKER_CALLS", str(calls))
    invoke(tmp_path)
    passwd = tmp_path / "data with spaces/mosquitto/passwd"
    passwd.write_text("existing-placeholder-hash\n")
    invoke(tmp_path)
    assert passwd.read_text() == "existing-placeholder-hash\n"
    assert not calls.exists()


def test_rerun_uses_existing_data_dir_not_override(tmp_path, monkeypatch):
    invoke(tmp_path)
    original = tmp_path / "data with spaces/go2rtc/go2rtc.yaml"
    before = original.read_bytes()
    elsewhere = tmp_path / "not-used"
    result = subprocess.run(["bash", str(DOCKER / "setup.sh"), "--env-only"],
                            env={**os.environ, "DATA_DIR": str(elsewhere), "ENV_FILE": str(tmp_path / "stack.env")},
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert not elsewhere.exists()
    assert original.read_bytes() == before


def test_existing_env_missing_key_aborts(tmp_path):
    invoke(tmp_path)
    path = tmp_path / "stack.env"
    path.write_text("".join(line for line in path.read_text().splitlines(keepends=True)
                            if not line.startswith("VISION_NODE_ID=")))
    result = subprocess.run(["bash", str(DOCKER / "setup.sh"), "--env-only"],
                            env={**os.environ, "ENV_FILE": str(path),
                                 "DATA_DIR": str(tmp_path / "data with spaces"), "GO2RTC_PUBLIC_HOST": "192.0.2.10"},
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert "Missing environment keys: VISION_NODE_ID" in result.stderr
