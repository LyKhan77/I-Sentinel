# Zone Break (Waktu Istirahat per Zona) — Design Spec

- Tanggal: 2026-10-19
- Branch: `feat/zone-break` (dari `main` @ `9fa6128`)
- Status: draf, menunggu persetujuan user
- Catatan: versi awal spec ini menaruh istirahat di Shift. User memutuskan memindahkannya ke konfigurasi Zona Deteksi karena
  jam istirahat bisa berbeda per zona dan agar berguna untuk perusahaan lain. Shift tidak berubah sama sekali.

## 1. Latar Belakang & Tujuan

Zona deteksi punya jadwal **24/7**, **Jam tertentu**, atau **Ikut shift**. "Ikut shift" diubah menjadi `{days, start, end}`
oleh `resolve_schedule()` (`backend/app/services/config_push.py`) lalu node mengecek jendela itu lewat `schedule_active()`
(`vision/vision/analyzers/base.py`). Belum ada cara menonaktifkan zona pada jam istirahat.

Tujuan: admin dapat mengisi **jendela istirahat** opsional pada tiap zona (Konfigurasi → Zona Deteksi). Selama jendela itu zona
tidak mengevaluasi apa pun: tidak ada event, klip, snapshot, Telegram, crop wajah, atau baris absensi. Zona tanpa istirahat
tidak berubah.

Temuan kode yang membentuk ruang lingkup: `schedule_active()` hanya dipanggil oleh analyzer `intrusion`, `crowd`, dan
`idle_zone`. `FaceGateWorker` (gate absensi), `loitering`, dan `running` **tidak membaca `schedule` sama sekali**, dan backend
juga tidak menyaring event berdasarkan jadwal. Zona jenis itu sekarang aktif 24 jam walau jadwalnya terisi. Agar istirahat
berlaku untuk semua tipe zona, ketiganya harus mulai membaca jadwal (lihat §4.4 dan §5).

### Goals
- Setiap zona dengan jadwal "Jam tertentu" atau "Ikut shift" dapat punya istirahat sendiri (jam berbeda per zona).
- `intrusion`, `crowd`, `idle_zone`, `loitering`, `running` patuh **jadwal penuh** (hari, jam kerja, istirahat) memakai satu
  fungsi cek yang sama.
- Gate absensi patuh **hanya istirahat**; jam kerja tidak ditegakkan di gate.
- Format data siap untuk lebih dari satu istirahat per zona (daftar), walau UI awal hanya satu baris.

### Non-goals
- Perubahan pada Shift (model, API, tab Shift, migrasi), dan perhitungan absensi (`compute_status`, `deadline`,
  `exit_early_min`, `AttendanceCloser`).
- Istirahat untuk zona 24/7 tanpa jadwal. Cara pakai: pilih "Jam tertentu" 00:00–23:59 semua hari (gate mengabaikan jam
  kerja, jadi hasilnya sama dengan 24/7 ditambah istirahat).
- Istirahat berbeda per hari, shift lintas tengah malam, baris istirahat lebih dari satu di UI (data sudah mendukung).
- Penanda "sedang istirahat" di Live View atau daftar zona.
- Gate tetap merekam dan hitungan kehadiran mengabaikan scan istirahat. Follow-up tersendiri (§9).

### Anti-goals (dianggap gagal walau tampak berfungsi)
- Zona tanpa istirahat berubah perilakunya (selain loitering/running yang baru patuh jadwal, §5).
- Gate absensi menolak scan karena jam kerja (datang awal, pulang telat, lembur, hari non-kerja).
- Gate yang sedang istirahat masih menghasilkan event, crop, atau baris absensi.
- Event muncul tepat setelah istirahat berakhir hanya karena frame sebelum istirahat.
- Menyimpan zona dari editor menjatuhkan istirahat yang sudah ada.

## 2. Keputusan Desain

| Keputusan | Pilihan | Sumber |
|---|---|---|
| Letak pengaturan istirahat | konfigurasi zona, bukan Shift | user |
| Loitering/running/idle/crowd/intrusion | jadwal penuh (jam kerja + istirahat) | user |
| Gate absensi | hanya istirahat; jam kerja tidak ditegakkan (opsi A) | user, setelah builder check menunjukkan scan datang awal/pulang telat/lembur/shift lain akan hilang |
| Gate tetap merekam, kehadiran mengabaikan scan istirahat | tidak sekarang, follow-up | user |
| Data istirahat berupa daftar `breaks`, UI satu baris dulu | usulan | saya (user ingin siap dipakai perusahaan lain) |
| Istirahat tersedia untuk "Jam tertentu" dan "Ikut shift"; 24/7 tidak | usulan | saya |
| Setiap istirahat setengah terbuka `[start, end)`, `start < end`, tidak harus di dalam jam kerja, boleh tumpang tindih | usulan | saya |
| Maksimal 5 istirahat per zona | usulan | saya |

## 3. Data & API (backend)

- **Tanpa migrasi, tanpa kolom baru.** Istirahat disimpan di dalam `zone.schedule` (kolom JSON yang sudah ada):
  - Jam tertentu: `{"days": [...], "start": "HH:MM", "end": "HH:MM", "breaks": [{"start": "HH:MM", "end": "HH:MM"}]}`
  - Ikut shift: `{"shift_id": N, "breaks": [...]}`
  - Kunci `breaks` opsional; tidak ada atau `[]` berarti tanpa istirahat.
- **`_validate_schedule`** (`app/schemas/zone.py`) menerima kunci `breaks` opsional pada dua bentuk di atas dan tetap menolak
  kunci asing. Aturan `breaks`: list, panjang 0–5, tiap elemen dict persis `{start, end}`, format `HH:MM` (aturan waktu yang
  sama dengan `start`/`end`), `start < end` (perbandingan string `HH:MM`). Berlaku untuk `ZoneIn` dan `ZonePatch`.
- Tidak ada validasi silang terhadap jam kerja atau shift (istirahat di luar jam kerja tidak berbahaya; gate juga tidak
  menegakkan jam kerja).
- `ZoneOut.schedule` tetap `dict | None` tanpa validasi saat baca, jadi data berisi `breaks` aman dibaca setelah rollback.
- Audit zona sudah mencatat perubahan `schedule`; tidak ada perubahan.

## 4. Config Push & Node (vision)

### 4.1 `resolve_schedule()`
Untuk `{"shift_id": N, "breaks": [...]}` hasilnya `{"days", "start", "end"}` dari shift ditambah `"breaks"` yang disalin dari
zona bila tidak kosong. Untuk "Jam tertentu" jadwal diteruskan apa adanya (sudah memuat `breaks`). Shift yang hilang tetap
mengirim `None` (24/7) dengan peringatan log seperti sekarang; istirahat zona ikut hilang dalam kasus itu.

### 4.2 Fungsi cek di node
Tambah `break_active(schedule, ts)` di `base.py`: `True` bila ada elemen `breaks` dengan `start <= HH:MM < end` pada waktu
dinding lokal. `schedule_active()` memanggilnya setelah cek hari dan jendela kerja yang ada dan mengembalikan `False` saat
istirahat. Perilaku `schedule=None`, hari, dan jendela kerja inklusif tidak berubah. Node lama mengabaikan `breaks` (tidak
error), jadi urutan deploy API dan node bebas.

### 4.3 Analyzer yang sudah memanggil `schedule_active`
`intrusion`, `crowd`, `idle_zone`: tidak ada perubahan kode selain yang terbawa dari §4.2.

### 4.4 Yang baru membaca jadwal
- `LoiteringAnalyzer`, `RunningAnalyzer`: membaca `zone["schedule"]` dan memakai `schedule_active()` (jadwal penuh).
- `FaceGateWorker`: memakai **hanya `break_active()`**, tidak `schedule_active()`. Tanpa `breaks` (24/7, atau jadwal tanpa
  istirahat) gate berperilaku persis seperti sekarang.

Syarat perilaku, cara implementasi diserahkan ke builder:
- Saat off-window: tidak ada event, klip, snapshot, Telegram, crop wajah, atau baris absensi dari zona itu.
- State yang tertunda tidak boleh "bocor" melewati jendela: dwell loitering, kandidat identifikasi wajah yang sedang
  dikumpulkan, dan track berkecepatan tinggi tidak menghasilkan event setelah istirahat dari data sebelum istirahat.
  Mengikuti pola `intrusion` (state dibekukan; track yang masih di dalam saat jendela tutup tidak mengirim ulang saat buka).
- Untuk gate, melewati inferensi wajah selama istirahat dianjurkan (hemat GPU), asal funnel/heartbeat worker tetap normal.
- Satu kamera gate bisa punya beberapa zona; istirahat berlaku per zona, bukan per kamera.
- Kandidat wajah yang sedang dikumpulkan gate saat istirahat mulai dibuang (tidak dikirim setelah istirahat). *(Keputusan saya.)*
- Mode uji zona (`test_until`) tidak mengesampingkan jadwal: selama istirahat (atau di luar jadwal untuk analyzer jadwal penuh)
  zona tidak dievaluasi walau dalam Mode uji, sama seperti `intrusion` sekarang. Catat di `WORKFLOW.md`. *(Keputusan saya.)*

## 5. Dampak ke Zona yang Sudah Ada & Rollout

- **Gate absensi:** tidak ada risiko jam kerja. Tanpa `breaks` perilakunya tidak berubah.
- **Loitering dan running:** zona jenis ini yang sekarang punya `schedule` terisi (Jam tertentu atau Ikut shift) selama ini
  diam-diam aktif 24 jam. Setelah fitur ini mereka mulai berhenti di luar jam tersebut. Itu disengaja (keputusan user) tetapi
  harus diketahui sebelum deploy.
- Langkah sebelum deploy ke server: jalankan daftar zona ber-jadwal per tipe (`SELECT id, name, type, schedule FROM zone WHERE
  schedule IS NOT NULL`) dan tinjau bersama user. Tambahkan langkah ini ke runbook rollout.
- Urutan: API → node (aman bila terbalik; node lama mengabaikan `breaks`). Tidak ada migrasi.
- Rollback: kembalikan commit. Kunci `breaks` yang sudah tersimpan di zona diabaikan dan tidak merusak pembacaan
  (`ZoneOut.schedule` tidak divalidasi saat baca). Catatan: setelah rollback, menyimpan ulang zona berisi `breaks` dari API
  lama akan ditolak validator lama; hapus kunci itu lewat editor atau SQL bila perlu. Zona loitering/running kembali tidak
  patuh jadwal.

## 6. UI (frontend)

- `ZonesPage.tsx`: di bawah pemilih jadwal, saat mode "Jam tertentu" atau "Ikut shift", tampil bagian **Istirahat (opsional)**
  dengan satu baris waktu mulai dan selesai dan tombol hapus. Kosong berarti tanpa istirahat. Memilih "24/7" menghapus
  `schedule` seperti sekarang (istirahat ikut hilang).
- Perubahan lain pada jadwal (mengganti shift, mengubah hari/jam, berpindah antara Jam tertentu dan Ikut shift) tidak boleh
  menjatuhkan `breaks` yang sudah diisi; kode sekarang yang menulis ulang objek `schedule` (misalnya
  `{ shift_id: ... }`) harus diubah untuk mempertahankannya.
- Baris istirahat dengan salah satu waktu kosong atau `start >= end` ditandai tidak valid di form sebelum simpan; error 422
  server tetap ditampilkan seperti pola zona sekarang.
- `src/api/zones.ts`: `Schedule` dan `{ shift_id }` mendapat `breaks?: { start: string; end: string }[]`.
- Semua teks baru lewat `src/app/i18n.tsx`. Tidak ada overflow horizontal di 390 px.
- Halaman Shift dan Karyawan tidak berubah.

## 7. Pengujian

Tes harus gagal pada bug yang masuk akal, bukan mengunci implementasi.
- **Vision**: `schedule_active` dengan istirahat — tepat di `start` istirahat (False), satu menit sebelum (True), tepat di
  `end` istirahat (True), banyak istirahat, tanpa kunci `breaks` (perilaku lama). Tes per analyzer baru: loitering/running tidak
  menghasilkan output di luar jadwal/istirahat dan tidak ada output tertunda setelah istirahat; gate berhenti saat istirahat,
  tetap menerima scan di luar jam kerja, dan tanpa `breaks` identik dengan perilaku sekarang.
- **Backend**: validator menerima `breaks` valid di kedua bentuk, menolak kunci asing, non-list, lebih dari 5, format waktu
  salah, `start >= end`; `resolve_schedule` menyalin `breaks` untuk Ikut shift dan meneruskannya untuk Jam tertentu; config
  push memuat `breaks`.
- **Frontend**: mengisi, mengubah, dan menghapus istirahat; mengganti shift atau jam tidak menjatuhkan istirahat; 24/7
  menghapusnya; baris tidak valid tidak bisa disimpan.

## 8. Dokumentasi yang Diperbarui

`WORKFLOW.md` (§6 jadwal zona dan istirahat, catatan gate hanya patuh istirahat dan jam kerja tidak berlaku di gate, cara
24/7 + istirahat), `ARCHITECTURE.md` (semantik jadwal, bentuk `schedule.breaks`, daftar analyzer yang patuh jadwal),
`README.md` bila memuat daftar fitur, `ROADMAP.md`, `CHANGELOG.md` (konteks, file, bukti, dampak, rollback), runbook rollout
(langkah §5). Catatan kode lama yang menyebut jadwal hanya untuk sebagian analyzer diperbaiki.

## 9. Diserahkan ke Builder & Catatan Terbuka

- Titik pasti penyaringan jadwal di `FaceGateWorker`, `loitering`, `running` (selama §4.4 terpenuhi).
- Komponen input waktu dan tombol hapus (ikuti komponen Carbon yang sudah dipakai di editor zona).
- Kunci i18n dan teks Indonesia/Inggris sesuai pola `i18n.tsx`.
- **Batas yang diketahui:** karyawan yang tiba saat istirahat pada gate yang sedang istirahat tidak tercatat masuk (bisa menjadi
  `no_entry`/`absent` sampai dikoreksi admin). Dokumentasikan di `WORKFLOW.md`.
- **Follow-up:** (1) gate tetap merekam dan hitungan kehadiran mengabaikan scan istirahat (kecuali entry pertama hari itu),
  spec dan siklus tersendiri karena mengubah `attendance.py`; (2) UI beberapa baris istirahat; (3) istirahat untuk zona 24/7
  tanpa trik "Jam tertentu".
- Belum diuji di server nyata: perilaku gate di sekitar batas istirahat dengan kamera sungguhan. Verifikasi live adalah langkah
  terpisah setelah merge, sesuai alur deploy repo.
