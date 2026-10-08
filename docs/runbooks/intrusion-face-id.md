# Runbook — Face ID pada intrusion critical

Fitur: identitas wajah pada alert intrusion `critical`, ditulis ke caption Telegram setelah alert
terkirim (tanpa menunda atau menyupresi alert). Status: **belum diuji di server nyata**.

## Cara menyalakan (butuh persetujuan sebelum menulis ke server)

1. Siapkan zona intrusion yang akan diawasi. Kamera tidak perlu punya zona attendance: kamera
   dengan zona critical ber-`face_id` otomatis mendapat worker wajah sendiri (membaca stream utama
   kamera itu; SCRFD hanya jalan saat ada gerakan atau orang di zona).
2. Di **Konfigurasi → Zona**: zona intrusion → severity `critical` → behavior **Intrusi** →
   nyalakan **Cari identitas wajah** → Simpan. Kamera itu akan restart sendiri (apply per kamera)
   dan log `vision` menampilkan worker face dengan kolektor identitas.
3. Tanpa perubahan di server lain. `FACE_ID_THRESHOLD` (default `0.50`) dan `FACE_ID_MARGIN`
   (default `0.10`) di `docker/.env` **wajib diikuti recreate `api`** (`docker compose up -d api`
   --force-recreate`), bukan `restart` — Compose tidak membaca ulang env saat restart.

## Membaca hasil

- **Caption Telegram**: baris `Identitas: Dikenali: <nama>` / `Wajah terlihat, tidak dikenali` /
  `Wajah tidak terlihat jelas` / `Identitas tidak terverifikasi` (empat hasil; `unverified` =
  pesan susulan tidak pernah datang dalam 20 detik — cek log consumer MQTT dan status worker face).
- **Inbox**: baris Identitas di panel detail (`event-identity`), tab **Crop wajah** untuk event
  intrusion ber-`crop_path` (bukti manual untuk yang tidak dikenali).
- **Live View, overlay debugger**: kotak wajah yang terhubung ke kepala orang (40% atas bbox person) diberi label hasil gerbang identitas, yaitu kualitas (`0.62`) atau penolakan `wajah terlalu kecil` / `skor rendah` / `menyamping` / `buram` / `menunduk/mendongak` / `kualitas rendah`, bukan status zona. Pada kamera tanpa zona attendance, wajah yang bukan kepala siapa pun tidak digambar. Kamera ber-zona attendance tetap memberi label `di luar zona` pada wajah yang bukan kandidat identitas.
- **Log**: `identity_skipped_text_only` = alert terkirim sebagai teks, tidak bisa diedit (wajar).
  `zona face_id tetapi model wajah tidak tersedia` (log `vision`) = model wajah tidak termuat
  (`VISION_FACE_MODEL_DIR`/insightface); identitas tidak aktif dan alert critical berakhir `unverified`.
  `unverified` berulang di kamera critical → periksa `torch.cuda.device_count()` di container
  `vision` (container pernah kehilangan akses GPU dua kali, 2026-10-06 dan 2026-10-08; restart
  `vision` atas persetujuan bila 0).

## Kalibrasi (setelah uji lapangan dengan pencahayaan memadai)

1. Jalankan lintasan karyawan terdaftar (menghadap kamera) dan orang tidak terdaftar; catat
   `payload.face.score` tiap event (Inbox / DB).
2. Pilih `FACE_ID_THRESHOLD` di atas sebaran skor impostor tertinggi; `FACE_ID_MARGIN` dari jarak
   top-1/top-2 genuine. **Salah-orang harus nol dalam uji** — jangan menurunkan ambang agar
   pengenalan "berhasil" di kondisi gelap.
3. `MAX_PITCH` dan gerbang kualitas node di `vision/vision/intrusion_face.py` (konstanta atas
   berkas) hanya diubah bila statistik penolakan menunjukkan gerbang yang salah.
4. Probe kelayakan bisa diulang per kamera (`temp/scripts/intrusion_face_probe.py`, tidak
   di-commit; hasil terakhir `temp/logs/intrusion-face-id/probe.md`: kamera 363 gelap, 0 frame
   lolos gerbang penuh).

## Retensi crop intrusion

Crop wajah intrusion di `crops/` mengikuti **`snapshot_days`** (bukan `attendance_days`) dan tidak
dihapus sebagai orphan selama masih dirujuk event. File kedaluwarsa dihapus, `payload.crop_path`
dinolkan, `media_expired` ditandai; event tanpa media lain ikut dibersihkan.

## Rollback

- Cepat: matikan toggle `face_id` di zona (atau kembalikan severity) — node berhenti mengirim
  pesan identitas; alert kembali persis perilaku lama.
- Kode: `git checkout <commit sebelum face ID> && ./docker/setup.sh`. Kolom `0023_alert_face_synced`
  aditif — tidak perlu downgrade. Perhatian: kode lama sapuan retensi menganggap crop intrusion
  sebagai orphan; sebelum rollback, jalankan sekali sapuan dengan versi baru atau terima crop lama
  terhapus sebagai orphan.
