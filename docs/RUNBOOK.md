# RUNBOOK — Operasional I-Sentinel di gspe-ai3

Semua perintah di bawah **sudah diverifikasi jalan**. Host: `gspe-ai3`
(LAN `192.168.2.133`), repo `/home/gspe-ai3/project_cv/I-Sentinel`.

## 1. Service & restart

| Unit | Fungsi |
|---|---|
| `isentinel-api.service` | FastAPI backend, port 8000 |
| `vision-node.service` | Vision node (MQTT → event) |
| `isentinel-web.service` | Frontend dev server, port 5173 |
| `go2rtc` | RTSP bridge/snapshot, port 1984 (API) + 8554 (RTSP) |
| `isentinel-retention.timer` | Sweep retensi harian 03:00 |

Restart tanpa sudo (unit memakai `Restart=always`, jadi kill cgroup = restart):

```bash
ssh gspe-ai3
kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs)
kill $(cat /sys/fs/cgroup/system.slice/vision-node.service/cgroup.procs)
kill $(cat /sys/fs/cgroup/system.slice/isentinel-web.service/cgroup.procs)
```

Verifikasi:

```bash
systemctl is-active isentinel-api vision-node isentinel-web go2rtc
curl -s localhost:8000/api/v1/health          # {"status":"ok"}
journalctl -u isentinel-api -n 50 --no-pager
```

Update versi di server:

```bash
ssh gspe-ai3 "cd /home/gspe-ai3/project_cv/I-Sentinel && git pull"
# bila ada migration baru:
ssh gspe-ai3 "export \$(tr '\0' '\n' < /proc/\$(systemctl show isentinel-api -p MainPID --value)/environ | grep '^DATABASE_URL=' | head -1) && cd /home/gspe-ai3/project_cv/I-Sentinel/backend && /home/gspe-ai3/isentinel-venv/bin/alembic upgrade head"
```

## 2. Backup

```bash
# DB (redact: jangan salin URL ke log/git)
ssh gspe-ai3 "export \$(tr '\0' '\n' < /proc/\$(systemctl show isentinel-api -p MainPID --value)/environ | grep '^DATABASE_URL=' | head -1) && pg_dump \"\$DATABASE_URL\" > ~/backup/isentinel-\$(date +%F).sql"
# .env — salin manual, mode 600
ssh gspe-ai3 "ls -l /home/gspe-ai3/project_cv/I-Sentinel/.env"   # pastikan 600
```

Restore: `psql "$DATABASE_URL" < file.sql` + `alembic downgrade` bila DB lebih baru dari kode.

## 3. Tambah kamera

UI: **Konfigurasi → Kamera → Tambah** — isi Nama/Lokasi/IP → **Deteksi otomatis**
(scan channel NVR) → pilih stream MAIN/SUB → simpan.

- `go2rtc.yaml` ditulis otomatis (stream `cam_<id>` via API go2rtc).
- Node membaca kamera setelah config push MQTT (otomatis, tanpa restart).
- Zona dibuat di tab **Zona**; gate absensi di **Gate Absensi**.

## 4. GPU detektor (pin/unpin)

UI: **Konfigurasi → Node** → pilih `cuda:N` (dropdown dari heartbeat hw) →
Simpan → node hot-reload **tanpa restart**. Badge Dashboard berubah
`Detektor: PIN cuda:N`.

Fallback env (bootstrap): `VISION_DETECTOR_DEVICE=cuda:1` di `vision.env`,
lalu restart vision-node. Prioritas: **DB (UI) > env > auto**.

Gagal pin (`cuda:N` > jumlah GPU): start → exit fail-fast; config push →
ditolak (node tetap hidup, device lama).

## 5. Troubleshooting

| Gejala | Cek |
|---|---|
| Live view 502/gambar hitam | `systemctl is-active go2rtc`; `curl -o /dev/null -w '%{http_code}' 'http://127.0.0.1:1984/api/frame.jpeg?src=cam_<id>'` |
| Node offline di Dashboard | heartbeat: `select status from node`; LWT di log MQTT; vision `journalctl -u vision-node` |
| Kamera worker mati (RTSP 404) | cek stream di `http://<host>:1984` WebUI; kredensial NVR di `.env` (references) |
| Vision node exit segera saat start | log `detector device pin invalid` — pin > jumlah GPU; koreksi di UI Node |
| Retensi tidak jalan | `systemctl list-timers isentinel-retention.timer`; manual: `cd backend && python scripts/retention_sweep.py` |
| API 500 setelah deploy | alembic belum upgrade: jalankan per §1; cek `journalctl -u isentinel-api` |

## 5b. Alert & Telegram

- Telegram belum dikonfigurasi → alert **tetap tercatat di DB**, hanya
  pengiriman yang dilewati (status `not_configured` di log). Verifikasi:
  `curl -H 'Authorization: Bearer <token>' localhost:8000/api/v1/alerts`.
- Konfigurasi Telegram: env `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` di `.env`,
  restart API. Rate limit alert: `ALERT_MIN_SEVERITY`, `TELEGRAM_RATE_LIMIT`.

## 5c. Rotasi JWT secret

```bash
# 1. set JWT_SECRET baru di .env (nilai baru, acak, 32+ byte)
# 2. restart isentinel-api (kill-cgroup per §1)
```

Efek: **semua sesi login mati seketika** (token lama tak valid) — user login ulang.
Tidak memengaruhi data event/alert/absensi.

## 5d. Retensi

- Jadwal: `isentinel-retention.timer`, harian 03:00 (`Persistent=true`).
- Manual: `cd /home/gspe-ai3/project_cv/I-Sentinel/backend && \
  /home/gspe-ai3/isentinel-venv/bin/python scripts/retention_sweep.py`.
- Scope: clip/crop/snapshot/faces melebihi `RETENTION_DAYS`; DB baris tidak
  dihapus (media path dibiarkan — kosong di disk). Hasil sweep terlihat di
  `journalctl -u isentinel-retention.service`.

## 6. Load test / soak

```bash
cd /home/gspe-ai3/project_cv/I-Sentinel
export ISENTINEL_PASS='<password-admin>'   # zero-secret: dari .env, jangan masukkan log
./deploy/loadtest/make-streams.sh start 32    # 32 stream ffmpeg file (sample 2 jam)
python3 deploy/loadtest/register-cams.py add 32
SOAK_PIN=cuda:1 SOAK_OUT=~/isentinel-data/loadtest/soak.csv ./deploy/loadtest/soak.sh 120 32
./deploy/loadtest/soak-churn.sh 5 300         # churn paralel (terminal lain)
./deploy/loadtest/register-cams.py remove && ./deploy/loadtest/make-streams.sh stop 2000
```

## 7. Batasan yang diketahui

- **sudo tanpa password terbatas** — pemasangan unit baru / upgrade paket perlu user.
- **Hot-reload device GPU**: inferensia pindah seketika; CUDA context lama di
  GPU sebelumnya lepas hanya saat proses vision-node direstart.
- **isentinel-recorder.service**: stub (tidak ter-install) — recorder blob
  berjalan di dalam vision node.
- **Disk 85%** — retensi `RETENTION_DAYS` memotong clip/crop/snapshot, bukan
  log/DB; pantau `df -h`.
