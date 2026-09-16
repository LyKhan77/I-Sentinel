#!/usr/bin/env bash
# Uji resiliensi I-Sentinel. Jalankan DI SERVER (gspe-ai3), bukan dari laptop.
# Semua restart memakai kill-cgroup karena sudo tanpa password tidak tersedia.
set -uo pipefail

ROOT="${ISENTINEL_ROOT:-/home/gspe-ai3/project_cv/I-Sentinel}"
API="${ISENTINEL_API:-http://127.0.0.1:8000}"
USER_NAME="${ISENTINEL_USER:-admin}"
USER_PASS="${ISENTINEL_PASS:?set ISENTINEL_PASS}"
JAR="$(mktemp)"
PASS=0; FAIL=0

ok()   { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
login() { curl -s -c "$JAR" -X POST "$API/api/v1/auth/login" -H 'Content-Type: application/json' \
            -d "{\"username\":\"$USER_NAME\",\"password\":\"$USER_PASS\"}" -o /dev/null; }
nodes() { curl -s -b "$JAR" "$API/api/v1/nodes"; }
restart_unit() { local u=$1
  kill "$(cat /sys/fs/cgroup/system.slice/$u/cgroup.procs 2>/dev/null)" 2>/dev/null || true
  for _ in $(seq 1 30); do sleep 1; systemctl is-active --quiet "$u" && return 0; done
  return 1; }

login
trap 'rm -f "$JAR"' EXIT

echo "== 1. API restart saat jalan =="
restart_unit isentinel-api.service && ok "API kembali aktif" || bad "API tidak kembali"
sleep 3; login
[ "$(curl -s -o /dev/null -w '%{http_code}' "$API/api/v1/health")" = "200" ] \
  && ok "health 200 setelah restart" || bad "health bukan 200"

echo "== 2. kill -9 vision → LWT → node offline =="
VPID=$(systemctl show -p MainPID --value vision-node.service)
kill -9 "$VPID" 2>/dev/null
sleep 20   # LWT broker + staleness di backend
STATE=$(nodes | grep -o '"status":"[a-z]*"' | head -1)
[ "$STATE" = '"status":"offline"' ] && ok "node terlihat offline ($STATE)" \
  || bad "node belum offline setelah 20 s ($STATE)"

echo "== 3. vision pulih + antrean ter-flush =="
restart_unit vision-node.service && ok "vision-node aktif lagi" || bad "vision-node gagal start"
sleep 30
STATE=$(nodes | grep -o '"status":"[a-z]*"' | head -1)
[ "$STATE" = '"status":"online"' ] && ok "node online lagi" || bad "node masih $STATE"

echo "== 4. kamera mati → status offline + event system =="
echo "  (manual: cabut/putus salah satu kamera, lalu jalankan ulang skrip ini)"
echo "  ekspektasi: /api/v1/cameras menunjukkan status != online dan muncul event type=system"

echo
echo "ringkasan: $PASS PASS, $FAIL FAIL"
[ "$FAIL" -eq 0 ]
