# Face ID pada intrusion critical — desain

Tanggal: 2026-10-08. Branch: `feat/intrusion-face-id` (dari `main` @ `7e5d39c`).
Status: **draf untuk review user**. Belum ada kode. Rencana kerja: `docs/superpowers/plans/2026-10-08-intrusion-face-id.md`.

## 1. Tujuan dan keberhasilan

Saat orang masuk zona intrusion `critical` dan alert Telegram terkirim, beberapa detik kemudian caption alert yang sama diedit dengan identitas orang itu bila wajahnya terlihat. Penerima alert (satpam/IT) memakai nama untuk **triage cepat**: nama karyawan berarti kemungkinan sah, tidak dikenal berarti perlu ditanggapi.

Konsekuensi dari tujuan triage cepat:
- Alert **tidak pernah ditunda atau disupresi**. Identitas hanya informasi tambahan, bukan whitelist.
- Salah-cocok (orang A tampil sebagai karyawan B) jauh lebih berbahaya daripada "tidak dikenal". Ambang cocok lebih ketat daripada attendance dan keraguan selalu jatuh ke "tidak dikenal".
- Setiap alert yang fitur ini aktif harus berakhir pada salah satu dari empat hasil yang terlihat di caption (§5.1), termasuk saat tidak ada hasil sama sekali (`unverified`).

Keberhasilan v1 (ditetapkan user saat kalibrasi, bukan di dokumen ini): angka penerimaan lapangan di kamera 363 setelah pengukuran kelayakan (§9). Nol salah-orang dalam uji adalah syarat, bukan target.

## 2. Di luar cakupan v1

Supresi atau whitelist alert; penyimpanan crop wajah penyusup; kamera critical tanpa zona attendance (worker wajah belum ada di sana); balasan Telegram untuk alert yang terkirim sebagai teks; fusi multi-kamera; tipe selain `intrusion` (loitering, running); pencocokan ulang dari klip; ambang per zona atau UI ambang; retry berkala edit caption yang gagal.

## 3. Keputusan terkunci (dari diskusi 2026-10-08)

| Keputusan | Pilihan |
|---|---|
| Tujuan | Triage cepat |
| Kamera uji | 363 "Lorong Server", zona 15 "Server" (diubah ke `critical` oleh user hanya saat uji) |
| Pendekatan | A: perluas `FaceGateWorker` yang sudah ada (bukan worker on-demand, bukan dari klip) |
| Embedding | Dihitung di node, dicocokkan di API (pola attendance); tidak pernah disimpan |
| Saklar | `face_id` di behavior `intrusion`, default **mati**, tanpa migrasi data zona |
| Cakupan severity | Hanya `critical` |

## 4. Alur end-to-end

```
CameraWorker (YOLO, substream)
  per frame: track person yang titik kakinya di polygon zona critical+face_id
     -> IntrusionRegistry.touch(zone_id, track_id, bbox_norm, ts)
  analyzer intrusion memicu event (setelah trigger_seconds)
     -> publish_event(ev) seperti sekarang  -> API: alert Telegram (tidak ditunda)
     -> IntrusionRegistry.bind(zone_id, track_id, event_id, ts)

FaceGateWorker (main stream, SCRFD, sudah ada di 363)
  selama registry punya entri segar: motion gate dilewati
  wajah -> dipetakan ke bbox person (kepala di 40% atas) -> gerbang kualitas intrusion
  -> kumpulkan <=min_frames embedding per person -> agregasi
  setelah event terikat: kirim SATU pesan ke isentinel/events/face
     bila min_frames tercapai, ATAU T_id (8 dtk) sejak terikat, ATAU person hilang

API (consumer MQTT)
  pesan face -> embedding di-pop -> pencocokan ketat -> payload.face -> WS {"kind":"face"}
  -> edit caption Telegram (seluruh caption: baris AI + baris identitas)
  fallback: bila tak ada pesan dalam 15 dtk sejak ingest -> payload.face = unverified -> edit caption
```

## 5. Desain

### 5.1 Hasil identitas (kontrak `payload.face`)

`payload.face = {status, reason, employee_id, name, score, margin}` (kunci kosong dihilangkan). Tersimpan lewat merge `ev.payload = {**payload, "face": {...}}` (tanpa migrasi).

| status | Arti | Teks caption (Indonesia) |
|---|---|---|
| `recognized` | cocok ≥ ambang dan margin top-1/top-2 ≥ margin | `Dikenali: <nama>` |
| `unknown` | wajah kualitas cukup, tidak cocok atau margin kurang (`reason`: `no_match`/`ambiguous`) | `Wajah terlihat, tidak dikenali` |
| `not_visible` | tidak ada frame wajah yang lolos gerbang, atau kualitas API kurang (`reason`: `no_face`/`small`/`score`/`yaw`/`pitch`/`blur`/`quality`/`low_quality`) | `Wajah tidak terlihat jelas` |
| `unverified` | tidak ada pesan susulan sama sekali (worker mati, MQTT putus, kamera tanpa worker wajah) | `Identitas tidak terverifikasi` |

Caption tidak memakai kata "penyusup" atau "orang asing". Skor tidak tampil di Telegram.

### 5.2 Node (`vision/vision/`)

Modul baru `intrusion_face.py` (satu berkas, tanpa dependensi CUDA):
- `IntrusionRegistry`: thread-safe, kunci `(zone_id, track_id)`; `touch`, `bind`, `fresh(now)`, `release`. TTL entri 3,0 dtk (sama dengan `max_age_s` tracker; motion gate `CameraWorker` bisa melewatkan frame saat orang diam). Entri yang belum terikat dan basi dibuang (orang keluar sebelum `trigger_seconds`, tidak ada event).
- `associate(face_center_norm, entries)`: murni. Pusat wajah harus di area kepala bbox person (40% atas, diperlebar 10% ke kiri/kanan/atas); bila beberapa cocok, pilih yang pusat kepalanya terdekat; bila tidak ada, `None`.
- `pitch_dev(kps)`: murni. `abs((nose_y − eye_y)/(mouth_y − eye_y) − 0,5)` dari tiga pasang landmark (frontal = 0, fixture tes `FRONTAL` bernilai 0,5 sebelum dikurangi). Penyebut ≤ 0 mengembalikan nilai penolak.
- `IdentCollector`: milik `FaceGateWorker`; per kunci menyimpan vektor, bobot kualitas, dan hitungan penolakan (`small`, `score`, `yaw`, `pitch`, `blur`, `quality`, dan `faces`); `drain(now)` mengembalikan pesan yang siap.

Gerbang kualitas mode intrusion: `gate_code` yang ada dipanggil dengan zona dummy satu frame penuh (cek poligon selalu lolos, `gate_code` tidak diubah), lalu blur (kode yang sama), lalu `pitch_dev ≤ MAX_PITCH` (awal 0,30), lalu `quality(...) ≥ IDENT_MIN_QUALITY` (0,5, sama dengan `face_min_quality` API; ini menutup celah node 80 px/0,6 lawan API 0,5 untuk fitur ini). Hitungan penolakan identitas **dipisah** dari `_funnel` attendance supaya tes lama yang mengunci dict persis tidak berubah.

Perubahan kecil pada kode yang ada:
- `CameraWorker.__init__`: keyword opsional `registry=None, ident_zones=()`. Sebelum analyzer dipanggil, untuk tiap track `misses == 0` yang titik kakinya dalam polygon `ident_zones`: `registry.touch(...)`. Saat event `intrusion` terbit untuk zona itu: `registry.bind(zone_id, ev["payload"]["track_id"], ev["event_id"], frame.ts)`.
- `FaceGateWorker.__init__`: keyword opsional `registry=None`. Pada celah bypass `face_worker.py:115`: `... and not (registry and registry.active(frame.ts))`. Di `_process`, hasil `faces` yang sama dipakai ulang (tanpa SCRFD kedua) oleh `IdentCollector`; pesan yang siap dikirim lewat `transport.publish_face(msg)`.
- `MqttTransport.publish_face(payload)` → `_publish(FACE_TOPIC, payload)` (QoS1, antrean disk seperti event).
- `_start_camera`: hitung `ident_zones` (zona `severity == "critical"` dengan behavior `intrusion` ber-`face_id: true`). Registry hanya dibuat bila ada `ident_zones` **dan** worker wajah ada (`gates` tidak kosong). Bila `ident_zones` ada tetapi `gates` kosong: log peringatan satu kali, fitur tidak aktif untuk kamera itu (API akan menandai `unverified`). Perubahan kunci di dalam behavior memicu restart kamera itu saja (mekanisme apply per kamera yang ada).

Pesan susulan: `{event_id, camera_id, node_id, track_id, embedding|null, quality|null, stats{faces, rejects{...}, frames_used}}`; `embedding` = `aggregate(...)` yang ada, `quality` = kualitas tertinggi frame terpakai. Satu pesan per `event_id`, dikirim setelah event intrusion (urutan MQTT/antrean disk FIFO menjamin event lebih dulu).

### 5.3 API (`backend/app/`)

- `events_consumer.py`: konstanta `FACE_TOPIC = "isentinel/events/face"`, langganan `(FACE_TOPIC, 1)`, cabang `elif topic == FACE_TOPIC` yang memanggil `intrusion_face.handle_face_result(db, data)`. Embedding di-`pop` sebelum apa pun disimpan.
- `services/intrusion_face.py` (baru): `handle_face_result`, `identify(vector, quality)`, `schedule_unverified(event_id)`, `finalize_unverified(event_id)`.
  - Event tidak ditemukan: log peringatan dan buang (tanpa buffer; node selalu mengirim setelah event).
  - Pesan duplikat dengan hasil sama diabaikan. Hasil nyata yang tiba setelah `unverified` menimpa `unverified` dan memicu edit caption lagi.
  - Setelah menyimpan: broadcast WS `{"kind": "face", ...}` (bentuk mengikuti frame `kind: "ai"` di `ai_worker.py`), lalu `alert_ai.sync_face_caption`.
- `services/face.py`: `FaceGallery.top2(vector)` (skor terbaik per karyawan, dua karyawan berbeda teratas) dan `match_strict(vector, quality)` → `MatchResult` dengan alasan `low_quality|no_match|ambiguous|matched`. `matched` hanya bila `top1 ≥ face_id_threshold` **dan** `top1 − top2 ≥ face_id_margin`. Gerbang kualitas memakai `face_min_quality` yang sudah ada.
- `core/config.py`: `face_id_threshold = 0.50`, `face_id_margin = 0.10` (**nilai awal, dikalibrasi lapangan**). `docker/compose.yml`: dua variabel itu **harus** ditambahkan ke anchor `x-api-environment` (`FACE_*` lain tidak diteruskan compose; temuan 2026-10-07) disertai tes guard di `docker/tests/test_compose.py`.
- `schemas/zone.py`: `"face_id"` ditambahkan ke tuple flag boolean (tipe harus bool). Pembacaan: `zone.behavior_flag("intrusion", "face_id", default=False)`.
- `schemas/` : model `FaceResultIn` untuk validasi payload pesan susulan.

Fallback `unverified`: setelah event critical ber-`face_id` ter-ingest dan alert dijadwalkan, `threading.Timer(UNVERIFIED_AFTER_S = 15, ...)` (daemon, sesi DB sendiri) memanggil `finalize_unverified`, yang tidak melakukan apa pun bila `payload.face` sudah ada. `# ponytail: timer hilang bila API restart; upgrade ke sweeper bila terlihat sering`. Tidak ada `Timer` lain di backend; consumer MQTT satu thread, jadi jeda tidak boleh di dalam `handle_message`.

### 5.4 Caption Telegram (`telegram.py`, `alert_ai.py`, `alert_dispatcher.py`)

- `format_caption` menambah baris `("Identitas", ...)` setelah baris Level untuk event `intrusion` yang punya `payload.face`. Tidak ada perubahan pada penganggaran 1024 unit UTF-16 (baris AI tetap satu-satunya yang diperpendek; baris identitas ≤ `FIELD_MAX`).
- Migrasi **0023**: kolom `alert.face_synced` (Boolean, `nullable=False`, `server_default=false`), meniru 0022 dan `test_migration_0022.py`.
- `alert_ai.sync_face_caption(db, event_id)`: guard sama dengan `sync_ai_caption` **tanpa** syarat teks AI; klaim atomik `face_synced`; merender seluruh caption (`build_caption` sudah membaca `payload.face` lewat `format_caption`, dan baris AI bila ada); `_release` bila gagal. `sync_ai_caption` tidak berubah selain ikut merender identitas bila sudah ada.
- **Satu `threading.Lock` modul** mengelilingi klaim + render + edit pada kedua fungsi sync supaya dua edit bersamaan tidak saling menimpa (edit yang lebih awal merender tanpa bagian yang baru tiba, lalu dikirim sesudah edit yang lengkap). Lock tidak menahan transaksi DB (properti `not db.in_transaction()` selama I/O Telegram dipertahankan).
- Dispatcher: bagian identitas yang sudah ada saat caption awal dibangun (`payload.face` pada baris 170) ditandai `face_synced = True`; setelah kirim sukses, `db.refresh(event)` lalu panggil kedua sync (sesi dispatcher memuat event satu kali dengan `expire_on_commit=False`, jadi tanpa refresh hasil yang ditulis thread consumer tak terlihat).
- Alert yang terkirim sebagai teks (`message_photo is not True`) tidak bisa diedit: dilewati dan dicatat `identity_skipped_text_only` di log.

### 5.5 UI (`frontend/src/`)

- `api/zones.ts`: `Behavior.face_id?: boolean`. `ZonesPage.tsx`: `Toggle` `zone-face-id-intrusion` pada behavior `intrusion` (pola `zone-telegram-${kind}`), `toggled={b.face_id ?? false}`, teks bantuan `zones.faceIdHint` (hanya berlaku bila severity `critical` dan kamera punya zona attendance).
- `EventsPage.tsx`: baris identitas di panel detail untuk event yang punya `payload.face` (pola baris `event-face-match`, `data-testid="event-identity"`), menampilkan status, nama, dan skor (skor tampil di Inbox untuk semua peran, bukan di Telegram). Cabang WS `kind === 'face'` memanggil `refresh('merge')`. `asNotifyEvent` sudah mengabaikan frame tanpa `id/event_id/type` sehingga aman.
- i18n: semua string di `i18n.tsx`, kunci di kedua kamus (`id`, `en`): `zones.faceId`, `zones.faceIdHint`, `events.identity`, `events.identity.recognized`, `.unknown`, `.notVisible`, `.unverified`.

## 6. Kegagalan dan kasus tepi

| Kasus | Perilaku |
|---|---|
| Wajah tidak pernah terlihat | Event dan alert tetap; caption diedit `not_visible` |
| Orang keluar sebelum `trigger_seconds` | Tidak ada event; entri registry dibuang |
| Pesan susulan tak datang | `unverified` setelah 15 dtk |
| Alert terkirim sebagai teks | Tidak diedit (dicatat di log) |
| Edit Telegram gagal | Status alert tidak berubah; `_release`; tanpa retry berkala |
| Dua orang di zona | Registry per track; asosiasi memilih bbox terdekat; satu pesan per `event_id` |
| Embedding ambigu antar karyawan | `unknown` (`ambiguous`) |
| Saklar mati / zona bukan critical / kamera tanpa worker wajah | Perilaku sama persis dengan sekarang (tanpa pesan susulan; `unverified` hanya bila saklar hidup) |
| Hasil nyata tiba setelah `unverified` | Menimpa dan mengedit caption lagi |
| API restart saat timer berjalan | Timer hilang; caption tanpa baris identitas (batas v1) |

## 7. Privasi

Embedding tidak pernah masuk DB atau WS (di-`pop` di consumer sebelum penyimpanan). Crop wajah penyusup tidak disimpan di v1; retensi `crops/` tetap khusus attendance. `payload.face` hanya menyimpan status, `employee_id`, nama, skor, dan margin. Nama karyawan masuk Telegram seperti pada CHECK IN attendance. Prompt AI tetap melarang menebak identitas (`ai_prompts.py`), jadi baris AI tidak pernah menyebut nama.

## 8. Konfigurasi dan default

`face_id` per zona: default mati. Konstanta node (`IntrusionRegistry` TTL 3,0 dtk, area kepala 40%, `T_id` 8 dtk, `MAX_PITCH` 0,30, `IDENT_MIN_QUALITY` 0,5) dan API (`face_id_threshold` 0,50, `face_id_margin` 0,10, `UNVERIFIED_AFTER_S` 15 dtk) adalah **nilai awal tanpa data lapangan**. Gerbang lebar/skor/yaw/blur/min_frames memakai `FaceSettings` yang sudah dipush dari UI.

## 9. Pengukuran kelayakan dan kalibrasi

**Tugas 0 (sebelum kode fitur; butuh persetujuan eksplisit sebelum dijalankan di server):** skrip sekali pakai di `temp/` (tidak di-commit) membaca main-stream kamera 363 di container `vision`, menjalankan `FaceEmbedder.detect_faces`, dan mencatat lebar, skor, yaw, pitch, dan blur per frame saat user dan rekan melintas di area zona 15 (menghadap kamera, menyamping, dari belakang, cepat). Keluaran: persen lintasan yang punya ≥1 frame lolos gerbang intrusion. Usulan go/no-go (ditetapkan user): ≥80% lintasan menghadap kamera menghasilkan ≥1 frame lolos. Lintasan dari belakang diharapkan `not_visible` (hasil jujur, bukan kegagalan). Di bawah target: hentikan fitur atau perbaiki geometri kamera dulu.

**Kalibrasi (setelah implementasi, di lapangan):** lintasan karyawan terdaftar dan orang tidak terdaftar dengan skor tersimpan di `payload.face.score`; `face_id_threshold` dan `face_id_margin` dipilih dari sebaran skor genuine lawan impostor; `MAX_PITCH` dari statistik penolakan. Salah-orang harus nol dalam uji. Angka penerimaan lain ditetapkan user saat itu.

## 10. Pengujian

TDD, tiap RED dilihat gagal karena alasan yang benar. Cakupan: node (registry, `associate`, `pitch_dev`, collector: min_frames/jendela/person hilang/embedding null; bypass motion gate; flag mati berarti tanpa pesan; tes lama attendance tidak berubah); API (embedding tidak ada di DB dan WS, `top2`/`match_strict` termasuk ambigu, pemetaan status, `unverified` dan penimpaan, caption berisi AI + identitas pada kedua urutan dan saat bersamaan, alert teks dilewati, `face_synced`, migrasi 0023, langganan topik, guard compose); frontend (toggle, baris detail, cabang WS). Suite dijalankan berurutan (jangan bersamaan). Klaim atomik `face_synced` baru diuji di SQLite; dicek ke Postgres saat deploy.

## 11. Rollout dan rollback

Cabang `feat/intrusion-face-id`; eksekusi native oleh sesi lain, commit lokal, berhenti tanpa push; sesi perencanaan menjalankan ulang suite berurutan, mereview, lalu deploy `api`+`vision`+`web` (`git pull && ./docker/setup.sh`) hanya setelah OK user. Aman secara default (saklar mati). Uji lapangan: user mengubah zona 15 ke `critical` dan menyalakan `face_id` (menulis ke server hanya atas persetujuan eksplisit). Rollback: matikan toggle; atau `git checkout` versi sebelumnya + `./docker/setup.sh` (kolom 0023 aditif, tanpa downgrade).

## 12. Perubahan dari presentasi lisan

1. TTL registry 3,0 dtk (bagian 1 menyebut 0,5 dtk): motion gate bisa melewatkan frame saat orang diam.
2. Aturan "≥2 dari 3 frame" dibuang; `aggregate` yang ada (membuang outlier, bobot kualitas) + ambang + margin sudah menjaga konsistensi.
3. Gerbang kualitas node memakai `quality ≥ 0,5` (sama dengan API) agar frame yang pasti ditolak API tidak lolos node.
4. Skor tampil di detail Inbox untuk semua peran (bagian 3 menyebut admin saja): memeriksa peran di `EventsPage` menambah kerumitan tanpa nilai untuk v1.
5. Pesan susulan dikirim di topik `isentinel/events/face` (bukan memperluas MEDIA): handler MEDIA hanya menerapkan `clip_path`, `snapshot_path`, `clip_offset_s`.

## 13. Risiko dan pertanyaan terbuka

- Kamera critical umumnya melihat dari atas atau samping: `not_visible` bisa dominan. Pengukuran §9 menjawab ini sebelum kode.
- Konkurensi ONNX pada `FaceEmbedder` bersama sudah terjadi di produksi (beberapa `FaceGateWorker`); tidak diverifikasi di internal insightface.
- `ai_fps` kamera 363 dan beban GPU `cuda:2` saat registry aktif belum diukur (hanya selama ada orang di zona).
- Retensi dan kebijakan crop wajah penyusup belum didefinisikan (di luar v1).
