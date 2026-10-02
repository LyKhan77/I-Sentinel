"""Migration ordering and guards using fake host data, never a live migration."""
import os
from pathlib import Path
import shlex
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/migrate-from-host.sh"
PASSWORD = "fake-password-not-for-production"


def fixture_env(tmp_path):
    data = tmp_path / "docker-data"
    data.mkdir()
    host = tmp_path / "host-data"
    for folder in ["api", "vision"]:
        (host / folder).mkdir(parents=True)
    host_env = tmp_path / "host.env"
    host_env.write_text(f"DATABASE_URL=postgresql+psycopg://operator:{PASSWORD}@127.0.0.1:5432/old_db\n")
    env_file = tmp_path / "docker.env"
    env_file.write_text(f"DATA_DIR={shlex.quote(str(data))}\nCOMPOSE_PROFILES=\nVISION_NODE_ID=1\n")
    secrets = tmp_path / "camera-secrets.json"
    secrets.write_text("{}\n")
    engine = tmp_path / "yolo26s.engine"
    engine.write_bytes(b"placeholder")
    return {**os.environ, "ENV_FILE": str(env_file), "HOST_ENV_FILE": str(host_env),
            "HOST_DATA_ROOT": str(host), "HOST_SECRETS_FILE": str(secrets),
            "HOST_ENGINE": str(engine), "OLD_UNITS_CHECK": "skip", "DATA_DIR": str(data)}


def invoke(env, *args):
    return subprocess.run(["bash", str(SCRIPT), *args, "--dry-run"], env=env,
                          text=True, capture_output=True)


def test_rehearse_plan(tmp_path):
    env = fixture_env(tmp_path)
    result = invoke(env, "--rehearse")
    assert result.returncode == 0, result.stderr
    text = result.stdout
    steps = ["stop api retention", "pg_dump", "DROP", "CREATE", "psql -U isentinel -d isentinel", "rsync -a", "up -d"]
    indices = [text.index(step) for step in steps]
    assert indices == sorted(indices)
    assert "camera-secrets" not in text
    assert "COMPOSE_PROFILES=vision" not in text
    assert PASSWORD not in text + result.stderr
    assert "127.0.0.1:5432/old_db" in text
    assert not (Path(env["DATA_DIR"]) / ".cutover-done").exists()


def test_cutover_plan(tmp_path):
    env = fixture_env(tmp_path)
    before = Path(env["ENV_FILE"]).read_bytes()
    result = invoke(env, "--cutover")
    assert result.returncode == 0, result.stderr
    text = result.stdout
    assert "rsync -a --delete" in text
    assert str(Path(env["HOST_DATA_ROOT"]) / "api") in text
    assert str(Path(env["HOST_DATA_ROOT"]) / "vision") in text
    assert "camera-secrets.json" in text
    assert "chmod 600" in text
    assert "COMPOSE_PROFILES=vision" in text
    assert "up -d" in text
    assert PASSWORD not in text + result.stderr
    assert Path(env["ENV_FILE"]).read_bytes() == before
    assert not (Path(env["DATA_DIR"]) / ".cutover-done").exists()


def test_cutover_refuses_when_old_units_active(tmp_path):
    env = fixture_env(tmp_path)
    fake = tmp_path / "systemctl"
    fake.write_text('#!/usr/bin/env bash\necho active\nexit 0\n')
    fake.chmod(0o755)
    env.update(PATH=f"{tmp_path}:{os.environ['PATH']}", OLD_UNITS_CHECK="check")
    result = invoke(env, "--cutover")
    assert result.returncode != 0
    assert "active" in result.stderr
    assert "pg_dump" not in result.stdout
    assert "DROP" not in result.stdout


def test_cutover_refuses_second_run_without_force(tmp_path):
    env = fixture_env(tmp_path)
    (Path(env["DATA_DIR"]) / ".cutover-done").touch()
    result = invoke(env, "--cutover")
    assert result.returncode != 0
    assert "--force" in result.stderr
    assert "DROP" not in result.stdout
    assert invoke(env, "--cutover", "--force").returncode == 0


@pytest.mark.parametrize("args", [[], ["--rehearse", "--cutover"], ["--cutover", "--cutover"]])
def test_requires_exactly_one_mode(tmp_path, args):
    result = invoke(fixture_env(tmp_path), *args)
    assert result.returncode != 0
    assert "exactly one" in result.stderr


def test_rehearse_refuses_shared_data_root(tmp_path):
    env = fixture_env(tmp_path)
    Path(env["ENV_FILE"]).write_text(f"DATA_DIR={env['HOST_DATA_ROOT']}\nCOMPOSE_PROFILES=\nVISION_NODE_ID=1\n")
    result = invoke(env, "--rehearse")
    assert result.returncode != 0
    assert "separate" in result.stderr
    assert "pg_dump" not in result.stdout


def test_cutover_guard_fails_closed_when_systemctl_unavailable(tmp_path):
    env = fixture_env(tmp_path)
    fake = tmp_path / "systemctl"
    fake.write_text('#!/usr/bin/env bash\necho "Failed to connect to bus" >&2\nexit 1\n')
    fake.chmod(0o755)
    env.update(PATH=f"{tmp_path}:{os.environ['PATH']}", OLD_UNITS_CHECK="check")
    result = invoke(env, "--cutover")
    assert result.returncode != 0
    assert "DROP" not in result.stdout
    assert "Unable to verify" in result.stderr


def test_rehearse_refuses_existing_camera_secrets(tmp_path):
    env = fixture_env(tmp_path)
    target = Path(env["DATA_DIR"]) / "secrets/camera-secrets.json"
    target.parent.mkdir()
    target.write_text("{}")
    result = invoke(env, "--rehearse")
    assert result.returncode != 0
    assert "secrets" in result.stderr
    assert "DROP" not in result.stdout


def test_target_env_guard_before_destructive_plan(tmp_path):
    env = fixture_env(tmp_path)
    Path(env["ENV_FILE"]).write_text(f"DATA_DIR={env['DATA_DIR']}\n")
    result = invoke(env, "--cutover")
    assert result.returncode != 0
    assert "Missing target environment keys" in result.stderr
    assert "DROP" not in result.stdout
