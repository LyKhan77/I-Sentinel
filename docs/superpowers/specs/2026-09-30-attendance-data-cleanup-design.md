# Design: Cleanup data absensi (rekap & riwayat)

**Konteks:** Server punya campuran karyawan uji dan karyawan nyata. Admin butuh cara aman untuk
menghapus permanen `attendance_event` + `attendance_day` (termasuk `override_note`) + entri Inbox
absensi terkait + file media, dibatasi per karyawan terpilih dan rentang tanggal — bukan retensi
otomatis, murni tindakan admin eksplisit.

**Keputusan (sudah disetujui):**
- Mode ketiga `attendance_data` di card "Bersihkan event" yang sudah ada (bukan halaman baru).
- Hapus semuanya untuk seleksi: riwayat, rekap (termasuk yang punya `override_note`), event Inbox
  terkait, dan file media — tidak ada opsi "sisakan koreksi manual".
- `date_to` maksimum **kemarin** (shift hari ini mungkin masih berjalan) — beda dari mode lain yang
  mengizinkan hari ini.
- Wajib pilih karyawan eksplisit ATAU centang "Semua karyawan" — tidak ada default diam-diam.
- Audit log berisi ID karyawan, bukan nama (data pribadi).
- Konfirmasi mengetik `HAPUS` (lebih ketat dari dua mode lain yang cukup klik modal) karena data
  tidak bisa dipulihkan dan berdampak pada rekap yang mungkin dipakai untuk penggajian/CSV.

**Reuse:** `retention._range_query`, `_chunks`, `_media_fields`, `_delete_events`, `_safe_join`,
`_size`, `_remove_files` — pola proteksi file bersama dan urutan "baris dulu, file sesudah" identik
dengan `cleanup_attendance_media`.

**Di luar cakupan:** tidak ada migrasi skema, tidak ada endpoint terpisah (menumpang
`POST /storage/cleanup` yang sudah admin-gated), tidak ada undo/soft-delete.

Rincian field, validasi, dan bentuk respons: lihat brief tugas (identik, tidak diduplikasi di sini).
