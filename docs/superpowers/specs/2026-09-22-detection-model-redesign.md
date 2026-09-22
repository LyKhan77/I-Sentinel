# Spec draft — Redesign "Detection & Model" (zona trigger, attendance face-first, clip, motion gate)

Status: **DRAFT untuk diskusi** (2026-09-22). Belum jadi plan; menunggu keputusan user.
Referensi UI: `mockup-ui/06-configuration.html` (tab **Deteksi & Model**).
Referensi arsitektur: `/Users/leekhan/project/frigate` (commit `af0ba1919`).

---

## 1. Tujuan yang diminta user

1. Tab baru **Deteksi & Model** di Configuration (per mockup 06).
2. Pisahkan dua keluarga deteksi secara eksplisit:
   - **Attendance** → berdasarkan **wajah** (face recognition + enrollment). Tanpa
     person tracking, tanpa clip, menampilkan **bbox wajah + face crop**; wajah tak
     dikenal tetap menghasilkan event dengan crop berlabel *unknown*.
   - **Behavior** → berdasarkan **person** (intrusion, running, loitering).
     Analitik inilah yang memakai tracking + snapshot + clip.
3. Istilah zona: `dwell_seconds` → **Trigger threshold** (detik): event
   (dan snapshot+clip) baru terbit setelah ambang ini lewat di dalam zona.
4. Zone `type` disederhanakan → **Attendance** | **Behavior**.
5. Behavior diaktifkan/dimatikan **per kamera** dari tab Deteksi & Model.
6. Clip harus ikut track yang memicu (bukan klip kosong); snapshot & clip harus
   dari **momen trigger yang sama**.
7. Debugger Live View: toggle "Show person bbox" → **"Show detection overlay"**;
   kamera attendance menampilkan **bbox wajah**, kamera behavior **bbox person**.
8. Deteksi hanya berjalan lewat **motion gate** (analisis bila ada gerakan).

---

## 2. Temuan teknis hari ini (fakta, sudah diverifikasi)

| # | Temuan | Bukti |
|---|---|---|
| 1 | Overlay deteksi tidak pernah sampai browser karena **proxy Vite tanpa `ws: true`** | `ws://localhost:5173/api/v1/ws/events` → timeout; `ws://localhost:8000/...` → connect OK; MQTT `isentinel/detections/server` disuntik → diterima WS. **Sudah diperbaiki** (commit `79a7a90`) dan diverifikasi lewat `:5173` |
| 2 | **Clip = post-event saja** (`go2rtc stream.mp4?duration=30`), sehingga orang yang sudah lewat tidak ada di klip | `vision/vision/recorder.py:_save_clip`; ukuran klip 155–290 KB (scene kosong) padahal snapshot 69–77 KB berisi orang |
| 3 | Crop attendance diambil dari **fetch live main stream** (keyframe bisa 2–4 s basi) sedangkan bbox dari frame substream saat deteksi → crop kadang lantai | crop `#4647` benar (`face_quality=0.78`), `#4650` lantai; snapshot selalu benar (dari ring substream) |
| 4 | Attendance sekarang **person-first**: YOLO person → ByteTrack → centroid zona → crop upper body → embed wajah. Wajah dideteksi di dalam crop, bukan per frame | `vision/vision/node.py:_attach_crop`, `vision/vision/analyzers/face_gate.py` |
| 5 | Kondisi server saat ini: kamera enabled 357/358/362/363/364 (364 **tidak punya stream** → worker mati), zona aktif hanya `zone 6` cam357 dengan `type=restricted`, `dwell=5` (diubah user) → **tidak ada zona attendance aktif** | heartbeat node + `build_node_config` |
| 6 | Detections MQTT terbit **hanya saat ada track** (`if tracks and transport`) — benar secara desain, tapi verifikasi overlay butuh orang di depan kamera | `vision/vision/node.py:124` |

### Referensi Frigate (pola yang layak diadopsi)

| Konsep Frigate | Isi | Relevansi I-Sentinel |
|---|---|---|
| `Zone.inertia` (default 3) | jumlah **frame berurutan** objek di zona sebelum dianggap hadir; "helps filter out transient detections" | ini persis "Trigger threshold" (versi detik) |
| `Zone.loitering_time` | detik diam di zona → status loitering | konsep loitering terpisah dari inertia |
| `ImprovedMotionDetector` + `motion.{threshold,contour_area,improve_contrast,mask}` | deteksi gerak dulu; YOLO hanya jalan pada region yang bergerak; objek diam di-re-detect periodik (`stationary_frame_counter`) | dasar **motion gate** |
| `record.{alerts,detections}.pre_capture` (default 5 s) & `post_capture` (5 s) | rekaman **segmen kontinu**, klip event dipotong dari cache segmen → ada pre-roll | solusi klip "orang terlihat" |
| `embeddings/` (face recognition) | modul terpisah dari detektor objek | memperkuat attendance face-first |

Estimasi biaya motion gate: sekarang 5 fps × N kamera selalu inferensi YOLO.
Dengan gate, inferensi hanya pada frame bergerak (koridor kosong → hampir 0) —
penghematan GPU terbesar, mengingat 4 kamera aktif + rencana 10+.

---

## 3. Rancangan usulan (per aspek, beserta trade-off)

### 3.1 Model data zona

```
zone.type        : "attendance" | "behavior"        (dari: absensi|restricted|free)
zone.behaviors   : ["intrusion","loitering","running"]   (multi, hanya utk behavior)
zone.trigger_seconds : int (0 = langsung)            (rename dari dwell_seconds)
zone.loiter_seconds  : ???  → lihat Pertanyaan 2
zone.speed_limit_mps, zone.direction, schedule, severity, rate_limit_min, snapshot, clip, telegram: tetap
```

Catatan `free`: zona tanpa analyzer (hanya untuk visualisasi) bisa tetap ada
sebagai `behavior` dengan `behaviors: []`.

### 3.2 Tab "Deteksi & Model" (mockup 06)

- **Global (berlaku semua kamera kecuali dioverride)**: model, AI FPS default,
  confidence default, tracker, **motion gate** (on/off + threshold global).
- **Tabel per kamera**: `AI FPS` | `CONFIDENCE` | `ANALYZER AKTIF` (chips
  intrusion/loitering/running) | aksi.
- Field backend yang perlu ditambah: `camera.ai_fps`, `camera.confidence`
  (nullable = pakai global), `camera.analyzers` (JSON list), plus global
  `detector.conf/imgsz/nms/model` + `motion.*` yang mendorong `config_push`.
- Sumber data model/device: `node.hw` + `node.modules` (sudah ada) → tile status.
- Efek: semua analyzer mati = kamera hanya live view (hemat GPU) — sesuai hint mockup.

### 3.3 Attendance (face-first)

```
frame substream (motion-gated)
  └─ face detector (InsightFace det/SCRFD) → daftar wajah (bbox + det_score)
       └─ centroid wajah di polygon zona attendance
            └─ hadir ≥ trigger_seconds  → event 'attendance'
                 ├─ crop = potongan bbox wajah dari frame yang SAMA (bukan fetch live)
                 ├─ embedding → match gallery (threshold 0.40, quality ≥ 0.5)
                 │     ├─ match  → label nama + employee_id, attendance_event + rekap
                 │     └─ tidak  → label "unknown" (event tetap terbit, crop disimpan)
                 └─ snapshot = frame ring + bbox wajah (opsional, konteks ruangan)
                 └─ clip: TIDAK (sesuai permintaan)
```

Konsekuensi teknis:
- Node perlu **face detector per frame** (bukan hanya saat crop) untuk kamera
  attendance. Beban: SCRFD 500M pada 640×480 @5 fps — ringan, tapi GPU face
  (`cuda:2`) ikut terpakai terus (sebelumnya hanya saat crop).
- Cooldown per `employee_id` (mis. 5 menit) supaya tidak spam event saat orang
  berdiri di gate.
- Zona attendance cukup **satu polygon**; `direction` (entry/exit) tetap dipakai
  untuk rekap harian; boleh dua zona di satu kamera (atas/bawah) atau dua kamera.
- Overlay debugger untuk kamera ini = bbox **wajah** + label nama/unknown.

### 3.4 Behavior (person) + clip

- Analyzer per kamera (chips) × area zona; `trigger_seconds` menahan emit
  (snapshot+clip diambil saat trigger).
- **Clip**: tiga opsi (Pertanyaan 3):
  - A. **Segment cache** (pola Frigate): ffmpeg menulis segmen bergulir (mis. 10 s)
    ke RAM/disk; saat event → potong `[t−pre, t+post]` jadi satu mp4. Pre-roll
    pasti, resolusi konsisten, biaya disk hanya cache + klip event.
  - B. **Ring frame memori** (yang sudah ada, 40 frame ≈ 8 s) + go2rtc post-event:
    murah, tanpa disk kontinu, tapi sambungan pre/post berubah fps/resolusi.
  - C. Tetap post-only (sekarang) — tidak menyelesaikan keluhan klip kosong.
- Stream untuk klip: substream (640×480, hemat) vs **mainstream** (sesuai mockup
  "PATH CLIPS (MAINSTREAM)", 1080p, ~6× penyimpanan).

### 3.5 Motion gate

- Hitung gerak pada frame substream yang di-downscale (mis. 320×180 grayscale,
  `absdiff` frame sebelumnya, threshold + operasi morfologi, hitung rasio piksel
  berubah / `contour_area`).
- Bila gerak < threshold → **lewati inferensi** untuk frame itu; tetap kirim
  frame ke tracker/recorder (ring buffer snapshot tetap hidup) dan periodik
  (mis. tiap 2 s) paksa inferensi agar objek diam tidak hilang.
- Konfigurasi: `motion.enabled` (global + per kamera), `motion.threshold`,
  `motion.min_area`, opsional `motion.mask` (polygon area yang diabaikan,
  mis. pohon/layar bergerak).
- Dampak: event `person_detect`/track baru bisa sedikit tertunda (menunggu
  gerakan) — perlu diukur.

### 3.6 Debugger Live View

- Payload detections MQTT diperluas: `{"kind": "person"|"face", "items": [{id,bbox_norm,label?}]}`
  (atau `boxes` + `faces` terpisah).
- Toggle UI: **"Tampilkan deteksi"** (ganti "Tampilkan bbox person"), tetap ada
  toggle "Tampilkan zona".
- Label: behavior → `ID n`; attendance → nama karyawan / `unknown`.

---

## 4. Pertanyaan terbuka (ditunggu jawabannya)

1. **Kepemilikan toggle behavior**: per kamera (mockup) atau per zona, atau
   keduanya (kamera = master on/off, zona = area + parameter)?
2. **Trigger threshold vs loiter**: satu field `trigger_seconds` untuk semua zona
   (loitering = behavior dengan threshold itu) atau `loiter_seconds` tetap
   terpisah?
3. **Strategi klip**: opsi A (segment cache + cut), B (ring frame + post), atau C
   (tetap post-only)? Dan stream klip: substream atau mainstream?
4. **Attendance**: face detector per frame (face-first penuh) atau pertahankan
   person→crop→embed dengan perbaikan timing crop saja?

---

## 5. Dampak implementasi (kasar, untuk perencanaan)

- Migration: rename/ubah `zone.type` + `zone.dwell_seconds` → `trigger_seconds`,
  JSON `zone.behaviors`; `camera.ai_fps|confidence|analyzers`; settings motion.
- `config_push`: payload zona + kamera berubah → node perlu versi baru
  (`vision` parsing behaviors, trigger, motion).
- Analyzer baru di vision: `face_gate` diganti `attendance_face` (face detector
  per frame), `motion_gate` di worker, dan perubahan `recorder` untuk klip.
- Frontend: tab Deteksi & Model, ZonesPage (type+behaviors+trigger), GatesPage
  (attendance), EventsPage (label unknown, tanpa tab clip untuk attendance),
  Live View (toggle deteksi + render bbox wajah).
- i18n EN/ID, tests (backend pytest, vision pytest, vitest), CHANGELOG, deploy.
