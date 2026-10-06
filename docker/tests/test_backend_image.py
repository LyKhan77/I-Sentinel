"""Entrypoint migration ordering and CPU face installation contract."""
import os
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "docker/backend/entrypoint.sh"


def run_entrypoint(tmp_path, migrate=None, fail=False):
    log = tmp_path / "alembic.log"
    fake = tmp_path / "alembic"
    fake.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$ALEMBIC_LOG"\nexit "${ALEMBIC_EXIT:-0}"\n')
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
           "ALEMBIC_LOG": str(log), "ALEMBIC_EXIT": "1" if fail else "0"}
    env.pop("RUN_MIGRATIONS", None)
    if migrate is not None:
        env["RUN_MIGRATIONS"] = migrate
    result = subprocess.run(["bash", str(ENTRYPOINT), "echo", "ok"], env=env, text=True, capture_output=True)
    return result, log.read_text() if log.exists() else ""


def test_entrypoint_skips_migration_by_default(tmp_path):
    result, log = run_entrypoint(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok\n"
    assert log == ""


def test_entrypoint_runs_migration_before_command(tmp_path):
    result, log = run_entrypoint(tmp_path, "1")
    assert result.returncode == 0, result.stderr
    assert log == "upgrade head\n"
    assert result.stdout == "ok\n"


def test_entrypoint_aborts_when_migration_fails(tmp_path):
    result, log = run_entrypoint(tmp_path, "1", fail=True)
    assert result.returncode != 0
    assert log == "upgrade head\n"
    assert "ok" not in result.stdout


def test_pyproject_has_face_extra():
    project = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())
    extra = project["project"]["optional-dependencies"].get("face", [])
    assert any(item.startswith("insightface") for item in extra)
    assert any(item.startswith("onnxruntime>=") for item in extra)
    assert not any(item.startswith("onnxruntime-gpu") for item in extra)


def test_runtime_stage_installs_ffmpeg():
    runtime = (ROOT / "docker/backend/Dockerfile").read_text().rsplit("FROM ", 1)[1]
    install = runtime.split("apt-get install", 1)[1].split("&&", 1)[0]
    assert "ffmpeg" in install.split()
