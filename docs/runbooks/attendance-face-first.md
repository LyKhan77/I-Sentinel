# Runbook: Deploy & Verifikasi R5b — Attendance Face-First

Kegunaan: deploy branch `feat/attendance-face-first` ke `gspe-ai3`, migrasi 0016,
restart node wajah, dan verifikasi lapangan (spec R5b §11).

> Semua langkah di server memerlukan izin user. **Lokal belum menjalankan bagian
> ini** — Task 11 R5b menandai seluruh verifikasi lapangan sebagai PENDING.
> Pin GPU tidak berubah: detector `cuda:1`, face `cuda:2`.

## 1. Urutan deploy

```bash
ssh gspe-ai3
cd /home/gspe-ai3/project_cv/I-Sentinel && git pull
/home/gspe-ai3/isentinel-venv/bin/alembic upgrade head     # 0015 → 0016 (face settings + purge embedding attendance)
/home/gspe-ai3/isentinel-venv/bin/python -m alembic current  # expect: 0016
# restart API: tanpa passwordless sudo, matikan cgroup proses; unit Restart=always
kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs)
kill $(cat /sys/fs/cgroup/system.slice/vision-node.service/cgroup.procs)
journalctl -u vision-node -f | grep -E "started .* worker"   # tunggu worker wajah siap
```

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
- `skor rendah` — skor deteksi SCRFD < `face_min_score`;
- `menyamping` — yaw > `face_max_yaw`;
- `buram` — blur < `face_blur_min`.

Wajah tanpa label (atau `ID n`) = lolos gerbang dan sedang menghitung frame bagus.

## 4. Kalibrasi `face_stats`

Perlu ≥10 lintasan nyata lewat gerbang. Buka debugger, catat distribusi label
`buram` (nilai blur) dan `wajah terlalu kecil` (width_px) dari log/overlay, lalu
setel `face_blur_min` dan `face_min_width_px` di Konfigurasi → Deteksi & Model →
Advanced → "Wajah attendance" agar wajah bagus lolos dan noise dibuang. Nilai
final dicatat di ROADMAP bagian R5b setelah kalibrasi lapangan.

## 5. Rollback

Urutan penting — **downgrade sebelum revert** (revert dulu menghapus file
migration 0016 dan Alembic tidak bisa menelusuri DB yang masih di 0016):

1. Stop API + vision: `kill` cgroup procs kedua service (lihat §1).
2. Backup DB.
3. `alembic downgrade 0015` **saat file migration 0016 masih ada** (branch lama
   belum dicheckout). `downgrade 0015` membuang kolom setelan wajah; embedding
   lama yang ter-purge tidak kembali.
4. `git revert` rentang R5b / checkout kode lama, deploy ulang.
5. Restart API + vision.

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
