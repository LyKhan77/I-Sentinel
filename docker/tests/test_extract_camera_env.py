"""Camera credentials are copied from the host env file without leaking or mangling values."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/extract_camera_env.py"


@pytest.fixture(scope="module")
def helper():
    spec = importlib.util.spec_from_file_location("extract_camera_env", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_keeps_only_camera_credential_keys(helper):
    text = "\n".join([
        "DATABASE_URL=postgresql+psycopg://u:p@h/db", "JWT_SECRET=abc", "TELEGRAM_BOT_TOKEN=tok",
        "MQTT_PASSWORD=m", "CAM_USERNAME=admin", "CAM_PASSWORD=pw", "CAMERA_CREDENTIAL_NVR_A=x", ""])
    assert helper.extract(text) == ["CAM_USERNAME='admin'", "CAM_PASSWORD='pw'",
                                    "CAMERA_CREDENTIAL_NVR_A='x'"]


def test_dollar_and_hash_survive_literally(helper):
    """Compose env_file menginterpolasi $VAR kecuali nilai diberi tanda kutip tunggal."""
    assert helper.extract("CAM_PASSWORD=pa$s#word\n") == ["CAM_PASSWORD='pa$s#word'"]


def test_systemd_style_quotes_are_stripped_once(helper):
    assert helper.extract('CAM_USERNAME="admin"\nCAM_PASSWORD=\'pw\'\n') == [
        "CAM_USERNAME='admin'", "CAM_PASSWORD='pw'"]


def test_comments_blanks_and_duplicates(helper):
    text = "# CAM_PASSWORD=old\n\nCAM_PASSWORD=first\nCAM_PASSWORD=second\n"
    assert helper.extract(text) == ["CAM_PASSWORD='second'"]


def test_unsafe_values_refused_without_echoing_them(helper):
    with pytest.raises(ValueError) as error:
        helper.extract("CAM_PASSWORD=it's-secret\n")
    assert "CAM_PASSWORD" in str(error.value)
    assert "it's-secret" not in str(error.value)


def test_cli_writes_0600_and_reports_count_only(helper, tmp_path, capsys):
    source = tmp_path / "host.env"
    source.write_text("CAM_USERNAME=admin\nCAM_PASSWORD=very-secret\n")
    target = tmp_path / "secrets/camera.env"
    target.parent.mkdir()
    assert helper.main([str(source), str(target)]) == 0
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.read_text() == "CAM_USERNAME='admin'\nCAM_PASSWORD='very-secret'\n"
    output = capsys.readouterr()
    assert "2" in output.out
    assert "very-secret" not in output.out + output.err
