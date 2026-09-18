#!/usr/bin/env bash
# Soak: N stream sintetis + sampel metrik tiap 30 s ke CSV. Jalankan DI SERVER.
#   SOAK_OUT=~/isentinel-data/loadtest/soak.csv ISENTINEL_PASS=... ./soak.sh 120 32
# Pin GPU detektor via config push: SOAK_PIN=cuda:1 (opsional).
# Churn (remove+add kamera) dikelola skrip terpisah: ./soak-churn.sh.
set -uo pipefail

MINUTES="${1:-120}"; N="${2:-32}"
OUT="${SOAK_OUT:-$HOME/isentinel-data/loadtest/soak-$(date +%Y%m%d-%H%M).csv}"
API="${ISENTINEL_API:-http://127.0.0.1:8000}"
PASS="${ISENTINEL_PASS:?ISENTINEL_PASS belum diset}"
PYBIN="${PY:-python3}"
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$(dirname "$OUT")"

if [ ! -f "$HOME/isentinel-data/loadtest/sample.mp4" ]; then
  echo "sample video tidak ada — jalankan dulu Task 10 setup"; exit 1
fi

login_cookie() {
  curl -s -X POST "$API/api/v1/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ISENTINEL_USER:-admin}\",\"password\":\"$PASS\"}" \
    | grep -o '"token":"[^"]*"' | cut -d'"' -f4
}

# --- pin device detektor via config push (D1: GPU1) ---
PIN="${SOAK_PIN:-}"
if [ -n "$PIN" ]; then
  TOK=$(login_cookie)
  code=$(curl -s -X PUT "$API/api/v1/nodes/1/detector-device" \
    -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
    -d "{\"device\":\"$PIN\"}" -o /dev/null -w '%{http_code}')
  echo "pin $PIN -> HTTP $code"
fi

# --- mulai stream + kamera
"$DIR/make-streams.sh" start "$N"
"$DIR/register-cams.py" add "$N" || true

echo "ts,gpu0_util,gpu0_mem,gpu1_util,gpu1_mem,gpu2_util,gpu2_mem,vision_rss_kb,api_rss_kb,events_total,nvidia_worker_procs" > "$OUT"
END=$(( $(date +%s) + MINUTES * 60 ))
while [ "$(date +%s)" -lt "$END" ]; do
  TS=$(date +%s)
  GPU=$(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' ' | paste -sd,)
  VRSS=$(ps -o rss= -p "$(systemctl show -p MainPID --value vision-node.service)" 2>/dev/null | tr -d ' ')
  ARSS=$(ps -o rss= -p "$(systemctl show -p MainPID --value isentinel-api.service)" 2>/dev/null | tr -d ' ')
  # total event hari ini via DB (stats API butuh auth; sampler cukup hitung baris)
  EV=$(DBURL=$(tr '\0' '\n' < /proc/"$(systemctl show -p MainPID --value isentinel-api.service)"/environ | grep '^DATABASE_URL=' | head -1 | cut -d= -f2-) \
       "$PY" -c "from sqlalchemy import create_engine,text; import os;e=create_engine(os.environ['DBURL']);print(e.connect().execute(text('select count(*) from event')).scalar())" 2>/dev/null || echo 0)
  NVPROC=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c "$(systemctl show -p MainPID --value vision-node.service)")
  echo "$TS,${GPU:-0,0,0,0,0,0},$VRSS,$ARSS,$EV,$NVPROC" >> "$OUT"
  sleep 30
done

echo "CSV: $OUT"
awk -F, 'NR>1{n++; u1+=$2; m1+=$3; u2+=$5; m2+=$6; r+=$8; if($8>max)max=$8}
 END{printf "sampel=%d\nGPU1 util rata2 %.1f%% mem rata2 %d MB\nvision RSS rata2 %.0f MB puncak %.0f MB\n",
 n, u2/n, m2/n, r/n/1024, max/1024}' "$OUT"
