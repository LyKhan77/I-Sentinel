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
    for name in ["api", "api/faces_models", "vision", "models", "go2rtc", "mosquitto/data", "secrets"]:
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


def test_camera_env_created_empty_0600_and_never_overwritten(tmp_path):
    """Berkas CAM_*/CAMERA_CREDENTIAL_* untuk API: dibuat kosong, tidak pernah ditimpa."""
    invoke(tmp_path)
    path = tmp_path / "data with spaces/secrets/camera.env"
    assert path.stat().st_mode & 0o777 == 0o600
    assert not [line for line in path.read_text().splitlines() if line and not line.startswith("#")]
    path.write_text("CAM_USERNAME='admin'\n")
    invoke(tmp_path)
    assert path.read_text() == "CAM_USERNAME='admin'\n"


def test_undetectable_lan_ip_warns_and_falls_back_to_loopback(tmp_path):
    """Tanpa peringatan, WebRTC dari LAN mati diam-diam (candidate 127.0.0.1)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {"ipconfig": "exit 1", "hostname": "exit 0"}.items():
        (bin_dir / name).write_text("#!/usr/bin/env bash\n" + body + "\n")
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GO2RTC_PUBLIC_HOST": "",
           "DATA_DIR": str(tmp_path / "data"), "ENV_FILE": str(tmp_path / "stack.env")}
    result = subprocess.run(["bash", str(DOCKER / "setup.sh"), "--env-only"], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert values(tmp_path / "stack.env")["GO2RTC_PUBLIC_HOST"] == "127.0.0.1"
    assert "127.0.0.1" in result.stderr and "GO2RTC_PUBLIC_HOST" in result.stderr


FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$DOCKER_CALLS"
case "$*" in
  "info --format"*) echo '{"runc":{"path":"runc"}}' ;;
  *download_face_models*) exit "${FAKE_DOWNLOAD_EXIT:-0}" ;;
  *" exec -T postgres psql"*"select name from node"*) echo "${FAKE_NODE_NAME:-server}" ;;
  *" exec -T postgres psql"*) echo 7 ;;
  *" ps -q"*) echo fakecontainer ;;
  "inspect "*) echo healthy ;;
  "run --rm --user"*)
      prev=""
      for arg in "$@"; do
          if [ "$prev" = "-v" ]; then mkdir -p "${arg%%:*}"; : > "${arg%%:*}/passwd"; fi
          prev="$arg"
      done ;;
esac
exit 0
"""


def run_full(tmp_path, *args, download_exit=1, node_name="server"):
    """Jalankan setup.sh penuh dengan docker palsu yang mencatat setiap panggilan."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "DOCKER_CALLS": str(tmp_path / "calls.log"),
           "FAKE_DOWNLOAD_EXIT": str(download_exit), "FAKE_NODE_NAME": node_name, "DATA_DIR": str(tmp_path / "data"),
           "ENV_FILE": str(tmp_path / "stack.env"), "GO2RTC_PUBLIC_HOST": "192.0.2.10"}
    return subprocess.run(["bash", str(DOCKER / "setup.sh"), *args], env=env, text=True, capture_output=True)


def calls(tmp_path):
    return (tmp_path / "calls.log").read_text().splitlines()


def first(lines, needle):
    return next(i for i, line in enumerate(lines) if needle in line)


def test_full_flow_survives_face_model_download_failure(tmp_path):
    """Jaringan tertutup: model wajah gagal diunduh -> peringatan, stack tetap naik."""
    result = run_full(tmp_path, "--rehearse", "--no-engine")
    assert result.returncode == 0, result.stderr
    assert "face model" in result.stderr.lower()
    lines = calls(tmp_path)
    order = [first(lines, "up -d postgres mosquitto go2rtc api"), first(lines, "exec -T postgres psql"),
             first(lines, "download_face_models"), len(lines) - 1]
    assert order == sorted(order)
    assert "up -d postgres mosquitto go2rtc api web retention" in lines[-1]
    assert values(tmp_path / "stack.env")["VISION_NODE_ID"] == "server"
    assert (tmp_path / "data/api/faces_models").is_dir()


def test_compose_run_is_non_interactive(tmp_path):
    run_full(tmp_path, "--rehearse", "--no-engine")
    run_calls = [line for line in calls(tmp_path) if " run " in f" {line} " and "download_face_models" in line]
    assert run_calls and all(" -T " in f" {line} " for line in run_calls)


def test_full_flow_rerun_is_idempotent(tmp_path):
    run_full(tmp_path, "--rehearse", "--no-engine")
    before = (tmp_path / "stack.env").read_bytes()
    result = run_full(tmp_path, "--rehearse", "--no-engine")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "stack.env").read_bytes() == before
    assert sum("mosquitto_passwd" in line for line in calls(tmp_path)) == 1


def test_vision_node_id_is_the_node_name_from_the_start(tmp_path):
    """MQTT mengenali node lewat NAMA (isentinel/nodes/<name>/heartbeat), bukan id numerik tabel."""
    assert values(DOCKER / ".env.example")["VISION_NODE_ID"] == "server"
    invoke(tmp_path)
    assert values(tmp_path / "stack.env")["VISION_NODE_ID"] == "server"


def test_node_name_must_be_safe_for_mqtt_topics(tmp_path):
    """Nama dengan / + # spasi merusak topik MQTT; setup berhenti, bukan menulisnya ke .env."""
    result = run_full(tmp_path, "--rehearse", "--no-engine", node_name="bad/name")
    assert result.returncode != 0
    assert "node name" in result.stderr.lower()
    assert values(tmp_path / "stack.env")["VISION_NODE_ID"] == "server"

