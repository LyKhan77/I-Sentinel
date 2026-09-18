#!/usr/bin/env bash
# Churn soak: remove + add ulang kamera SYNTH tiap CHURN_S detik, CHURNS kali.
#   ISENTINEL_PASS=... ./soak-churn.sh 5 300   # 5 siklus, tiap 300 s
set -uo pipefail
CYCLES="${1:-5}"; WAIT="${2:-300}"
DIR="$(cd "$(dirname "$0")" && pwd)"
export ISENTINEL_PASS="${ISENTINEL_PASS:?ISENTINEL_PASS belum diset}"

for i in $(seq 1 "$CYCLES"); do
  echo "[churn $i] $(date +%H:%M:%S) remove..."
  python3 "$DIR/register-cams.py" remove || true
  sleep 20
  echo "[churn $i] add kembali..."
  python3 "$DIR/register-cams.py" add 32 || true
  [ "$i" -lt "$CYCLES" ] && sleep "$WAIT"
done
echo "churn selesai"
