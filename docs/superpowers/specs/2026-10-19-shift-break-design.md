# Shift Break (Waktu Istirahat) — Design Spec

- Tanggal: 2026-10-19
- Branch: `feat/shift-break` (dari `main` @ `9fa6128`)
- Status: draf, menunggu persetujuan user

## 1. Latar Belakang & Tujuan

Zona deteksi bisa memilih jadwal **24/7**, **Jam tertentu**, atau **Ikut shift**. "Ikut shift" mengubah shift menjadi
`{days, start, end}` (`resolve_schedule()` di `backend/app/services/config_push.py`) lalu node mengecek jendela itu lewat
`schedule_active()` (`vision/vision/analyzers/base.py`). Shift belum punya konsep istirahat, jadi zona yang mengikuti shift
tetap aktif saat jam istirahat.

Tujuan: admin mengisi **jendela istirahat** opsional pada Shift (halaman Enrollment → tab Shift). Selama jendela itu, zona
yang memakai "Ikut shift" tidak mengevaluasi apa pun (tidak ada event, klip, Telegram, atau baris absensi), kecuali zona yang
admin kecualikan lewat checkbox per zona. Di luar jendela itu perilaku sama seperti sekarang.

Temuan kode yang membentuk ruang lingkup: `schedule_active()` hanya dipanggil oleh analyzer `intrusion`, `crowd`, dan
`idle_zone`. `FaceGateWorker` (gate absensi), `loitering`, dan `running` **tidak membaca `schedule` sama sekali**, dan backend
juga tidak menyaring event berdasarkan jadwal. Jadi zona jenis itu sekarang aktif 24 jam walau jadwalnya terisi. Agar istirahat
berlaku untuk semua zona "Ikut shift", ketiganya harus mulai membaca jadwal. Untuk `loitering` dan `running` itu berarti jadwal
penuh. Untuk gate absensi hanya istirahat (alasan di §2 dan §4.4).

### Goals
- Shift punya satu jendela istirahat opsional, diatur di halaman Shift.
- Zona `intrusion`, `crowd`, `idle_zone`, `loitering`, `running` patuh **jadwal penuh** (hari, jam kerja, istirahat bila ada)
  memakai satu fungsi cek yang sama.
- Gate absensi (entry/exit) patuh **hanya jendela istirahat** dari shift; jam kerja shift tidak ditegakkan di gate.
- Zona "Ikut shift" bisa dikecualikan dari istirahat lewat checkbox per zona, supaya zona yang harus menyala terus tetap
  mengikuti jam shift tanpa jeda.
- Edit istirahat pada Shift langsung berlaku di node tanpa langkah manual.

### Non-goals
- Istirahat untuk opsi **Jam tertentu** (manual per zona). Bentuk data dan form zona itu tidak berubah. Gate absensi dengan
  "Jam tertentu" tetap mengabaikan jadwal seperti sekarang (tidak ada kunci `break` di sana).
- Lebih dari satu istirahat per shift, istirahat berbeda per hari, shift lintas tengah malam.
- Mengubah perhitungan absensi (`compute_status`, `deadline`, `exit_early_min`, `AttendanceCloser`). Istirahat tidak
  mempengaruhi status telat, `no_exit`, atau chip Exit awal.
- Penanda "sedang istirahat" di Live View atau daftar zona.
- Pencatatan scan gate selama istirahat dengan pengecualian di hitungan absensi (opsi "gate tetap merekam, kehadiran
  mengabaikan scan istirahat"). Dicatat sebagai follow-up, lihat §9.

### Anti-goals (dianggap gagal walau tampak berfungsi)
- Zona yang memilih **24/7** atau **Jam tertentu** ikut terpengaruh istirahat shift.
- Zona dengan `ignore_break` ikut mati saat istirahat.
- Gate absensi menolak scan di luar jam kerja shift (datang awal, pulang telat, lembur, hari non-kerja).
- Wajah yang lewat saat istirahat pada gate yang patuh istirahat masih menghasilkan event, crop, atau baris absensi.
- Event muncul tepat setelah istirahat berakhir hanya karena frame sebelum istirahat.
- Menyimpan Shift tanpa istirahat mengubah perilaku zona dibanding sebelum fitur ini (selain §5).

## 2. Keputusan Desain

| Keputusan | Pilihan | Sumber |
|---|---|---|
| Letak pengaturan istirahat | halaman Shift, bukan per zona | user |
| Zona yang terpengaruh | semua zona "Ikut shift", apa pun tipenya, kecuali yang dikecualikan | user |
| Loitering/running/idle/crowd/intrusion | jadwal penuh (jam kerja + istirahat) | user |
| Gate absensi | hanya istirahat; jam kerja shift tidak ditegakkan (opsi A) | user, setelah builder check menunjukkan scan datang awal/pulang telat/lembur/shift lain akan hilang |
| Pengecualian per zona | checkbox "Patuhi istirahat shift" (default aktif); data `schedule.ignore_break = true` | user (Cara 1) |
| "Jam tertentu" | tetap tanpa istirahat | user |
| Gate tetap merekam dan hitungan absensi mengabaikan scan istirahat | tidak sekarang, follow-up | user |
| Satu jendela istirahat per shift, `break_start` dan `break_end` opsional, harus terisi berdua atau kosong berdua | usulan | saya |
| Jendela setengah terbuka `[break_start, break_end)` | usulan | saya |
| Syarat: `start_time < break_start < break_end < end_time` | usulan | saya |
| Format kunci ke node: `schedule.break = {"start", "end"}`, kunci dihilangkan bila tanpa istirahat atau zona `ignore_break` | usulan | saya |

## 3. Data & API (backend)

- **Migrasi** `0027_shift_break` (down_revision `0026_audit_log`; builder memverifikasi head terbaru): tambah
  `shift.break_start` dan `shift.break_end`, `String(5)`, nullable, tanpa default. Downgrade menghapus kedua kolom. Harus
  idempoten seperti migrasi lain di repo.
- **Model** `app/models/shift.py`: dua kolom `Mapped[str | None]`.
- **Schema shift** `app/schemas/employee.py`: `ShiftIn`, `ShiftPatch`, `ShiftOut` mendapat `break_start`/`break_end`
  (`str | None`, validasi format `HH:MM` lewat `_validate_time`). Aturan: keduanya terisi atau keduanya kosong; bila terisi
  berlaku syarat urutan di §2.
- **`PATCH /shifts/{id}`** sekarang membuang nilai `null` (semua kolom lama NOT NULL: "null eksplisit diabaikan"). Kolom
  istirahat nullable, jadi `null` eksplisit untuk `break_start`/`break_end` **harus berarti menghapus istirahat**, bukan
  diabaikan. Validasi urutan memakai nilai gabungan (nilai baru + nilai tersimpan), termasuk saat hanya `start_time`/`end_time`
  yang diubah sehingga istirahat lama jatuh di luar jam baru (tolak dengan 422).
- **Schema zona** `app/schemas/zone.py`: `_validate_schedule` menerima `{"shift_id": N}` atau
  `{"shift_id": N, "ignore_break": true|false}` (bool murni, bukan int). Bentuk lain tetap ditolak seperti sekarang.
  `ignore_break: false` boleh diterima dan setara dengan kunci tidak ada.
- Audit `shift.create`/`shift.update` mencatat perubahan kolom istirahat seperti kolom lain.
- `update_shift` sudah memicu `publish_node_config_for_camera` untuk kamera yang zonanya memakai shift itu; pastikan perubahan
  yang hanya menyentuh istirahat ikut memicunya.

## 4. Config Push & Node (vision)

### 4.1 `resolve_schedule()`
Untuk `{"shift_id": N, ...}` hasilnya `{"days", "start", "end"}` seperti sekarang, ditambah `"break": {"start": ..., "end": ...}`
hanya bila shift punya istirahat **dan** zona tidak ber-`ignore_break`. Jadwal "Jam tertentu" dan `null` tidak berubah.

### 4.2 Fungsi cek di node
Tambah `break_active(schedule, ts)` di `base.py`: `True` bila `schedule` punya `break` dan `break.start <= HH:MM < break.end`.
`schedule_active()` memanggilnya setelah cek hari dan jendela kerja yang ada, dan mengembalikan `False` saat istirahat.
Perilaku `schedule=None` (selalu aktif), hari, dan jendela kerja inklusif tidak berubah. Node lama yang belum diperbarui
mengabaikan kunci `break` (tidak error), jadi urutan deploy API dan node bebas.

### 4.3 Analyzer yang sudah memanggil `schedule_active`
`intrusion`, `crowd`, `idle_zone`: tidak ada perubahan kode selain yang terbawa dari §4.2.

### 4.4 Yang baru membaca jadwal
- `LoiteringAnalyzer`, `RunningAnalyzer`: membaca `zone["schedule"]` dan memakai `schedule_active()` (jadwal penuh).
- `FaceGateWorker`: memakai **hanya `break_active()`**, tidak `schedule_active()`. Tanpa kunci `break` (24/7, Jam tertentu,
  shift tanpa istirahat, zona `ignore_break`) gate berperilaku persis seperti sekarang.

Syarat perilaku, cara implementasi diserahkan ke builder:
- Saat off-window (istirahat, atau di luar jadwal untuk analyzer jadwal penuh): tidak ada event, klip, snapshot, Telegram, crop
  wajah, atau baris absensi dari zona itu.
- State yang tertunda tidak boleh "bocor" melewati jendela: dwell loitering, kandidat identifikasi wajah yang sedang
  dikumpulkan, dan track berkecepatan tinggi tidak menghasilkan event setelah istirahat dari data sebelum istirahat.
  Mengikuti pola `intrusion` (state dibekukan; track yang masih di dalam saat jendela tutup tidak mengirim ulang saat buka).
- Untuk gate, melewati inferensi wajah selama istirahat dianjurkan (hemat GPU), asal funnel/heartbeat worker tetap normal.
- Satu kamera gate bisa punya beberapa zona; istirahat berlaku per zona, bukan per kamera.
- Mode uji zona (`test_until`) tidak berubah dan tidak bergantung pada jadwal.

## 5. Dampak ke Zona yang Sudah Ada & Rollout

- **Gate absensi:** zona gate yang sudah memilih "Ikut shift" tidak berubah perilakunya sampai shift-nya diberi istirahat, dan
  hanya jendela istirahat yang berlaku. Tidak ada risiko jam kerja bagi gate.
- **Loitering dan running:** zona jenis ini yang sekarang punya `schedule` terisi (Jam tertentu atau Ikut shift) selama ini
  diam-diam aktif 24 jam. Setelah fitur ini mereka mulai berhenti di luar jam tersebut. Itu disengaja (keputusan user) tetapi
  harus diketahui sebelum deploy.
- Langkah sebelum deploy ke server: jalankan daftar zona ber-jadwal per tipe (`SELECT id, name, type, schedule FROM zone WHERE
  schedule IS NOT NULL`) dan tinjau bersama user. Tambahkan langkah ini ke runbook rollout.
- Urutan: migrasi → API → node (tiga-tiganya aman bila terbalik, node lama hanya mengabaikan `break`).
- Rollback: kembalikan commit; `alembic downgrade` menghapus nilai istirahat saja (data shift lain utuh). Zona loitering/
  running kembali tidak patuh jadwal; kunci `ignore_break` yang sudah tersimpan di zona tidak berbahaya dan diabaikan.

## 6. UI (frontend)

- `ShiftsTab.tsx`: dua isian waktu opsional (mulai dan selesai istirahat) dengan gaya sama dengan isian jam mulai/selesai;
  kosong berarti tanpa istirahat. Error 422 memakai pola `SHIFT_ERRORS` yang ada. Tabel Shift menampilkan istirahat.
- `ZonesPage.tsx`:
  - Label dropdown "Ikut shift" menjadi `Nama (HH:MM–HH:MM)` ditambah `, istirahat HH:MM–HH:MM` bila ada.
  - Checkbox **"Patuhi istirahat shift"** tampil hanya bila jadwal "Ikut shift" dipilih dan shift terpilih punya istirahat.
    Default aktif; mematikannya menyimpan `ignore_break: true`, menyalakannya kembali menghapus kunci itu. Berlaku untuk semua
    tipe zona, termasuk gate.
  - Menyimpan zona tidak boleh menjatuhkan atau mengubah `ignore_break` yang ada ketika admin hanya mengubah field lain, dan
    mengganti shift terpilih mempertahankan nilai checkbox.
- `src/api/employees.ts`: tipe `Shift` dan `ShiftPayload` mendapat `break_start`/`break_end` (nullable). Tipe `Schedule`
  zona di `src/api/*` mendapat varian `{shift_id, ignore_break?}`.
- Semua teks baru lewat `src/app/i18n.tsx`. Tidak ada overflow horizontal di 390 px.

## 7. Pengujian

Tes harus gagal pada bug yang masuk akal, bukan mengunci implementasi.
- **Vision**: `schedule_active` dengan istirahat — tepat di `break.start` (False), satu menit sebelum (True), tepat di
  `break.end` (True), tanpa kunci `break` (perilaku lama). `break_active` terpisah dari jam kerja. Tes per analyzer baru:
  loitering/running tidak menghasilkan output di luar jadwal/istirahat dan tidak ada output tertunda setelah istirahat; gate
  berhenti saat istirahat, tetap menerima scan sebelum `start_time` dan sesudah `end_time` shift, dan tanpa `break` identik
  dengan perilaku sekarang.
- **Backend**: validasi urutan dan pasangan (isi satu saja → 422), PATCH `null` menghapus istirahat, PATCH jam kerja yang
  membuat istirahat lama di luar rentang → 422, `resolve_schedule` memuat/menghilangkan `break` (termasuk zona `ignore_break`),
  validator zona menerima `ignore_break` bool dan menolak non-bool atau kunci asing, edit istirahat memicu config push,
  migrasi naik-turun.
- **Frontend**: form menyimpan dan menghapus istirahat, label dropdown zona memuat istirahat, checkbox hanya tampil untuk shift
  beristirahat dan menyimpan/menghapus `ignore_break`.

## 8. Dokumentasi yang Diperbarui

`WORKFLOW.md` (§6 jadwal zona dan checkbox, §11 form Shift, catatan gate hanya patuh istirahat dan "Jam tertentu" tidak
berlaku untuk gate), `ARCHITECTURE.md` (kolom `shift`, semantik jadwal, daftar analyzer yang patuh jadwal), `README.md` bila
memuat daftar fitur, `ROADMAP.md`, `CHANGELOG.md` (konteks, file, bukti, dampak, rollback), runbook rollout (langkah §5).
Catatan kode lama yang menyebut jadwal hanya untuk sebagian analyzer diperbaiki.

## 9. Diserahkan ke Builder & Catatan Terbuka

- Titik pasti penyaringan jadwal di `FaceGateWorker`, `loitering`, `running` (selama §4.4 terpenuhi).
- Komponen input waktu dan checkbox (ikuti komponen Carbon yang sudah dipakai form terkait).
- Kunci i18n dan teks Indonesia/Inggris sesuai pola `i18n.tsx`.
- Verifikasi nomor migrasi dan `down_revision` terhadap head terbaru.
- **Batas yang diketahui:** karyawan yang tiba saat istirahat pada gate yang patuh istirahat tidak tercatat masuk (bisa menjadi
  `no_entry`/`absent` sampai dikoreksi admin). Satu zona hanya mengikuti satu shift, jadi karyawan shift lain di kamera yang
  sama ikut terblokir saat istirahat shift zona itu; gate seperti itu sebaiknya tidak memakai "Ikut shift" atau memakai
  `ignore_break`. Dokumentasikan keduanya di `WORKFLOW.md`.
- **Follow-up:** gate tetap merekam dan hitungan kehadiran mengabaikan scan istirahat (kecuali entry pertama hari itu).
  Spec dan siklus tersendiri karena mengubah `attendance.py`.
- Belum diuji di server nyata: perilaku gate di sekitar batas istirahat dengan kamera sungguhan. Verifikasi live adalah langkah
  terpisah setelah merge, sesuai alur deploy repo.
