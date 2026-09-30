# Runbook: Retensi & Storage (retensi, cleanup event, alert disk)

Kegunaan: mengubah retensi clip/snapshot, membersihkan event lama per rentang tanggal dengan aman,
dan menanggapi peringatan disk hampir penuh. Semua lewat **Konfigurasi → Storage** (admin).

> Data absensi (riwayat `attendance_event`, rekap `attendance_day`, dan event Inbox tipe
> `attendance`) **tidak pernah** disentuh oleh mode `events`/`attendance_media` maupun retensi
> otomatis. Satu-satunya cara menghapusnya adalah mode admin eksplisit **"Data absensi (rekap &
> riwayat)"** di §2.3 — dan begitu dieksekusi, hasilnya **tidak bisa dipulihkan**.

## 1. Mengubah retensi (clip, snapshot, media absensi)

1. Konfigurasi → Storage → kartu **Pengaturan retensi**.
2. Isi **Retensi clip (hari)**, **Retensi snapshot (hari)** (behavior), **Retensi media absensi (hari)**
   (snapshot + crop wajah absensi; baris & rekap absensi tetap) (1–3650), dan/atau **Peringatan disk (%)**
   (50–99) → **Simpan** (toast "Pengaturan tersimpan"; nilai di luar rentang → 422 dengan pesan rentang).
3. Berlaku pada **sweep berikutnya** (timer systemd harian) atau tombol **Jalankan sekarang**
   (jalankan **Dry run** dulu untuk melihat dampaknya). Tanpa restart API.
4. Field yang belum pernah disimpan mengikuti `RETENTION_DAYS` di `.env`; setelah disimpan, nilai DB
   yang dipakai. Rollback cepat: isi ulang nilai lama lalu Simpan.

> Event yang seluruh medianya sudah habis (retensi atau cleanup media) ikut dihapus beserta alert-nya —
> card-nya hilang dari Events. Rekap & riwayat absensi tetap; log sistem dikecualikan.

## 2. Membersihkan event per rentang tanggal

1. Konfigurasi → Storage → kartu **Bersihkan event**.
2. Pilih **Dari tanggal** / **Sampai tanggal** (maks hari ini); opsional kamera & jenis
   (intrusion/loitering/running/idle_zone/crowd/**Log sistem** — endpoint menolak jenis lain dengan 422).
   Event absensi tidak pernah ikut (backend selalu mengecualikannya). Log sistem (node offline/LWT)
   hanya ikut bila dipilih eksplisit di Jenis.
   **Yang dibersihkan → Media absensi saja**: hanya foto & crop wajah event absensi di rentang (filter
   Jenis disembunyikan); event, riwayat masuk/keluar, dan rekap absensi tetap. Cocok untuk membuang foto
   absensi lama/uji tanpa mengubah rekap.
3. **Pratinjau** (dry run, tidak mengubah apa pun) → baca "N event · M file · X".
4. Bila sudah yakin → **Hapus N event** → modal konfirmasi menyebut jumlah + rentang → konfirmasi.
   Tombol Hapus hanya aktif setelah pratinjau untuk **filter yang sama**; jumlah pada konfirmasi
   berasal dari pratinjau saat itu — event baru yang masuk ke rentang yang sama sebelum konfirmasi
   tetap ikut terhapus.
5. Setelah eksekusi: notifikasi "Event dihapus" dan statistik disk disegarkan. Baris log
   `event cleanup by <admin>: <from>..<to> cameras=… types=… mode=events|attendance_media → N events, M files, X bytes`
   ada di `journalctl -u isentinel-api` (kegagalan dicatat dengan awalan `event cleanup by <admin> failed`).

Catatan: file yang masih dirujuk event di luar rentang (clip insiden bersama) **tidak** dihapus;
file yang sudah tidak ada / path di luar `STORAGE_ROOT` dilewati tanpa error; crop di
`payload.crop_path` tidak dikumpulkan cleanup (tersapu otomatis oleh orphan sweep setelah
`snapshot_days`). Baris event & alert dihapus lebih dulu, file menyusul — bila penghapusan file gagal,
barisnya sudah bersih dan sisanya disapu orphan sweep. Rentang mengikuti zona waktu lokal server dan
batasnya `[dari 00:00, sampai+1 hari 00:00)`.

### 2.3 Data absensi (rekap & riwayat) — permanen, bukan retensi

Server produksi biasanya berisi campuran karyawan uji dan karyawan nyata. Mode ini untuk membuang
data uji tanpa menyentuh karyawan lain — **bukan** proses otomatis, murni tindakan admin eksplisit.

1. **Yang dibersihkan → Data absensi (rekap & riwayat)**. Pilih **Dari/Sampai tanggal** — maksimum
   **kemarin** (shift hari ini mungkin masih berjalan, jadi hari ini tidak bisa dipilih). Kamera dan
   Jenis tidak berlaku untuk mode ini (disembunyikan).
2. Pilih **Karyawan** (MultiSelect, wajib minimal satu) **atau** centang **"Semua karyawan"** — harus
   salah satu, tidak boleh keduanya kosong atau keduanya terisi (backend menolak 422). "Semua
   karyawan" juga menghapus event wajah tak dikenal (attendance tanpa baris riwayat) di rentang itu;
   dengan filter karyawan tertentu, event wajah tak dikenal **tidak** ikut.
3. **Pratinjau** menampilkan ringkasan (riwayat, hari rekap, entri Inbox, file, ukuran) dan tabel
   per karyawan (riwayat + hari) — baca dulu sebelum menghapus, dry run tidak mengubah apa pun.
4. **Hapus data absensi** membuka modal yang mewajibkan mengetik **`HAPUS`** persis sebelum tombol
   aktif — konfirmasi lebih ketat dari dua mode lain karena tidak ada cara mengembalikannya.
5. Yang terhapus **permanen**: baris `attendance_event` (riwayat masuk/keluar), `attendance_day`
   (rekap harian, **termasuk yang punya `override_note`** — koreksi manual admin ikut hilang), event
   Inbox tipe `attendance` terkait beserta alert-nya, dan semua medianya (foto, crop wajah, clip
   lama). File yang masih dirujuk baris **di luar** seleksi (karyawan lain / rentang lain) tetap ada.
   **Ekspor CSV attendance untuk rentang ini akan kosong setelahnya.**
6. Audit log: `attendance data cleanup by <admin>: <from>..<to> employees=<id...|all> →
   N attendance_events, M days, K events, F files` — **hanya ID karyawan, tidak pernah nama** (data
   pribadi tidak masuk log).

## 3. Menanggapi peringatan disk hampir penuh

- Banner merah "Disk hampir penuh (N %)" muncul di **Dashboard** dan tab **Storage** saat pemakaian
  ≥ ambang. Pengingat Telegram berulang dibatasi **sekali per 24 jam**; saat pemakaian turun di bawah
  ambang − 2 % dikirim "✅ Disk pulih" (setelah pulih, kenaikan lagi di atas ambang mengirim pesan
  baru). State (`disk_alert_state`) ikut disimpan sehingga pengingat tetap benar setelah API restart.
- Tindakan: turunkan retensi (§1), bersihkan event lama yang tidak diperlukan (§2), atau pindahkan
  media di luar I-Sentinel. Bila pemakaian turun karena pembersihan, Telegram "pulih" terkirim
  otomatis (≤ 10 menit setelah cek berikutnya).
- Tanpa bot/grup Telegram: banner tetap muncul, tidak ada pesan — tidak ada error.

## Verifikasi cepat (server)

```bash
curl -s localhost:8000/api/v1/health            # {"status":"ok"}
journalctl -u isentinel-api -n 50 --no-pager    # cari "disk alert" / "event cleanup"
systemctl list-timers isentinel-retention.timer # jadwal sweep harian
```

Rollback: `git revert` commit fitur + restart **isentinel-api** (tanpa migrasi; setting `storage` /
`disk_alert_state` di DB diabaikan kode lama, retensi kembali ke `RETENTION_DAYS`). Event yang sudah
dibersihkan tidak bisa dipulihkan — berlaku juga untuk data absensi yang dihapus lewat §2.3
(revert hanya menghapus kode UI/endpoint-nya, bukan mengembalikan baris yang sudah terhapus).
Cadangkan (dump tabel `attendance_event`/`attendance_day` atau ekspor CSV) sebelum memakai §2.3 bila
ragu.
