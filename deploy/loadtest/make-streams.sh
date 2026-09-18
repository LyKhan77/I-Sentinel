#!/usr/bin/env bash
# Publish N video loop ke go2rtc sebagai stream synth_<i>. Jalankan DI SERVER.
#   ./make-streams.sh start 32      # nyalakan 32 stream
#   ./make-streams.sh stop          # matikan semua
#   ./make-streams.sh status
set -uo pipefail

N="${2:-32}"
SRC="${SYNTH_SRC:-$HOME/isentinel-data/loadtest/sample.mp4}"
RTSP="${SYNTH_RTSP:-rtsp://127.0.0.1:8554}"
PIDDIR="${SYNTH_PIDDIR:-/tmp/isentinel-synth}"
mkdir -p "$PIDDIR"

start() {
  [ -f "$SRC" ] || { echo "video sumber tidak ada: $SRC"; exit 1; }
  local started=0
  for i in $(seq 1 "$N"); do
    if [ -f "$PIDDIR/$i.pid" ] && kill -0 "$(cat "$PIDDIR/$i.pid")" 2>/dev/null; then continue; fi
    ffmpeg -nostdin -loglevel error -re -stream_loop -1 -i "$SRC" \
      -c:v libx264 -preset ultrafast -tune zerolatency -g 15 -f rtsp -rtsp_transport tcp \
      "$RTSP/synth_$i" >/dev/null 2>&1 &
    echo $! > "$PIDDIR/$i.pid"
    started=$((started+1))
  done
  echo "started: $started (total pidfile: $(ls "$PIDDIR" | wc -l))"
}

stop() {
  for f in "$PIDDIR"/*.pid; do [ -e "$f" ] || continue; kill "$(cat "$f")" 2>/dev/null; rm -f "$f"; done
  echo "semua publisher dimatikan"
}

status() {
  local live=0 total=0
  for f in "$PIDDIR"/*.pid; do [ -e "$f" ] || continue
    total=$((total+1)); kill -0 "$(cat "$f")" 2>/dev/null && live=$((live+1)); done
  echo "publisher hidup: $live / $total"
  free -m | awk 'NR==2{printf "RAM: %s MB terpakai dari %s MB\n", $3, $2}'
  nvidia-smi --query-gpu=index,utilization.gpu,memory.used --format=csv,noheader 2>/dev/null
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "pakai: $0 {start N|stop|status}"; exit 2 ;;
esac
