# Spec — Penyempurnaan face gate (Telegram, zona deteksi, kecepatan tercatat)

Status: **Draft, arah disetujui di chat 2026-10-07**, menunggu review spec tertulis.
Branch: `feat/face-gate-refine` (dari `main` @ `dc5e235`).
Konteks: `ARCHITECTURE.md` §3 (node vision), `WORKFLOW.md` §12 (Absensi), `docs/runbooks/attendance.md`.

---

## 1. Latar

Permintaan user (2026-10-07):

1. Pesan Telegram masih menulis "Lihat klip: …"; seharusnya "Lihat event: …".
2. Face recognition terlalu menuntut karyawan menatap CCTV 5–10 detik untuk memastikan absensi tercatat. Ingin
   karyawan cukup lewat, dengan kamera yang menyorot wajah (kondisi ideal).
3. Pesan Telegram untuk karyawan yang **sudah check in hari itu** diberi tanda "sudah check in". Deteksi berikutnya
   hanya berfungsi sebagai evidence, untuk kasus karyawan keluar gedung tanpa exit terlihat lalu tercatat entry dua kali.
4. Zona attendance harus bisa dipakai **hanya sebagai pendeteksi wajah orang yang masuk**, bukan absensi.
5. Opsi zona: matikan pengiriman wajah Unknown ke Telegram (hanya karyawan yang dikirim).

Fakta konteks: belum ada konfirmasi yang dipantau orang di pintu; Telegram menerima wajah masuk apa adanya. Pada tahap
development user mengonfirmasi lewat debugger Live View. Layar konfirmasi gate (mini interface dekat CCTV entry)
direncanakan **nanti**, spec terpisah.

## 2. Temuan kode

| # | Temuan | Lokasi | Dampak |
|---|---|---|---|
| 1 | `should_alert`: attendance `matched` dikirim; `no_match` (Unknown) dikirim dengan rate-limit; `already_in` dan `cooldown` → `attendance_skipped`, tidak ada baris alert | `backend/app/services/alerting.py` | Entry kedua di hari yang sama tidak pernah sampai ke Telegram; bukti hanya ada di Inbox |
| 2 | `handle_face_event` mengecek cooldown (±`attendance_cooldown_min`, per karyawan+arah) lebih dulu, lalu `already_in` (entry sekali per hari; exit boleh berulang) | `backend/app/services/attendance.py:200-206` | Urutan cek menjadi dasar penanda "sudah check in" |
| 3 | Cooldown dan `already_in` bergantung pada baris `AttendanceEvent` | `attendance.py:116-134` | Zona tanpa pencatatan absensi tidak punya dedup; perlu dedup sendiri |
| 4 | `format_caption` membentuk judul (`matched` → CHECK IN/OUT, selain itu UNKNOWN FACE) dan baris `🎥 Lihat klip:` untuk semua tipe | `backend/app/services/telegram.py:229-282` | Teks tautan satu tempat; berlaku semua tipe alert |
| 5 | Face worker emit saat `min_frames` (default 3) frame lolos gerbang, atau saat track hilang bila ≥1 frame lolos; setelah itu track `done`, frame bagus berikutnya dibuang | `vision/vision/face_worker.py:177-217` | Tiga frame pertama biasa-biasa saja → hasil `Unknown` permanen untuk track itu |
| 6 | Frame tanpa gerak dilewati motion gate; `force_interval_s=2.0` memaksa satu inferensi per 2 detik | `face_worker.py:110`, `vision/vision/motion.py` | **Hipotesis (belum terukur):** wajah yang diam (orang berhenti menatap) diproses 1 frame/2 detik; `min_frames=3` butuh sekitar 4–6 detik, sesuai keluhan 5–10 detik |
| 7 | Heartbeat menghitung `motion_skip_pct` hanya untuk worker `detect`; `FaceGateWorker` tidak punya counter `motion_skipped` | `vision/vision/node.py:487-505` | Hipotesis #6 tidak bisa diverifikasi dari data yang ada |
| 8 | Face worker memakai stream main pada `ai_fps` kamera (default 5); SCRFD `det_size=(640,640)` pada seluruh frame | `node.py:425-428`, `vision/vision/face.py:66` | Wajah kecil di frame besar mengecil sebelum dideteksi; angka gerbang (lebar min 80 px) diukur di piksel asli |
| 9 | Zona dipilih untuk face worker lewat `attendance_zones`: wajib `direction` entry/exit **dan** behavior `attendance` | `node.py:205-209` | `direction` tetap wajib untuk zona deteksi-saja |
| 10 | `behaviors` adalah JSON tervalidasi (`_validate_behaviors`); flag boolean baru tidak butuh migrasi | `backend/app/schemas/zone.py` | Flag baru aman untuk zona lama (key hilang = default) |
| 11 | Skor cocok di server 0,714 dan 0,65 dengan ambang 0,40 (dua titik data) | `ROADMAP.md:422` | Ada ruang, tapi belum cukup data untuk mengubah ambang |

## 3. Keputusan user

| Topik | Keputusan |
|---|---|
| Teks Telegram | "Lihat klip" → "Lihat event" (semua tipe alert) |
| Entry berulang | Kirim ke Telegram dengan penanda "sudah check in" + status exit; tiap kali lolos cooldown |
| Zona | Opsi **Catat absensi** (OFF = deteksi saja) dan opsi **kirim Unknown ke Telegram** (OFF = hanya karyawan) |
| Konfirmasi gate | Ditunda; Telegram saja sekarang, layar gate di spec terpisah |
| Trigger/motion | Pemicu tetap pusat bbox wajah di poligon zona; ROI crop ke zona **dicabut** (zona = filter penerimaan kepala yang lewat) |
| Pecahan kerja | Satu spec, urut: Fase 1 Telegram → Fase 2 Catat absensi OFF → Fase 3 kecepatan (3a ukur+tuning, 3b dua-fase bersyarat) |

## 4. Tujuan, kriteria sukses, non-tujuan

**Kriteria sukses** (diuji):

*Fase 1*
1. Caption semua tipe alert memakai `Lihat event:`; emoji 🎥 tetap.
2. Entry kedua hari yang sama di luar cooldown menghasilkan satu alert Telegram berjudul "SUDAH CHECK IN" dengan jam
   check in pertama dan status exit; tidak ada `AttendanceEvent` baru; `attendance_day` tidak berubah.
3. Entry kedua di dalam cooldown tetap diam.
4. Dengan `telegram_unknown=false`, wajah Unknown tidak menjadi alert tetapi tetap menjadi Event di Inbox dengan snapshot
   berlabel Unknown; `matched` tetap terkirim.
5. Zona lama tanpa flag baru berperilaku sama seperti sekarang, kecuali butir 2.

*Fase 2*
6. Zona dengan `record=false`: tidak ada `AttendanceEvent` dan tidak ada perubahan `attendance_day`; satu alert
   `detected` per (karyawan, zona) per jendela cooldown; Unknown tunduk pada `telegram_unknown`.
7. `record=true` (default) identik dengan perilaku sebelum fase ini.

*Fase 3a*
8. Wajah yang diam di zona diproses pada `ai_fps` penuh, bukan 1 frame/2 detik.
9. Heartbeat worker face membawa corong: frame terproses, frame dilewati motion gate, wajah terdeteksi, penolakan per
   kode gerbang (`zone/small/score/yaw/blur`), track emit, track berakhir tanpa frame lolos, median waktu ke frame
   lolos pertama.
10. Uji penerimaan di server (§5.3 butir 4) dijalankan dan angkanya dicatat di CHANGELOG.

**Non-tujuan:** layar konfirmasi gate; fusi lintas kamera; ROI crop ke zona; pemicu person-YOLO; gallery wajah di node;
throttle tambahan untuk `already_in`; perubahan ambang cosine atau gerbang kualitas tanpa data uji; UI untuk corong.

## 5. Desain

### 5.1 Fase 1 — Telegram

**Teks tautan.** `format_caption`: `Lihat klip:` → `Lihat event:`.

**Evidence `already_in`.**
- `handle_face_event`, cabang `already_in`: isi `payload["first_entry_ts"]` (ts entry paling awal hari lokal itu) dan
  `payload["exit_ts"]` (exit terakhir antara entry pertama dan event ini; tidak ada kunci bila belum ada). Sumber: baris
  `AttendanceEvent` karyawan itu, dengan gaya query yang sama seperti `_entered_earlier_today` (helper bool diganti
  helper yang mengembalikan entry pertama hari itu; semantik bool tidak berubah).
- Urutan cek tetap: cooldown (diam) → `already_in`.
- `should_alert`: `match_reason == "already_in"` → `(True, "")` setelah `_telegram_on`; melewati rate-limit generik
  karena duplikat sudah ditahan cooldown.
- `format_caption`: judul `🔁 <b>ATTENDANCE — SUDAH CHECK IN</b>`; baris Nama, Check in pertama (jam lokal), Exit
  sejak itu (`belum terlihat` atau jam), Kamera, Zona, Waktu.
- Inbox tidak berubah: event `already_in` sudah ada dengan snapshot berlabel nama.

**Toggle `telegram_unknown`.** Flag boolean pada behavior `attendance` (key hilang = `true`). Divalidasi di
`_validate_behaviors`. `should_alert`: event attendance `no_match` dan flag `false` → `(False, "attendance_skipped")`.
`telegram` pada behavior tetap saklar induk. UI: toggle di editor zona (muncul bila Telegram aktif), string lewat
`src/app/i18n.tsx`.

### 5.2 Fase 2 — Catat absensi OFF

- Flag `record` (boolean, default `true`) pada behavior `attendance`; validator sama. `direction` tetap wajib (§2 #9) dan
  dipakai untuk label arah.
- `handle_face_event` membaca zona (`db.get(Zone, event.zone_id)`). Zona pra-R5 (`behaviors` null) dan key hilang → `record=true`.
- Bila OFF: match, label snapshot, dan anotasi crop berjalan seperti biasa; **tidak** ada `AttendanceEvent` dan tidak
  ada `recompute_day`. Dedup per (karyawan, zona): bila ada event attendance lain di zona yang sama dalam
  ±`attendance_cooldown_min` dengan `payload.employee_id` sama → `match_reason="cooldown"`; selain itu
  `match_reason="detected"`.
  Query berdasarkan `Event.zone_id` + jendela `ts_event`, filter payload di Python (ponytail: data kecil per zona;
  indeks bila volume tumbuh).
- Alert: `detected` → `should_alert` True setelah saklar. Judul `👤 <b>TERDETEKSI — MASUK|KELUAR</b>` dengan Nama;
  tanpa kata CHECK IN. `no_match` mengikuti `telegram_unknown`.
- UI: toggle "Catat absensi" pada behavior attendance dengan teks bantu saat OFF; Inbox menampilkan label untuk
  `match_reason="detected"`; i18n.
- Tidak berubah: halaman Attendance, `attendance_day`, `AttendanceCloser`. Karyawan yang hanya terlihat di zona OFF
  tetap dihitung berdasarkan zona yang mencatat; ini disengaja.

### 5.3 Fase 3a — Ukur dan tuning (tanpa perubahan protokol)

1. **Kehadiran menopang motion gate.** `FaceGateWorker.run`: frame tanpa gerak tetap diproses bila frame yang diproses
   sebelumnya berisi wajah (`_faces_shown`). Gerak membangunkan, kehadiran wajah mempertahankan. Satu kondisi di
   `face_worker.py:110`. Bila wajah menghilang, gate kembali normal. Pelepasan manual tetap lewat toggle motion per kamera.
2. **Corong di node.** Counter kumulatif di `FaceGateWorker` (`motion_skipped`, `faces`, `rejects{kode}`,
   `tracks_emitted`, `tracks_silent`, waktu-ke-frame-lolos-pertama); `_camera_stats` mengirim delta per jendela
   heartbeat dalam objek `funnel` pada entri worker `face`, dan `motion_skip_pct` juga dihitung untuk worker face.
   API meneruskan lewat endpoint monitoring yang sudah ada; rincian penyimpanan heartbeat diverifikasi di plan.
   Tidak ada UI.
3. **Tuning.** Parameter global yang ada (`min_frames`, `max_yaw`, `min_width_px`, `blur_min`, `min_det_score`) disetel
   dari data corong dan uji penerimaan; spec ini tidak menetapkan angka baru. Opsi `det_size` lebih besar hanya bila
   penolakan `small` dominan.
4. **Uji penerimaan (server, kamera ideal).** 10 karyawan × 5 lintasan, jalan normal tanpa menoleh. Target: ≥95%
   tercatat benar, ≤2 detik dari wajah muncul sampai event tercatat, nol salah-orang. Setiap perubahan ambang
   diulang uji ini.
5. **Runbook (`docs/runbooks/attendance.md`).**
   - Gambar zona cukup lebar agar wajah yang berjalan berada di dalamnya ≥1 detik (≈5 frame pada `ai_fps` 5).
   - Checklist kamera: shutter ≥1/250, WDR/BLC bila pintu membelakangi cahaya, tinggi mata sampai sedikit di atasnya,
     zona 2–4 m sebelum pintu.
   - Enrollment dari kamera gate sendiri bila skor kurang.

**Dicabut dari rencana: ROI crop ke zona.** Zona digambar kecil di area kepala dan berfungsi sebagai filter penerimaan.
Deteksi dan tracking harus lebih lebar dari zona agar track sudah ada sebelum wajah masuk. Pemicu tetap pusat bbox wajah
di poligon (setara titik kaki untuk orang).

### 5.4 Fase 3b — Commit dua fase (bersyarat, go/no-go setelah 3a)

**Go** hanya bila uji penerimaan di bawah target **dan** corong menunjukkan bukti lemah atau terlambat (bukan masalah
zona atau kamera). Sketsa, dirinci di plan bila go:

- Node mengirim event `phase="early"` pada frame lolos pertama dan `phase="final"` saat track berakhir (aggregate
  embedding). `dedup_key` memakai akhiran fase.
- API: `early` dengan skor ≥ `T_commit` dan unggul dari kandidat kedua → langsung dicatat. Selain itu
  `match_reason="provisional"` tanpa label Unknown dan tanpa alert. `final` mencari `early` track yang sama
  (kamera + `track_id`, ±30 detik, filter Python) dan **memperbarui baris itu di tempat** (embedding, media, hasil), lalu
  memutuskan `matched`/`no_match`. Tanpa `early` yang ditemukan, `final` diproses sebagai event biasa.
- Cooldown mencegah dobel absensi dan dobel Telegram; `early` yang tidak pernah disusul `final` dibiarkan `provisional`
  (tanpa timer).
- `T_commit` dan margin ditentukan dari data uji, bukan tebakan.

## 6. Tes

Mengikuti pola berkas tes yang ada per lapis (backend `pytest -m "not gpu"`, vision `pytest -m "not gpu"`, frontend `vitest`).
Tiap tes harus gagal pada bug yang masuk akal:

- Fase 1: caption `Lihat event:`; caption `already_in` memuat check in pertama dan status exit; `should_alert` meloloskan
  `already_in`, menahan Unknown saat `telegram_unknown=false`, tetap mengirim `matched`; cooldown tetap diam; payload
  `first_entry_ts`/`exit_ts`; validator menolak flag non-boolean. Tes lama `test_telegram.py:85,112,232` diperbarui
  untuk teks tautan.
- Fase 2: `record=false` tidak membuat `AttendanceEvent` dan tidak mengubah `attendance_day`; dedup per (karyawan, zona);
  `detected` mengirim alert; default identik dengan sekarang; UI toggle dan label Inbox.
- Fase 3a: dengan source palsu, wajah diam diproses pada laju penuh; counter corong naik sesuai kode gerbang; entri
  heartbeat membawa `funnel`.

## 7. Dokumen

Per commit fungsional: `CHANGELOG.md` (konteks, berkas, bukti, dampak, rollback). Saat fitur selesai: `WORKFLOW.md`
(§12 Absensi, bagian Telegram dan zona), `ARCHITECTURE.md` (kontrak alert, heartbeat `funnel`), `docs/runbooks/attendance.md`,
`ROADMAP.md` (siklus baru). Spec lama yang menyebut "Lihat klip" adalah catatan dan tidak diubah.

## 8. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| `already_in` ramai bila orang melintasi zona berulang dengan jeda >5 menit | Dipantau saat uji; throttle tambahan hanya bila terbukti perlu |
| Zona OFF membanjiri Telegram karena karyawan sering lewat | Dedup per (karyawan, zona) dan saklar `telegram` induk |
| Salah-orang bila ambang/gerbang dilonggarkan | Tidak ada perubahan angka tanpa uji penerimaan; syarat nol salah-orang |
| "Kehadiran menopang" membuat gate selalu aktif pada wajah latar (poster/cermin) | Biaya GPU saja; toggle motion per kamera tetap ada |

Rollback: tiap fase commit terpisah, flag default = perilaku lama, key JSON baru diabaikan API lama, tanpa migrasi.
Deploy: rebuild container `api` (Fase 1–2), `vision` (Fase 3a); `docker compose up -d`, bukan hanya `restart`.

## 9. Keputusan yang saya ambil sendiri (koreksi saat review)

- `direction` **tetap wajib** pada zona deteksi-saja (usulan chat sebelumnya "opsional"). Node memilih zona gate
  dengan `direction`, dan arah dipakai untuk label pesan.
- `already_in` melewati rate-limit generik karena cooldown sudah menahan duplikat.
- Corong hanya di heartbeat/API, tanpa UI.
- ROI crop dicabut; hangover motion diganti aturan "kehadiran menopang" (lebih sederhana dan menutup kasus orang berhenti).
- Fase 3b bersyarat, bukan otomatis.
