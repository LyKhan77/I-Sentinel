# Runbook: Deploy & Verifikasi R5b — Attendance Face-First

Kegunaan: deploy branch `feat/attendance-face-first` ke `gspe-ai3`, migrasi 0016,
restart node wajah, dan verifikasi lapangan (spec R5b §11).

> Semua langkah di server memerlukan izin user. **Lokal belum menjalankan bagian
> ini** — Task 11 R5b menandai seluruh verifikasi lapangan sebagai PENDING.
> Pin GPU tidak berubah: detector `cuda:1`, face `cuda:2`.

## 1. Urutan deploy

Server berada di branch `feat/detection-model`; `git pull` saja **tidak** membawa R5b.
Branch `feat/attendance-face-first` harus sudah di-push dulu (dari laptop).

```bash
ssh gspe-ai3
cd /home/gspe-ai3/project_cv/I-Sentinel
git fetch origin && git checkout feat/attendance-face-first && git pull --ff-only
git log --oneline -1                      # harus commit terbaru R5b

# backup WAJIB berhasil sebelum migrasi: 0016 menghapus embedding lama permanen.
# DATABASE_URL berskema SQLAlchemy (postgresql+psycopg://) -> buang "+psycopg" untuk pg_dump.
set -a; . ./.env; set +a
BACKUP="$HOME/backup-pra-0016-$(date +%Y%m%d-%H%M).sql"
pg_dump "${DATABASE_URL/+psycopg/}" > "$BACKUP" && test -s "$BACKUP" \
  && echo "BACKUP OK: $BACKUP ($(du -h "$BACKUP" | cut -f1))"
# STOP di sini bila baris di atas tidak mencetak "BACKUP OK".

# alembic.ini ada di backend/, bukan di root project
cd backend
/home/gspe-ai3/isentinel-venv/bin/alembic upgrade head   # 0015 -> 0016 (setelan wajah + purge embedding)
/home/gspe-ai3/isentinel-venv/bin/alembic current        # harus: 0016 (head)
cd ..

# restart tanpa passwordless sudo: matikan cgroup proses; unit Restart=always
kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs)
sleep 5 && curl -s localhost:8000/api/v1/health            # {"status":"ok"}
kill $(cat /sys/fs/cgroup/system.slice/vision-node.service/cgroup.procs)
timeout 150 bash -c 'until journalctl -u vision-node --since "-3 min" --no-pager | grep -q "started .* worker"; do sleep 3; done' \
  && echo "vision-node siap"
```

Frontend (`isentinel-web`, Vite dev) memuat kode baru langsung setelah checkout, tanpa restart.
Setelah deploy, zona attendance 7/8/9/11 masih `active=False`: fitur wajah belum
berjalan sampai zona digambar ulang (§2) lalu diaktifkan di Zona Deteksi (tipe Absensi).

Deploy frontend+backend dan vision harus bersamaan: PUT setelan wajah
(Task 7) menolak payload tanpa lima field wajah, jadi frontend lama + backend
baru → 422 saat Simpan.

## 2. Gambar ulang zona attendance

Zona attendance 7/8/9/11 digambar ulang di **area kepala** (polygon kecil di
sekitar kepala/atas badan pada frame utama), bukan seluruh area pintu. Gunakan
editor zona; arah gate tetap `entry`/`exit` seperti semula. Zona tanpa arah
diabaikan worker (tidak ada fallback person).

## 3. Membaca label gerbang di debugger

Live View → klik tile kamera attendance → modal debugger. Kotak biru (`face`)
dengan label:

- `di luar zona` — wajah terdeteksi di luar polygon zone;
- `wajah terlalu kecil` — lebar wajah < `face_min_width_px`;
- `skor rendah` — skor deteksi SCRFD < `face_min_det_score`;
- `menyamping` — yaw > `face_max_yaw`;
- `buram` — blur < `face_blur_min`.

Label berupa angka (mis. `0.82`) = lolos gerbang; angkanya skor kualitas frame itu, dan
worker sedang mengumpulkan frame bagus (default 3) sebelum menerbitkan satu event.

## 4. Kalibrasi `face_stats`

Perlu ≥10 lintasan nyata lewat gerbang. Buka debugger, catat distribusi label
`buram` (nilai blur) dan `wajah terlalu kecil` (width_px) dari log/overlay, lalu
setel `face_blur_min` dan `face_min_width_px` di Konfigurasi → Deteksi & Model →
Advanced → "Wajah attendance" agar wajah bagus lolos dan noise dibuang. Nilai
final dicatat di ROADMAP bagian R5b setelah kalibrasi lapangan.

## 5. Rollback

Urutan penting — **downgrade sebelum pindah branch** (kode lama tidak punya file
migration 0016, sehingga Alembic tidak bisa turun dari DB yang masih di 0016):

```bash
cd /home/gspe-ai3/project_cv/I-Sentinel
kill $(cat /sys/fs/cgroup/system.slice/vision-node.service/cgroup.procs)
set -a; . ./.env; set +a
pg_dump "${DATABASE_URL/+psycopg/}" > "$HOME/backup-pra-rollback-$(date +%Y%m%d-%H%M).sql"
cd backend && /home/gspe-ai3/isentinel-venv/bin/alembic downgrade 0015 && cd ..   # buang kolom setelan wajah
git checkout feat/detection-model                                                   # kode pra-R5b yang terakhir jalan
kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs)
kill $(cat /sys/fs/cgroup/system.slice/vision-node.service/cgroup.procs)
```

Embedding lama yang ter-purge oleh 0016 tidak kembali (disengaja); pulihkan dari
backup pra-0016 hanya bila benar-benar diperlukan.

## 6. Verifikasi (setelah deploy)

- `alembic current` = `0016`;
  `SELECT count(*) FROM event WHERE type='attendance' AND payload::text LIKE '%embedding%'` = 0.
- Retained config `isentinel/config/server` memuat `face` dengan enam kunci.
- Heartbeat `modules.face.device == "cuda:2"`; setelah orang lewat kamera
  attendance, `loaded == true` dan `nvidia-smi --query-compute-apps` menunjukkan
  proses vision di GPU index 2.
- Skenario lapangan spec R5b §11 dijalankan bersama user; bukti = baris DB
  (`event`, `attendance_event`) + file di `STORAGE_ROOT` + screenshot
  `docs/evidence/r5b-*.png`.
