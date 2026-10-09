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
3. **Parameter** ada di **Konfigurasi → Deteksi & Model → Advanced → kartu "Pengenalan wajah"**
   (grup **Identitas**): ambang kecocokan, margin top-1/top-2, lebar minimum identitas, batas pitch,
   K frame terbaik, dan jendela identitas. Nilai disimpan di baris `detector_setting` (migrasi 0024),
   dipush ke node lewat config push, dan dipakai API pada event berikutnya — **tanpa deploy, tanpa
   recreate `api`**. Env `FACE_ID_MARGIN` / `FACE_MATCH_THRESHOLD` hanya cadangan bila baris setelan
   belum ada (instalasi baru), begitu pula `FACE_ID_MARGIN` di `docker/.env`.

| Parameter | Letak sekarang | Nilai awal | Catatan |
|---|---|---|---|
| Ambang kecocokan | Grup **Bersama** (dipakai absensi + identitas) | 0,40 | Menggantikan `FACE_ID_THRESHOLD` (repo 0,50) dan env `FACE_MATCH_THRESHOLD` |
| Margin top-1/top-2 | Grup **Identitas** | 0,15 | Menggantikan `FACE_ID_MARGIN` |
| Lebar minimum identitas | Grup **Identitas** | 60 px | Dulu konstanta `IDENT_MIN_WIDTH_PX` di kode node |
| Batas pitch / K / jendela | Grup **Identitas** | 0,30 / 5 / 8 dtk | Dulu konstanta `MAX_PITCH` / `BEST_K` / `IDENT_WINDOW_S` |
| Gerbang absensi lama (lebar, blur, jumlah frame, yaw, skor) | Grup **Absensi (lama)** + **Bersama** | tetap | Tidak berubah pada tahap ini |

   Interval pembaruan (10 dtk), maksimum pembaruan (6), batas lacak (90 dtk), dan `UNVERIFIED_AFTER_S`
   (20 dtk) tetap konstanta kode di `vision/vision/intrusion_face.py` dan `app/services/intrusion_face.py`.

## Membaca hasil

- **Caption Telegram**: baris `Identitas: Dikenali: <nama>` / `Wajah terlihat, tidak dikenali` /
  `Wajah tidak terlihat jelas` / `Identitas tidak terverifikasi` (empat hasil; `unverified` =
  pesan susulan tidak pernah datang dalam 20 detik — cek log consumer MQTT dan status worker face).
  Hasil bisa **naik** selama orang masih di zona (maks 90 detik; mis. `Wajah terlihat, tidak dikenali` →
  `Dikenali: <nama>` saat orang menemukan titik terbaik); tidak pernah turun, dan caption hanya diedit
  lagi saat status berubah (skor/crop yang lebih baik diperbarui diam-diam di Inbox).
- **Inbox**: baris Identitas di panel detail (`event-identity`), tab **Crop wajah** untuk event
  intrusion ber-`crop_path` (bukti manual untuk yang tidak dikenali).
- **Live View, overlay debugger**: kotak wajah yang terhubung ke kepala orang (40% atas bbox person) diberi label hasil gerbang identitas, yaitu lebar wajah dalam piksel (`86px`, artinya lolos gerbang) atau penolakan `wajah terlalu kecil` (< `face.ident.min_width_px`, awal 60 px) / `skor rendah` / `menyamping` / `menunduk/mendongak`, bukan status zona. Label `buram` dan `kualitas rendah` tidak muncul lagi untuk identitas: ketajaman hanya dipakai sebagai peringkat relatif, bukan gerbang. Pada kamera ber-zona attendance label absensi (`buram`, dst.) tetap memakai gerbang attendance. Pada kamera tanpa zona attendance, wajah yang bukan kepala siapa pun tidak digambar. Kamera ber-zona attendance tetap memberi label `di luar zona` pada wajah yang bukan kandidat identitas.
- **Log**: `identity_skipped_text_only` = alert terkirim sebagai teks, tidak bisa diedit (wajar).
  `zona face_id tetapi model wajah tidak tersedia` (log `vision`) = model wajah tidak termuat
  (`VISION_FACE_MODEL_DIR`/insightface); identitas tidak aktif dan alert critical berakhir `unverified`.
  `unverified` berulang di kamera critical → periksa `torch.cuda.device_count()` di container
  `vision` (container pernah kehilangan akses GPU dua kali, 2026-10-06 dan 2026-10-08; restart
  `vision` atas persetujuan bila 0).

## Kalibrasi (setelah uji lapangan dengan pencahayaan memadai)

1. Jalankan lintasan karyawan terdaftar (menghadap kamera) dan orang tidak terdaftar; catat
   `payload.face.score` tiap event (Inbox / DB).
2. Pilih **ambang kecocokan** (grup Bersama) di atas sebaran skor impostor tertinggi; **margin top-1/top-2**
   (grup Identitas) dari jarak top-1/top-2 genuine. **Salah-orang harus nol dalam uji** — jangan menurunkan ambang agar
   pengenalan "berhasil" di kondisi gelap.
3. Lebar minimum identitas, batas pitch, K, dan jendela kini di grup **Identitas** (tanpa deploy);
   konstanta operasional lain (pembaruan 10 dtk, maksimum 6, lacak 90 dtk) tetap di `vision/vision/intrusion_face.py` dan
   hanya diubah bila statistik penolakan menunjukkan gerbang yang salah.
4. Probe kelayakan bisa diulang per kamera (`temp/scripts/intrusion_face_probe.py`, tidak
   di-commit; hasil terakhir `temp/logs/intrusion-face-id/probe.md`: kamera 363 gelap, 0 frame
   lolos gerbang penuh).

### Keadaan kalibrasi saat ini (2026-10-08)

- **Nilai efektif setelah migrasi 0024:** ambang 0,40 / margin 0,15 dari baris `detector_setting` (UI
  Konfigurasi → Deteksi & Model), menggantikan nilai uji `.env` server 0,35 / 0,15. `FACE_ID_THRESHOLD`
  tidak lagi dipakai; `FACE_ID_MARGIN` hanya cadangan bila baris belum ada. Ubah di UI, tanpa deploy.
- **Dasar:** galeri 7 karyawan × 5 foto pendaftaran: impostor (skor terbaik non-pemilik, n = 35)
  median 0,225, maksimum 0,280; genuine antar foto pendaftaran minimum 0,582. Crop jarak 1–2 m:
  wajah ±96–125 px hampir frontal memberi skor 0,37–0,58 (kandidat kedua 0,17–0,23); wajah menunduk
  (±111 px) hanya 0,27–0,33. Pose lebih menentukan daripada ukuran. Upscaling dan flip-averaging
  tidak memberi manfaat berarti.
- **Belum ada** uji non-karyawan di depan kamera: tingkat salah-orang belum terukur, jadi 0,35 adalah
  nilai uji, bukan hasil kalibrasi akhir. Lengkapi dengan beberapa lintasan tiap karyawan terdaftar
  dan beberapa orang tidak terdaftar pada jarak 1–2 m, lalu pilih ulang ambang dari data itu.

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
