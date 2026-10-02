#!/usr/bin/env bash
set -euo pipefail

DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$DOCKER_DIR/.env}"
HOST_ENV_FILE="${HOST_ENV_FILE:-/home/gspe-ai3/project_cv/I-Sentinel/.env}"
HOST_DATA_ROOT="${HOST_DATA_ROOT:-/home/gspe-ai3/project_cv/I-Sentinel-data}"
HOST_SECRETS_FILE="${HOST_SECRETS_FILE:-/home/gspe-ai3/.isentinel/camera-secrets.json}"
HOST_ENGINE="${HOST_ENGINE:-/home/gspe-ai3/isentinel-data/models/yolo26s.engine}"
mode=
mode_count=0
dry_run=0
force=0
for arg in "$@"; do
    case "$arg" in
        --rehearse) mode=rehearse; mode_count=$((mode_count+1)) ;;
        --cutover) mode=cutover; mode_count=$((mode_count+1)) ;;
        --dry-run) dry_run=1 ;;
        --force) force=1 ;;
        *) echo "Usage: migrate-from-host.sh (--rehearse | --cutover) [--dry-run] [--force]" >&2; exit 1 ;;
    esac
done
if [[ "$mode_count" != 1 ]]; then
    echo "Choose exactly one mode: --rehearse or --cutover" >&2
    exit 1
fi
command -v python3 >/dev/null
umask 077

# Only DATA_DIR is imported from the target env; host env is never sourced.
DATA_DIR="$(python3 - "$ENV_FILE" "$DOCKER_DIR" "$HOST_DATA_ROOT" <<'PY'
from pathlib import Path
import shlex
import sys
values = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, raw = line.split('=', 1)
        parts = shlex.split(raw, comments=True)
        values[key] = parts[0] if parts else ''
missing = {'DATA_DIR', 'COMPOSE_PROFILES', 'VISION_NODE_ID'} - values.keys()
if missing:
    sys.exit('Missing target environment keys: ' + ', '.join(sorted(missing)))
value = values['DATA_DIR']
if not value:
    sys.exit('Target environment requires DATA_DIR')
target = (Path(sys.argv[2]) / value).resolve()
source = Path(sys.argv[3]).resolve()
if target == source or target in source.parents or source in target.parents:
    sys.exit('DATA_DIR must be separate from HOST_DATA_ROOT (no overlapping paths)')
if target == Path('/'):
    sys.exit('DATA_DIR must not be root')
print(target)
PY
)"
export DATA_DIR
if [[ -f "$DATA_DIR/.cutover-done" && "$force" != 1 ]]; then
    echo "Cutover already recorded; refusing to overwrite Docker data. Use --force only after backup and explicit approval." >&2
    exit 1
fi
if [[ "$mode" == rehearse && -e "$DATA_DIR/secrets/camera-secrets.json" ]]; then
    echo "Rehearsal target already contains camera secrets; use a fresh DATA_DIR to prevent duplicate alerts." >&2
    exit 1
fi
if [[ "$mode" == cutover && "${OLD_UNITS_CHECK:-check}" != skip ]]; then
    if ! command -v systemctl >/dev/null; then
        echo "Unable to verify old units: systemctl unavailable" >&2
        exit 1
    fi
    for unit in isentinel-api isentinel-web vision-node go2rtc isentinel-retention.timer; do
        status="$(systemctl is-active "$unit" 2>/dev/null || true)"
        case "$status" in
            inactive|failed|unknown) ;;
            active|activating|reloading|deactivating)
                echo "Old unit $unit is $status; stop and disable old units before cutover." >&2
                exit 1
                ;;
            *) echo "Unable to verify old unit $unit; refusing cutover." >&2; exit 1 ;;
        esac
    done
fi
if [[ ! -d "$HOST_DATA_ROOT/api" ]]; then
    echo "Host api data directory missing" >&2
    exit 1
fi
if [[ "$mode" == cutover && ( ! -d "$HOST_DATA_ROOT/vision" || ! -f "$HOST_SECRETS_FILE" ) ]]; then
    echo "Cutover requires host vision data and host secrets file" >&2
    exit 1
fi

# Keep the password out of command arguments and dry-run output.
connection="$(python3 - "$HOST_ENV_FILE" <<'PY'
from pathlib import Path
import shlex
import sys
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
url = None
for line in Path(sys.argv[1]).read_text().splitlines():
    if line.startswith('DATABASE_URL='):
        parts = shlex.split(line.split('=', 1)[1], comments=True)
        url = parts[0] if parts else ''
if not url:
    sys.exit('Host environment requires DATABASE_URL')
try:
    parsed = urlsplit(url.replace('postgresql+psycopg://', 'postgresql://', 1))
    if parsed.scheme != 'postgresql' or not parsed.hostname or not parsed.path.strip('/'):
        raise ValueError
    host = parsed.hostname
    if ':' in host:
        host = '[' + host + ']'
    user = parsed.username or ''
    netloc = (user + '@' if user else '') + host + (':' + str(parsed.port) if parsed.port else '')
    password = unquote(parsed.password or '')
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() == 'password':
            password = value
        else:
            query.append((key, value))
    clean = urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(query), ''))
except ValueError:
    sys.exit('Invalid host DATABASE_URL; expected PostgreSQL URI')
print('host_database=' + shlex.quote(clean))
print('host_password=' + shlex.quote(password))
PY
)"
eval "$connection"
export COMPOSE_PROFILES=
if [[ "$mode" == cutover ]]; then
    export COMPOSE_PROFILES=vision
fi
compose=(docker compose -f "$DOCKER_DIR/compose.yml" --env-file "$ENV_FILE")

print_command() {
    printf '+ '; printf '%q ' "$@"; printf '\n'
}
execute() {
    print_command "$@"
    if [[ "$dry_run" == 0 ]]; then
        "$@"
    fi
}

if [[ "$dry_run" == 0 ]]; then
    for tool in docker pg_dump rsync; do command -v "$tool" >/dev/null; done
    docker info >/dev/null
    "${compose[@]}" config -q
    dump="$(mktemp "${TMPDIR:-/tmp}/isentinel-migration.XXXXXX")"
    trap 'rm -f "$dump"' EXIT
else
    dump=/tmp/isentinel-migration-XXXXXX.sql
fi
# Include inactive profile services explicitly so any prior vision run is stopped.
execute "${compose[@]}" --profile vision stop api retention vision
print_command pg_dump --no-owner --no-privileges --dbname "$host_database" --file "$dump"
if [[ "$dry_run" == 0 ]]; then
    PGPASSWORD="$host_password" pg_dump --no-owner --no-privileges --dbname "$host_database" --file "$dump"
fi
execute "${compose[@]}" exec -T postgres psql -U isentinel -d postgres -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS isentinel WITH (FORCE)'
execute "${compose[@]}" exec -T postgres psql -U isentinel -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE isentinel OWNER isentinel'
printf '+ '; printf '%q ' "${compose[@]}" exec -T postgres psql -U isentinel -d isentinel -v ON_ERROR_STOP=1; printf '< %q\n' "$dump"
if [[ "$dry_run" == 0 ]]; then
    "${compose[@]}" exec -T postgres psql -U isentinel -d isentinel -v ON_ERROR_STOP=1 < "$dump"
fi
execute mkdir -p "$DATA_DIR/api" "$DATA_DIR/vision" "$DATA_DIR/models" "$DATA_DIR/secrets"
rsync_args=(-a)
if [[ "$mode" == cutover ]]; then
    rsync_args+=(--delete)
fi
execute rsync "${rsync_args[@]}" "$HOST_DATA_ROOT/api/" "$DATA_DIR/api/"
if [[ "$mode" == cutover ]]; then
    execute rsync "${rsync_args[@]}" "$HOST_DATA_ROOT/vision/" "$DATA_DIR/vision/"
fi
if [[ -f "$HOST_ENGINE" && ! -f "$DATA_DIR/models/yolo26s.engine" ]]; then
    execute cp "$HOST_ENGINE" "$DATA_DIR/models/yolo26s.engine"
fi
# Camera credentials (CAM_*, CAMERA_CREDENTIAL_*) are read from the environment by the API; the
# Telegram token lives in camera-secrets.json and is withheld in rehearsal.
execute python3 "$DOCKER_DIR/scripts/extract_camera_env.py" "$HOST_ENV_FILE" "$DATA_DIR/secrets/camera.env"
if [[ "$mode" == cutover ]]; then
    execute cp "$HOST_SECRETS_FILE" "$DATA_DIR/secrets/camera-secrets.json"
    execute chmod 700 "$DATA_DIR/secrets"
    execute chmod 600 "$DATA_DIR/secrets/camera-secrets.json"
fi
printf '+ update %q COMPOSE_PROFILES=%s\n' "$ENV_FILE" "$COMPOSE_PROFILES"
if [[ "$dry_run" == 0 ]]; then
    python3 - "$ENV_FILE" "$COMPOSE_PROFILES" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
lines = path.read_text().splitlines(keepends=True)
if not any(line.startswith('COMPOSE_PROFILES=') for line in lines):
    sys.exit('Target environment requires COMPOSE_PROFILES')
path.write_text(''.join('COMPOSE_PROFILES=' + sys.argv[2] + '\n' if line.startswith('COMPOSE_PROFILES=') else line for line in lines))
PY
fi
# Refresh the node id from the restored DB, not from the clean bootstrap database.
printf '+ refresh VISION_NODE_ID in %q from restored server node\n' "$ENV_FILE"
if [[ "$dry_run" == 0 ]]; then
    node_id="$("${compose[@]}" exec -T postgres psql -U isentinel -d isentinel -tAc "select id from node where type='server' order by id limit 1" | tr -d '[:space:]')"
    if [[ ! "$node_id" =~ ^[0-9]+$ ]]; then
        echo "Restored server node id missing; migration stopped before startup." >&2
        exit 1
    fi
    python3 - "$ENV_FILE" "$node_id" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
lines = path.read_text().splitlines(keepends=True)
if not any(line.startswith('VISION_NODE_ID=') for line in lines):
    sys.exit('Target environment requires VISION_NODE_ID')
path.write_text(''.join('VISION_NODE_ID=' + sys.argv[2] + '\n' if line.startswith('VISION_NODE_ID=') else line for line in lines))
PY
    export VISION_NODE_ID="$node_id"
fi
if [[ "$mode" == cutover ]]; then
    execute "${compose[@]}" up -d
    execute touch "$DATA_DIR/.cutover-done"
else
    execute "${compose[@]}" up -d postgres mosquitto go2rtc api web retention
fi
echo "Verify health on :7701/api/v1/health, login on :7700, row counts, sample clip checksums, and alembic current."
if [[ "$mode" == cutover ]]; then
    echo "Update Telegram app_url to http://<LAN-IP>:7700 through the UI; measure the detection gap."
else
    echo "Rehearsal leaves systemd unchanged and vision disabled; compare copied data and LAN live playback."
fi
