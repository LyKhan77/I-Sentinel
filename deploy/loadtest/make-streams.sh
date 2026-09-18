#!/usr/bin/env bash
# Daftarkan/hapus N stream sintetis synth_<i> di go2rtc (ffmpeg file source,
# dikelola go2rtc — auto start saat viewer, restart otomatis). Jalankan DI SERVER.
#   ./make-streams.sh start 32      # daftarkan 32 stream
#   ./make-streams.sh stop          # hapus semua synth_*
#   ./make-streams.sh status
# Env: GO2RTC_API (default http://127.0.0.1:1984),
#      SYNTH_SRC (default ~/isentinel-data/loadtest/sample.mp4)
set -uo pipefail

GO2RTC_API="${GO2RTC_API:-http://127.0.0.1:1984}"
SYNTH_SRC="${SYNTH_SRC:-$HOME/isentinel-data/loadtest/sample.mp4}"

start() {
  local n="${1:-32}" i created=0 code
  [ -f "$SYNTH_SRC" ] || { echo "video sumber tidak ada: $SYNTH_SRC"; exit 1; }
  for i in $(seq 1 "$n"); do
    code=$(curl -s -X PUT -G "$GO2RTC_API/api/streams" \
      --data-urlencode "name=synth_$i" \
      --data-urlencode "src=ffmpeg:$SYNTH_SRC" \
      -o /dev/null -w '%{http_code}') || code="ERR"
    if [ "$code" = "200" ]; then created=$((created+1)); else echo "synth_$i -> $code"; fi
  done
  echo "didistribusikan: $created"
}

stop() {
  local n="${1:-2000}" i removed=0 code
  for i in $(seq 1 "$n"); do
    code=$(curl -s -X DELETE "$GO2RTC_API/api/streams?src=synth_$i" -o /dev/null -w '%{http_code}')
    [ "$code" = "200" ] && removed=$((removed+1))
  done
  echo "dihapus: $removed"
}

status() {
  local all
  all=$(curl -s "$GO2RTC_API/api/streams" | grep -o 'synth_[0-9]*' | sort -u | wc -l)
  echo "stream synth terdaftar: $all"
  free -m | awk 'NR==2{printf "RAM: %s MB terpakai dari %s MB\n", $3, $2}'
  nvidia-smi --query-gpu=index,utilization.gpu,memory.used --format=csv,noheader 2>/dev/null
}

case "${1:-}" in
  start) start "${2:-32}" ;;
  stop) stop "${2:-2000}" ;;
  status) status ;;
  *) echo "pakai: $0 {start N|stop|status}"; exit 2 ;;
esac
