# Runbook — Istirahat jadwal zona (rollout Zone Break)

**Untuk siapa:** operator/admin saat deploy dan pemeliharaan · **Kode:** fitur `zone.schedule.breaks`

Fitur menambah jendela istirahat opsional per zona (`schedule.breaks`, maks 5 entri `{start, end}`
HH:MM, setengah terbuka `[start, end)`, pada jam dinding lokal). Selama jendela itu zona tidak
mengevaluasi apa pun: tanpa event, klip, snapshot, Telegram, crop wajah, atau baris absensi.
Semua tipe zona — `intrusion`, `crowd`, `idle_zone`, `loitering`, `running` — patuh **jadwal penuh**
(hari + jam kerja + istirahat) lewat `schedule_active()`; gerbang absensi (`FaceGateWorker`)
menegakkan **istirahatnya saja** (jam kerja dan hari tidak ditegakkan di gate).

## Sebelum deploy ke server

1. Tinjau zona ber-jadwal yang ada. Zona Jam tertentu/Ikut shift yang selama ini berjalan 24 jam akan
   mulai berhenti di luar jam (disengaja, tetapi harus diketahui sebelum deploy):
   ```sql
   SELECT id, name, type, schedule FROM zone WHERE schedule IS NOT NULL;
   ```
2. Catat zona `loitering`, `running`, dan gate absensi dengan jadwal terisi; konfirmasi jendela
   hari/jamnya dengan user sebelum memasang kode baru.
3. Zona `24/7` yang butuh istirahat harus dipindah dulu (atau sesudah deploy) ke **Jam tertentu
   00:00–23:59 semua hari** di editor zona (istirahat tidak didukung pada jadwal 24/7; gate mengabaikan
   jam kerja sehingga hasilnya setara 24/7 + istirahat).

## Urutan deploy

1. Deploy **`api`** (+ `web`) dulu, kemudian **`vision`**; tanpa migrasi Alembic.
2. Urutan terbalik tetap aman: node lama mengabaikan kunci `breaks` (zona tetap berjalan sesuai
   jadwal lama tanpa istirahat) — yang belum bekerja hanya jendela istirahatnya.
3. Sesudah `vision` baru berjalan, pantau heartbeat node dan event pertama di sekitar batas istirahat.

## Perilaku yang berubah dibanding sebelum fitur

- `loitering` dan `running` berjadwal **mulai berhenti** di luar jam kerja dan saat istirahat
  (sebelumnya aktif 24 jam walau jadwal terisi). **Belum diuji di kamera nyata** — verifikasi live
  terlebih dahulu.
- Zona gate absensi yang istirahat tidak menghasilkan event/crop/rekap; kandidat wajah yang sedang
  dikumpulkan dibuang saat jendela mulai (tidak dikirim setelah istirahat).
- **Mode uji tunduk pada istirahat**: selama istirahat zona tidak dievaluasi walau sedang Mode uji.
- Kolektor identitas intrusion pada kamera yang sama **tetap mendeteksi wajah** saat gate istirahat.

## Batas yang diketahui

- Karyawan yang tiba di gerbang saat gerbang istirahat **tidak tercatat masuk** (bisa tampil
  `no_entry`/`absent` sampai dikoreksi admin). Follow-up: gerbang tetap merekam sambil mengabaikan
  scan istirahat; kecuali entry pertama hari itu.
- Klip/snapshot tidak direkam selama istirahat (rekam-sans-evaluasi adalah follow-up lain).
- Istirahat hanya untuk bentuk jadwal Jam tertentu dan Ikut shift; 24/7 tidak punya istirahat.

## Pemeriksaan dan pemulihan

- **Verifikasi live (belum pernah diuji di kamera nyata):** setelah deploy, amati ±10 menit di
  sekitar **mulai** dan **akhir** istirahat pada satu zona tiap tipe; bandingkan payload event
  (`ingest` log API) dan log `vision` — tidak boleh ada event yang terbit dari data pra-istirahat.
- **Rollback kode:** `git revert` commit fitur lalu redeploy image komponen terdampak (`api`,
  `vision`, `web`). Zona loitering/running berjadwal kembali tidak patuh jadwal seperti sebelumnya.
- **Rollback data:** nilai tersimpan berisi `breaks` tetap **terbaca** oleh kode lama (jadwal
  dibaca apa adanya). Bila zona itu perlu disimpan ulang lewat API lama (validator lama menolak kunci
  `breaks`), hapus kuncinya via editor UI atau SQL read-write yang disetujui admin:
  ```sql
  UPDATE zone SET schedule = schedule - 'breaks' WHERE schedule ? 'breaks';
  ```
- **Cek cepat pasca-deploy:** bandingkan jumlah zona ber-istirahat di UI dengan DB:
  ```sql
  SELECT id, name, type FROM zone WHERE schedule ? 'breaks' AND schedule->'breaks' <> '[]'::jsonb;
  ```
