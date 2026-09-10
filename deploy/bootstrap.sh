#!/usr/bin/env bash
# I-Sentinel Fase 0 — bootstrap server dev (jalankan sebagai root/sudo di /opt/isentinel)
set -e

cd "$(dirname "$0")/.."

echo "==> Buat venv backend"
python3 -m venv backend/.venv
source backend/.venv/bin/activate

echo "==> Install backend[dev]"
pip install -e "backend[dev]"

echo "==> Migrasi database"
( cd backend && alembic upgrade head )

echo "==> Salin unit systemd"
cp deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable isentinel-api.service isentinel-recorder.service

cat <<'EOF'

=====================================================
Bootstrap selesai. Checklist manual:
1. Isi /opt/isentinel/.env dari .env.example:
   DATABASE_URL, JWT_SECRET, ADMIN_PASSWORD, CAM_USERNAME/PASSWORD
2. Mosquitto: cp deploy/mosquitto/mosquitto.conf /etc/mosquitto/mosquitto.conf
   sudo mosquitto_passwd -c /etc/mosquitto/passwd <user>
3. sudo systemctl start isentinel-api
4. curl -s localhost:8000/api/v1/health
=====================================================
EOF
