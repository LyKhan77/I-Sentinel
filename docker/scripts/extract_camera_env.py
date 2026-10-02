"""Copy camera credentials from the host env file (systemd format) to camera.env (Compose env_file).

Only CAM_USERNAME, CAM_PASSWORD and CAMERA_CREDENTIAL_* are copied. Values are written single-quoted
because Compose interpolates $VAR in unquoted env_file values; systemd does not, so a password such as
"pa$s#word" would otherwise change. Values are never printed.
"""
import os
from pathlib import Path
import re
import sys

KEY = re.compile(r"CAM_USERNAME|CAM_PASSWORD|CAMERA_CREDENTIAL_[A-Za-z0-9_]+")


def _value(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def extract(text: str) -> list[str]:
    """Return KEY='value' lines for camera credentials; later duplicates win, as in systemd."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] in "#;" or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        key = key.strip()
        if not KEY.fullmatch(key):
            continue
        value = _value(raw)
        if "'" in value or "\n" in value or "\r" in value:
            raise ValueError(f"{key}: value contains a single quote or newline; write it into camera.env by hand")
        found[key] = value
    return [f"{key}='{value}'" for key, value in found.items()]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: extract_camera_env.py HOST_ENV_FILE CAMERA_ENV_FILE", file=sys.stderr)
        return 2
    try:
        lines = extract(Path(argv[0]).read_text())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    if not lines:
        print("camera.env: 0 entries found; target left unchanged")
        return 0
    fd = os.open(argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as target:
        target.write("\n".join(lines) + "\n")
    print(f"camera.env: {len(lines)} entries written (values not shown)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
