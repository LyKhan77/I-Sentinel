# Runbook — Mode uji zona (tujuan event per behavior)

**Untuk siapa:** admin · **Di mana:** Konfigurasi → Zona Deteksi (`/configuration?tab=zones`)

Mode uji membuat satu behavior alert zona **berhenti menghasilkan bukti** selama 24 jam: tidak ada
event, tidak ada klip/snapshot, dan tidak ada alert Telegram. Zona tetap dievaluasi di node, dan track
yang akan memicu diberi label `UJI · <tipe>` di overlay Live View (hanya bila Debug aktif).

## Kapan dipakai

- Menyetel ulang polygon/trigger sebuah zona dan ingin mencoba tanpa membanjiri Inbox dan grup Telegram.
- Menghindari alarm palsu selama pekerjaan di area yang diawasi (mis. perbaikan, pembersihan).

## Cara memakai

1. Pilih kamera → pilih zona di daftar → centang behavior yang mau diuji (mis. **Intrusi**).
2. Pada **Tujuan event**, pilih **Mode uji**.
   - Zona `warning`: nilai langsung tersimpan saat **Simpan** (tanpa dialog).
   - Zona `critical`: muncul konfirmasi "alert keamanan zona ini berhenti selama uji dan kembali
     otomatis dalam 24 jam". **Batal** tidak mengubah nilai.
3. **Simpan**. Server menstempel `test_until = sekarang + 24 jam` dan `revert_to` = tujuan sebelum uji
   (Inbox + Telegram atau Hanya Inbox).
4. Daftar zona menampilkan badge **UJI · sampai HH:MM** selama uji berlaku.
5. Uji berakhir sendiri: node dan API kembali ke `revert_to` **tanpa restart** dan badge hilang.
   Menyimpan perubahan lain (nama, polygon, trigger) **tidak** memperpanjang uji.

## Batas dan hal yang harus diketahui

- **Tidak ada bukti selama uji.** Event yang tidak dibuat tidak bisa ditinjau kemudian — kalau kejadian
  di area itu perlu bukti, jangan pakai Mode uji.
- Uji hanya untuk behavior **alert** (intrusion, loitering, running, idle zone, crowd). Absensi tidak
  diubah oleh fitur ini (tetap punya toggle Telegram/Record sendiri).
- **Node lama** (belum di-deploy dengan dukungan `delivery`) tetap mengirim event; API menolak
  mengirim Telegram selama `test_until` berlaku, jadi Inbox bisa tetap terisi tetapi grup aman.
- **Selisih jam** node dan API menggeser akhir uji. Keduanya berjalan di server yang sama (Jetson
  memakai NTP); selisih detik tidak berarti untuk jendela 24 jam.
- **Perilaku saat kembali** mengikuti `revert_to`, bukan selalu "Inbox + Telegram" — zona yang sengaja
  disetel *Hanya Inbox* tidak mendadak mengirim Telegram setelah uji.
- Batas uji 24 jam adalah pengaman: alert keamanan zona tidak bisa dimatikan permanen lewat UI ini.
  Bila sebuah zona memang harus tanpa alert Telegram seterusnya, pilih **Hanya Inbox** (event tetap
  tercatat sebagai bukti).

## Pemeriksaan dan pemulihan

- Badge **UJI** hilang tetapi alert tidak kembali → periksa `delivery`/`revert_to` zona lewat
  `GET /api/v1/zones` (read-only) dan jam server (`date -u` di host) sebelum menyalahkan node.
- Alert kembali lebih cepat dari perkiraan → ada penyimpanan zona yang memulai uji baru
  (`test_until` bergeser), atau `revert_to` memang *Hanya Inbox*.
- **Rollback cepat:** pilih **Inbox + Telegram** (atau **Hanya Inbox**) lalu **Simpan** — kunci uji
  dibuang otomatis; tanpa deploy. Rollback kode: `git revert` commit Plan B (tanpa migrasi; kunci JSON
  tak dikenal diabaikan kode lama).
