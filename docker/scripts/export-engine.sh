#!/usr/bin/env bash
set -euo pipefail

DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$DOCKER_DIR/.env}"
dry_run=0
gpu="${VISION_ENGINE_GPU:-0}"
gpu_set=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) dry_run=1 ;;
        *)
            if [[ "$gpu_set" == 1 || ! "$arg" =~ ^[0-9]+$ ]]; then
                echo "GPU index must be numeric; usage: export-engine.sh [--dry-run] [GPU_INDEX]" >&2
                exit 1
            fi
            gpu="$arg"
            gpu_set=1
            ;;
    esac
done
if [[ ! "$gpu" =~ ^[0-9]+$ ]]; then
    echo "GPU index must be numeric" >&2
    exit 1
fi
command=(docker compose -f "$DOCKER_DIR/compose.yml" --env-file "$ENV_FILE"
    --profile vision run --rm --no-deps --workdir /models
    -e "CUDA_VISIBLE_DEVICES=$gpu" vision python /app/vision/scripts/export_engine.py --model yolo26s.pt)
if [[ "$dry_run" == 1 ]]; then
    printf '+ '; printf '%q ' "${command[@]}"; printf '\n'
else
    "${command[@]}"
fi
