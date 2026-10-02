#!/usr/bin/env bash
set -euo pipefail

DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$DOCKER_DIR/.env}"
env_only=0
rehearse=0
no_engine=0
created=0
has_nvidia=1
for arg in "$@"; do
    case "$arg" in
        --env-only) env_only=1 ;;
        --rehearse) rehearse=1 ;;
        --no-engine) no_engine=1 ;;
        *) echo "Usage: setup.sh [--env-only] [--rehearse] [--no-engine]" >&2; exit 1 ;;
    esac
done
command -v python3 >/dev/null
command -v openssl >/dev/null
umask 077

# Parse literal dotenv values; never execute an existing environment file.
load_env() {
    local declarations
    declarations="$(python3 - "$ENV_FILE" "$DOCKER_DIR/.env.example" <<'PY'
from pathlib import Path
import shlex
import sys
keys = {line.split('=', 1)[0] for line in Path(sys.argv[2]).read_text().splitlines()
        if line and not line.startswith('#')}
values = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    if '=' not in line or line.lstrip().startswith('#'):
        continue
    key, value = line.split('=', 1)
    if key in keys:
        parts = shlex.split(value, comments=True)
        values[key] = parts[0] if parts else ''
missing = keys - values.keys()
if missing:
    sys.exit('Missing environment keys: ' + ', '.join(sorted(missing)))
for key, value in values.items():
    print('export ' + key + '=' + shlex.quote(value))
PY
)"
    eval "$declarations"
}

compose() {
    docker compose -f "$DOCKER_DIR/compose.yml" --env-file "$ENV_FILE" "$@"
}

print_access() {
    echo "Web: http://$GO2RTC_PUBLIC_HOST:7700"
    echo "Ports: web 7700, API 7701, go2rtc 7702, WebRTC 7703 TCP/UDP, MQTT 7704; RTSP 7705 internal."
    if [[ "$created" == 1 ]]; then
        echo "ADMIN_USERNAME=$ADMIN_USERNAME"
        echo "ADMIN_PASSWORD=$ADMIN_PASSWORD"
    else
        echo "Admin credentials remain in $ENV_FILE (not printed again)."
    fi
    echo "Register cameras through the UI. Offline: place yolo26s.pt in $DATA_DIR/models before engine export."
}

if [[ "$env_only" == 0 ]]; then
    command -v docker >/dev/null
    docker compose version >/dev/null
    docker info >/dev/null
    if ! docker info --format '{{json .Runtimes}}' | grep -q 'nvidia'; then
        echo "Warning: NVIDIA runtime unavailable; vision will not be started." >&2
        has_nvidia=0
    fi
    if [[ "$(uname -s)" == Linux ]] && command -v systemctl >/dev/null; then
        if ! systemctl is-enabled docker.service >/dev/null 2>&1; then
            echo "Warning: docker.service is not enabled; arrange reboot startup before production." >&2
        fi
    fi
fi

if [[ ! -f "$ENV_FILE" ]]; then
    export HOST_UID="$(id -u)" HOST_GID="$(id -g)"
    export DATA_DIR="${DATA_DIR:-$DOCKER_DIR/../../I-Sentinel-docker-data}"
    DATA_DIR="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$DATA_DIR")"
    export DATA_DIR
    if [[ -z "${GO2RTC_PUBLIC_HOST:-}" ]]; then
        if [[ "$(uname -s)" == Darwin ]]; then
            GO2RTC_PUBLIC_HOST="$(ipconfig getifaddr en0 2>/dev/null || true)"
        else
            GO2RTC_PUBLIC_HOST="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
        fi
    fi
    if [[ -z "${GO2RTC_PUBLIC_HOST:-}" ]]; then
        echo "Warning: LAN IP not detected; using 127.0.0.1, so WebRTC from other machines will not work. Set GO2RTC_PUBLIC_HOST before the first run." >&2
        GO2RTC_PUBLIC_HOST=127.0.0.1
    fi
    export GO2RTC_PUBLIC_HOST
    if [[ -z "${TZ:-}" && -r /etc/timezone ]]; then
        TZ="$(cat /etc/timezone)"
    fi
    export TZ="${TZ:-Asia/Jakarta}"
    export POSTGRES_PASSWORD="$(openssl rand -hex 24)" JWT_SECRET="$(openssl rand -hex 32)"
    export NODE_API_KEY="$(openssl rand -hex 32)" MQTT_PASSWORD="$(openssl rand -hex 24)"
    export ADMIN_PASSWORD="$(openssl rand -hex 24)"
    export MQTT_USERNAME=isentinel ADMIN_USERNAME=admin VISION_NODE_ID=1
    export VISION_SHM_SIZE="${VISION_SHM_SIZE:-2gb}" VISION_ENGINE_GPU="${VISION_ENGINE_GPU:-0}"
    export RETENTION_DAYS="${RETENTION_DAYS:-30}" COMPOSE_PROFILES=vision
    if [[ "$rehearse" == 1 || "$has_nvidia" == 0 ]]; then
        export COMPOSE_PROFILES=
    fi
    mkdir -p "$(dirname "$ENV_FILE")"
    python3 - "$ENV_FILE" "$DOCKER_DIR/.env.example" <<'PY'
import os
from pathlib import Path
import shlex
import sys
keys = [line.split('=', 1)[0] for line in Path(sys.argv[2]).read_text().splitlines()
        if line and not line.startswith('#')]
with open(sys.argv[1], 'x') as target:
    for key in keys:
        target.write(key + '=' + shlex.quote(os.environ[key]) + '\n')
PY
    created=1
fi
load_env
chmod 600 "$ENV_FILE"
# Existing DATA_DIR wins over command-line environment overrides.
DATA_DIR="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.join(sys.argv[1],sys.argv[2])))' "$DOCKER_DIR" "$DATA_DIR")"
export DATA_DIR
if [[ "$rehearse" == 1 || "$has_nvidia" == 0 ]]; then
    export COMPOSE_PROFILES=
fi
mkdir -p "$DATA_DIR/api" "$DATA_DIR/api/faces_models" "$DATA_DIR/vision" "$DATA_DIR/models" "$DATA_DIR/go2rtc" \
    "$DATA_DIR/mosquitto/data" "$DATA_DIR/secrets"
chmod 700 "$DATA_DIR/go2rtc" "$DATA_DIR/secrets"
if [[ ! -f "$DATA_DIR/secrets/camera.env" ]]; then
    printf '%s\n' "# Camera credentials for the API: CAM_USERNAME, CAM_PASSWORD, CAMERA_CREDENTIAL_* (env: profiles)." \
        "# One KEY='value' per line; single quotes keep \$ and # literal." > "$DATA_DIR/secrets/camera.env"
fi
chmod 600 "$DATA_DIR/secrets/camera.env"
if [[ ! -f "$DATA_DIR/go2rtc/go2rtc.yaml" ]]; then
    python3 - "$DOCKER_DIR/go2rtc/go2rtc.yaml.tmpl" "$DATA_DIR/go2rtc/go2rtc.yaml" <<'PY'
import os
from pathlib import Path
import re
import sys
host = os.environ['GO2RTC_PUBLIC_HOST']
if not re.fullmatch(r'[A-Za-z0-9.-]+', host):
    sys.exit('GO2RTC_PUBLIC_HOST must be an IPv4 address or hostname')
with open(sys.argv[2], 'x') as target:
    target.write(Path(sys.argv[1]).read_text().replace('${GO2RTC_PUBLIC_HOST}', host))
PY
fi
chmod 600 "$DATA_DIR/go2rtc/go2rtc.yaml"
if [[ "$env_only" == 1 ]]; then
    print_access
    exit 0
fi

# Refuse occupied ports on a fresh stack, without disturbing existing services.
if [[ -z "$(compose ps -q)" ]]; then
    python3 - <<'PY'
import socket
import sys
sockets = []
try:
    for port, kind in [(p, socket.SOCK_STREAM) for p in range(7700, 7705)] + [(7703, socket.SOCK_DGRAM)]:
        sock = socket.socket(socket.AF_INET, kind)
        sockets.append(sock)
        try:
            sock.bind(('0.0.0.0', port))
        except OSError:
            sys.exit('Port %s (%s) is in use; setup stopped.' % (port, 'UDP' if kind == socket.SOCK_DGRAM else 'TCP'))
finally:
    for sock in sockets:
        sock.close()
PY
fi
if [[ ! -f "$DATA_DIR/mosquitto/passwd" ]]; then
    docker run --rm --user "$HOST_UID:$HOST_GID" -v "$DATA_DIR/mosquitto:/passwords" \
        eclipse-mosquitto:2.0.22 mosquitto_passwd -b -c /passwords/passwd "$MQTT_USERNAME" "$MQTT_PASSWORD"
fi
chmod 600 "$DATA_DIR/mosquitto/passwd"
if [[ -n "$COMPOSE_PROFILES" ]]; then
    compose build api web vision
else
    compose stop vision
    compose build api web
fi
compose up -d postgres mosquitto go2rtc api
healthy=0
for ((attempt=0; attempt<60; attempt++)); do
    container="$(compose ps -q api)"
    if [[ -n "$container" ]] && [[ "$(docker inspect --format '{{.State.Health.Status}}' "$container")" == healthy ]]; then
        healthy=1
        break
    fi
    sleep 2
done
if [[ "$healthy" != 1 ]]; then
    echo "API did not become healthy within 120 seconds; inspect compose logs api." >&2
    exit 1
fi
node_id="$(compose exec -T postgres psql -U isentinel -d isentinel -tAc "select id from node where type='server' order by id limit 1" | tr -d '[:space:]')"
if [[ ! "$node_id" =~ ^[0-9]+$ ]]; then
    echo "Server node id missing or invalid" >&2
    exit 1
fi
python3 - "$ENV_FILE" "$node_id" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
before = path.read_text()
lines = before.splitlines(keepends=True)
after = ''.join('VISION_NODE_ID=' + sys.argv[2] + '\n' if line.startswith('VISION_NODE_ID=') else line for line in lines)
if after != before:
    path.write_text(after)
PY
export VISION_NODE_ID="$node_id"
if [[ -z "$(find "$DATA_DIR/api/faces_models" -name '*.onnx' -print -quit 2>/dev/null || true)" ]]; then
    compose run --rm -T --no-deps -e RUN_MIGRATIONS=0 api python scripts/download_face_models.py \
        || echo "Warning: face model download failed; enrollment needs buffalo_l in $DATA_DIR/api/faces_models. Fix the network or copy the models, then rerun setup.sh." >&2
fi
if [[ -n "$COMPOSE_PROFILES" && "$no_engine" == 0 && ! -f "$DATA_DIR/models/yolo26s.engine" ]]; then
    ENV_FILE="$ENV_FILE" "$DOCKER_DIR/scripts/export-engine.sh" "$VISION_ENGINE_GPU"
fi
if [[ -n "$COMPOSE_PROFILES" ]]; then
    compose up -d
else
    compose up -d postgres mosquitto go2rtc api web retention
fi
print_access
