# R5a — Zone behaviors, tab Detection & Model, motion gate, detection overlay

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zona berbahasa baru (Attendance | Behavior dengan threshold per behavior), kamera punya master analyzer + AI FPS/confidence, node hanya menganalisis saat ada gerakan (motion gate), dan modal debugger Live View menampilkan deteksi (person/face) — bukan hanya zona.

**Architecture:** `zone.behaviors` (JSON, daftar behavior dengan `trigger_seconds` masing-masing) menggantikan `type=restricted/free` + `dwell_seconds` + `loiter_seconds` + `speed_limit_mps`; `zone.type` tinggal `attendance|behavior`. Kamera mendapat override `ai_fps`, `confidence`, `analyzers` (chips master), `motion_enabled`; setelan global (motion + default) tersimpan di tabel singleton `detector_setting` dan ikut `config_push`. Node: motion gate di depan detektor; `publish_detections` membawa `kind` (`person`/`face`) sehingga overlay bisa membedakan kamera behavior vs attendance.

**Tech Stack:** existing — SQLAlchemy/Alembic expand-only, Pydantic v2, SQLAlchemy JSON, FastAPI, MQTT config push, vision node (NumPy/OpenCV/ByteTrack), React 19 + Carbon + Vitest.

**Branch:** `feat/detection-model` (stack di atas `feat/events-dwell-crop`)

**Spec (latar + referensi Frigate):** `docs/superpowers/specs/2026-09-22-detection-model-redesign.md`

**Keputusan user yang sudah dikunci:**
1. Behavior: **kamera master** (chips per kamera) + **zona parameter** (area & threshold).
2. Threshold: **per behavior, satu semantik** (`trigger_seconds`; `loiter_seconds` dihapus, dimigrasi).
3. Klip: **segment cache substream** → dikerjakan di plan R5c (bukan di plan ini).
4. Attendance: **face-first di substream** → dikerjakan di plan R5b (bukan di plan ini).
5. Attendance tanpa clip, **snapshot konteks + crop wajah** tetap.
6. Motion gate: **on default, override per kamera**; mask area menyusul bila perlu.
7. Threshold global di **blok Advanced collapsible** tab Detection & Model.

**Urutan eksekusi:** Task 1–5 = fondasi data + node + overlay (bisa dites lokal), Task 6–10 = API + UI + deploy.

---

### Task 1: Model & migration 0014 — `zone.behaviors`, `camera` setting deteksi

**Files:**
- Create: `backend/alembic/versions/0014_zone_behaviors.py`
- Modify: `backend/app/models/zone.py`, `backend/app/models/camera.py`
- Modify: `backend/app/schemas/zone.py`
- Test: `backend/tests/test_zones_api.py`, `backend/tests/test_models.py`

**Desain kolom (expand-only — kolom lama TIDAK dihapus, ditandai deprecated):**

```python
# zone (baru)
behaviors: Mapped[list] = mapped_column(JSON, default=list)       # [{"kind","trigger_seconds", ...}]
trigger_seconds: Mapped[int] = mapped_column(Integer, default=0)  # attendance: lama di zona sebelum trigger
# zone (deprecated, tetap ada utk rollback): type absensi|restricted|free tetap valid dibaca,
#   dwell_seconds, loiter_seconds, speed_limit_mps tetap ada
# camera (baru)
ai_fps: Mapped[float | None] = mapped_column(Float, nullable=True)        # None = global
confidence: Mapped[float | None] = mapped_column(Float, nullable=True)    # None = global
analyzers: Mapped[list | None] = mapped_column(JSON, nullable=True)       # ["intrusion","loitering","running","attendance"]; None = semua
motion_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None = global
```

`zone.behaviors` entry: `{"kind": "intrusion"|"loitering"|"running", "trigger_seconds": int}`,
plus `"speed_limit_mps": float` khusus `running`. `zone.type`: `"attendance" | "behavior"`
(+ nilai lama tetap dibaca saat migrasi).

- [ ] **Step 1: test migrasi data (merah)** — tulis `backend/tests/test_zones_api.py::test_zone_behaviors_roundtrip` (POST zone baru dengan `behaviors`, GET kembali) dan `backend/tests/test_models.py::test_zone_behaviors_default_empty`. Jalankan `pytest tests/test_zones_api.py tests/test_models.py -q` → gagal (kolom belum ada).
- [ ] **Step 2: implementasi model + schema** — tambah kolom di model, tambah `behaviors`/`trigger_seconds` di `ZoneIn`/`ZonePatch`/`ZoneOut` dengan validator:

```python
VALID_BEHAVIORS = {"intrusion", "loitering", "running"}

def _validate_behaviors(v: list | None) -> list | None:
    if v is None:
        return v
    if not isinstance(v, list):
        raise ValueError("behaviors must be a list")
    for b in v:
        if not isinstance(b, dict) or b.get("kind") not in VALID_BEHAVIORS:
            raise ValueError(f"behavior kind must be one of {sorted(VALID_BEHAVIORS)}")
        if not isinstance(b.get("trigger_seconds", 0), int) or b.get("trigger_seconds", 0) < 0:
            raise ValueError("trigger_seconds must be an int >= 0")
    return v
```

  `zone.type` validator menerima `{"attendance", "behavior", "absensi", "restricted", "free"}` (nilai lama tetap boleh masuk saat migrasi, tapi UI hanya mengirim dua nilai baru).
- [ ] **Step 3: migration 0014** — `op.add_column` untuk `zone.behaviors`, `zone.trigger_seconds`, `camera.ai_fps`, `camera.confidence`, `camera.analyzers`, `camera.motion_enabled`; `downgrade` = drop; plus **backfill** di `upgrade()` lewat `op.execute`/`sa.text`:

```
absensi     → type='attendance', behaviors=[{"kind":"attendance","trigger_seconds":dwell_seconds}]
restricted  → type='behavior',   behaviors=[{"kind":"intrusion","trigger_seconds":dwell_seconds}]
              + loitering (bila loiter_seconds>0, trigger=loiter_seconds)
              + running   (bila speed_limit_mps>0, trigger=dwell_seconds, speed_limit_mps=...)
free        → type='behavior',   behaviors=[]
```
- [ ] **Step 4: verifikasi migrasi** — round-trip di DB scratch (SQLite hanya untuk uji file migrasi): stamp `0013` → `upgrade head` → cek kolom ada → `downgrade 0013` → `upgrade head`. Catat hasilnya di CHANGELOG.
- [ ] **Step 5: commit** `feat(backend): migration 0014 — zone.behaviors + setelan deteksi per kamera`

---

### Task 2: `config_push` — payload zona behaviors + setelan kamera

**Files:**
- Modify: `backend/app/services/config_push.py`
- Modify: `backend/app/core/config.py` (default global motion/ai_fps/conf)
- Test: `backend/tests/test_config_push.py`

**Desain payload (per kamera):**

```python
{
  "camera_id": cam.id, "source_url": ..., "ai_fps": cam.ai_fps or DEFAULT_FPS,
  "confidence": cam.confidence or settings.detector_conf,
  "analyzers": cam.analyzers,                      # None = semua
  "motion": {"enabled": cam.motion_enabled if cam.motion_enabled is not None else settings.motion_enabled,
             "threshold": settings.motion_threshold, "min_area": settings.motion_min_area,
             "force_interval_s": settings.motion_force_interval_s},
  "zones": [{"id","name","type","direction","polygon","schedule","severity","rate_limit_min",
             "behaviors":[...], "trigger_seconds": z.trigger_seconds,
             "snapshot": z.snapshot, "clip": z.clip, "telegram": z.telegram}],
}
```

- [ ] **Step 1: test (merah)** — `test_build_node_config_zone_includes_behaviors` (zona attendance → `behaviors=[{"kind":"attendance","trigger_seconds":3}]`) dan `test_build_node_config_camera_detection_overrides` (camera `ai_fps=8`, `confidence=0.45`, `analyzers=["intrusion"]`, `motion_enabled=False` → payload memuat nilainya; kamera tanpa override → nilai global).
- [ ] **Step 2: implementasi** — rakit payload; tambah setting baru di `config.py`: `motion_enabled: bool = True`, `motion_threshold: float = 0.02`, `motion_min_area: float = 0.01`, `motion_force_interval_s: float = 2.0`; perbarui test lama yang membandingkan dict zona persis (harga eksak berubah).
- [ ] **Step 3: commit** `feat(backend): config push — behaviors zona + setelan deteksi kamera`

---

### Task 3: Vision — analyzer mengikuti `behaviors` + master `analyzers`

**Files:**
- Modify: `vision/vision/node.py:308-336` (`_make_analyzers`, `_with_media`)
- Modify: `vision/vision/analyzers/intrusion.py`, `loitering.py`, `running.py`, `face_gate.py`
- Test: `vision/tests/test_node.py`, `vision/tests/test_intrusion.py`, `test_loitering.py`, `test_running.py`, `test_face_gate.py`

**Desain:** analyzer dibuat dari `zone["behaviors"]`, bukan dari `zone["type"]`/kolom lama:
- `intrusion` dibuat bila ada entry `kind=intrusion`; threshold delay = entry `trigger_seconds` (0 = emit saat transisi masuk, seperti sekarang).
- `loitering` dibuat bila ada entry `kind=loitering`; `loiter_seconds` = entry `trigger_seconds`.
- `running` dibuat bila ada entry `kind=running`; `speed_limit_mps` = entry; butuh `meters_per_pixel` (tetap).
- `face_gate` (sementara, sampai R5b) dibuat bila `zone["type"] == "attendance"`; `dwell` = `zone["trigger_seconds"]` atau entry `kind=attendance.trigger_seconds`.
- Master kamera: `cam.analyzers` (list) → skip analyzer yang kind-nya tidak ada di list; `None` = semua aktif.
- Kamera dengan `analyzers == []` → tidak ada analyzer (hanya live view, hemat GPU).

- [ ] **Step 1: test (merah)** — `test_make_analyzers_from_behaviors`: zona ber-`behaviors=[intrusion(0), loitering(30)]` + `analyzers=["intrusion"]` → hanya `IntrusionAnalyzer`; tanpa `analyzers` → dua analyzer; `analyzers=[]` → kosong. Tambah test `test_intrusion_trigger_delay`: `trigger_seconds=2` → transisi masuk tidak emit, 2 s kemudian emit (pola sama seperti dwell face_gate).
- [ ] **Step 2: implementasi** — helper `def _behavior(z, kind) -> dict | None` di `node.py`; analyzer membaca `trigger` dari entry; intrusion menambah `self.trigger` + `self._first_seen` (mirror logika di `face_gate._done`/`_first_seen`).
- [ ] **Step 3: regresi** — `pytest vision/tests -q -m "not gpu"` harus hijau; update test lama yang memakai `zone()` berbasis `type`/`loiter_seconds`.
- [ ] **Step 4: commit** `feat(vision): analyzer dari behaviors zona + master on/off per kamera`

---

### Task 4: Vision — motion gate

**Files:**
- Create: `vision/vision/motion.py`
- Modify: `vision/vision/node.py` (worker loop), `vision/vision/config.py` (parse `motion` per kamera)
- Test: `vision/tests/test_motion_gate.py` (baru), `vision/tests/test_node.py`

**Desain (`motion.py`):**

```python
class FrameMotionGate:
    """Gerak = rasio piksel berubah pada frame grayscale kecil (32x18 blok)."""
    def __init__(self, threshold: float = 0.02, min_area: float = 0.01, force_interval_s: float = 2.0):
        ...
    def update(self, frame, ts: float) -> bool:
        """True = boleh inferensi (ada gerak ATAU force interval lewat)."""
```

Algoritma: resize grayscale ke 64×36 → `absdiff` dengan frame sebelumnya → threshold biner → rasio piksel aktif (≈ `min_area`); simpan `self._last_detect_ts`; bila gerak < threshold tapi `ts - last_detect >= force_interval_s` → tetap True (objek diam / orang baru masuk frame tanpa gerak terdeteksi).

- [ ] **Step 1: test (merah)** — `test_static_frame_blocks_detection` (10 frame identik → hanya frame pertama yang True karena force interval), `test_moving_block_allows_detection`, `test_force_interval_recheck`. Jalankan → gagal (modul belum ada).
- [ ] **Step 2: implementasi modul + integrasi worker** — di `CameraWorker.run`, sebelum `detector.detect`: `if self.motion and not self.motion.update(frame.data, frame.ts): continue` — **tetapi** tetap kirim frame ke recorder ring + tetap `tracker.update([])` agar track lama bisa hilang secara alami (tulis komentar alasannya di kode).
- [ ] **Step 3: test worker** — `MockDetector` diberi counter: dengan motion gate `enabled=True` dan frame statis, jumlah pemanggilan `detect` < jumlah frame; dengan `enabled=False`, semua frame diinferensi.
- [ ] **Step 4: commit** `feat(vision): motion gate — inferensi hanya saat ada gerakan (hemat GPU)`

---

### Task 5: Overlay deteksi (`kind`) + label toggle UI

**Files:**
- Modify: `vision/vision/node.py:124-128` (payload detections)
- Modify: `frontend/src/features/live/LiveViewPage.tsx:180-230, 336-350`
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/liveview.test.tsx`, `vision/tests/test_node.py`

**Desain payload baru (backward-compatible: `boxes` tetap ada):**

```json
{"camera_id": 357, "kind": "person",
 "boxes": [{"id": 4, "bbox_norm": [0.48, 0.28, 0.62, 0.96], "label": null}]}
```
R5b akan mengirim `kind: "face"` + `label` = nama karyawan / `"unknown"`.

- [ ] **Step 1: test (merah)** — vitest: frame WS `kind:"person"` → `<rect data-testid="debug-box-4">` ada; `kind:"face"` + `label:"Angly"` → rect + teks `Angly` (siap walau R5b belum produksi face). Test vision: payload `publish_detections` memuat `kind`.
- [ ] **Step 2: implementasi** — node kirim `kind`; FE: ganti label toggle `live.showBbox` → **`live.showDetection`** ("Tampilkan deteksi"), render box + label per kind (person oranye, face biru), tetap satu SVG overlay dengan zona.
- [ ] **Step 3: verifikasi** — `npx vitest run`, `npm run build`, `npm run lint` (tanpa warning baru).
- [ ] **Step 4: commit** `feat(live): overlay deteksi (person/face) + toggle "Tampilkan deteksi"`

---

### Task 6: Backend — setelan global deteksi (Advanced) + API

**Files:**
- Create: `backend/alembic/versions/0015_detector_setting.py`, `backend/app/models/detector_setting.py`, `backend/app/schemas/detector_setting.py`, `backend/app/api/detector_settings.py`
- Modify: `backend/app/api/__init__.py` (router), `backend/app/services/config_push.py` (baca override), `backend/app/main.py` (wiring)
- Test: `backend/tests/test_detector_settings_api.py` (baru), `backend/tests/test_config_push.py`

**Desain:** tabel singleton `detector_setting` (id=1) kolom: `default_ai_fps float`, `default_confidence float`, `motion_enabled bool`, `motion_threshold float`, `motion_min_area float`, `motion_force_interval_s float`, `updated_at`. Precedence: **DB > env** (env tetap jadi nilai awal & fallback bila row tidak ada). API admin: `GET /api/v1/detector-settings`, `PUT /api/v1/detector-settings` → setelah commit, `config_push.republish_all(db)`.

- [ ] **Step 1: test (merah)** — PUT sebagai admin → 200 + nilai tersimpan; PUT sebagai viewer → 403; `build_node_config` memakai nilai DB setelah PUT (dan env bila belum ada row).
- [ ] **Step 2: implementasi** — model + schema + router + precedence di `config_push`.
- [ ] **Step 3: commit** `feat(backend): setelan deteksi global (motion/fps/confidence) + API admin`

---

### Task 7: Backend — PATCH kamera: `ai_fps`, `confidence`, `analyzers`, `motion_enabled`

**Files:**
- Modify: `backend/app/schemas/camera.py`, `backend/app/api/cameras.py`
- Test: `backend/tests/test_cameras_api.py`

**Desain:** validasi: `ai_fps` 0.5–25 (0 = kamera tanpa analitik? → gunakan `analyzers=[]`), `confidence` 0.05–0.95, `analyzers` ⊆ `{intrusion, loitering, running, attendance}`, `motion_enabled` bool. Setiap perubahan → `config_push.publish_node_config_for_camera(db, camera_id)` (pola `zones.py:_config_push`).

- [ ] **Step 1: test (merah)** — PATCH admin menetapkan `ai_fps=8` + `analyzers=["intrusion"]` → 200 dan payload config berubah; nilai invalid → 422; viewer → 403.
- [ ] **Step 2: implementasi + commit** `feat(backend): setelan deteksi per kamera (ai_fps/confidence/analyzers/motion)`

---

### Task 8: Frontend — tab Deteksi & Model (mockup 06) + Advanced

**Files:**
- Create: `frontend/src/features/config/DetectionPage.tsx`, `frontend/src/api/detection.ts`
- Modify: `frontend/src/features/config/ConfigurationPage.tsx` (tab baru `deteksi`), `frontend/src/app/theme.scss` (`.det-global`, `.det-tile`, chip), `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/detection.test.tsx` (baru)

**Desain (persis mockup 06):**
- Blok **Global** (tile read-only nilai efektif): MODEL DETEKSI, INFERENSI DEFAULT, CONFIDENCE, TRACKER.
- Tabel per kamera: `AI FPS` (number, kosong = global), `CONFIDENCE` (number, kosong = global), `ANALYZER AKTIF` (4 chip toggle: intrusion/loitering/running/attendance), aksi "Reset override".
- Blok **Advanced** collapsible (default tertutup): setelan global yang bisa disimpan — default AI FPS, default confidence, motion gate (enabled, threshold, min area, force interval). Hint: "semua analyzer mati = kamera hanya live view (hemat GPU)".

- [ ] **Step 1: test (merah)** — render tabel; klik chip `intrusion` pada kamera → `PATCH /cameras/{id}` dengan `analyzers` berubah; isi AI FPS → PATCH `ai_fps`; buka Advanced → ubah threshold motion → `PUT /detector-settings`; chip `attendance` hanya muncul untuk kamera gate (semua kamera boleh, tapi diberi keterangan).
- [ ] **Step 2: implementasi + `npx vitest run` + `npm run build`**
- [ ] **Step 3: commit** `feat(config-ui): tab Detection & Model — master analyzer per kamera + Advanced`

---

### Task 9: Frontend — editor zona (type Attendance|Behavior, behaviors + trigger)

**Files:**
- Modify: `frontend/src/features/config/ZonesPage.tsx`, `GatesPage.tsx`, `frontend/src/components/ZoneEditor.tsx`, `frontend/src/api/zones.ts`
- Test: `frontend/src/__tests__/zones.test.tsx`, `gates.test.tsx`

**Desain:**
- `type`: dropdown **Attendance | Behavior** (Attendance wajib `direction`; Behavior menampilkan multi-select behavior).
- Multi-select behavior → tiap behavior terpilih tampil satu input **"Trigger threshold (detik)"** (`0 = langsung`); `running` menambah input `speed_limit_mps`.
- Gate Attendance: input **"Trigger threshold (detik)"** + `direction`; label lama "dwell" dihapus dari i18n.
- `loiter_seconds`, `dwell_seconds`, `speed_limit_mps` per-zona lama tidak lagi ditampilkan (nilainya sudah pindah ke `behaviors` oleh migrasi).

- [ ] **Step 1: test (merah)** — pilih tipe Behavior + centang `intrusion` & `loitering` → dua input trigger tampil; ubah trigger loitering ke 30 → PATCH berisi `behaviors=[{kind:intrusion,trigger_seconds:0},{kind:loitering,trigger_seconds:30}]`; tipe Attendance → input trigger + radio arah; Behavior dengan nol behavior → diizinkan (zona visual).
- [ ] **Step 2: implementasi + verifikasi + commit** `feat(zones-ui): type Attendance|Behavior + trigger threshold per behavior`

---

### Task 10: Deploy + verifikasi lapangan

- [ ] Push branch, pull di `gspe-ai3`, `alembic upgrade head` (0014 + 0015) dari `backend/` dengan `DATABASE_URL` `.env` root.
- [ ] Restart vision (`kill -9` + tunggu `Restart=always`), re-push config; verifikasi retained MQTT memuat `behaviors` + `motion`.
- [ ] Cek motion gate bekerja: log/hitung pemanggilan detektor pada kamera tanpa gerakan (target: turun drastis; `modules.detector.ms_per_frame` tetap dilaporkan), dan pastikan track yang sudah ada tidak "hilang" saat diam.
- [ ] Verifikasi UI: tab Deteksi & Model (chips + override + Advanced), editor zona baru, overlay deteksi di modal debugger (person box muncul saat orang lewat).
- [ ] Verifikasi trigger: zona behavior `trigger_seconds=3` → event + snapshot terbit setelah 3 detik di dalam zona.
- [ ] Update `CHANGELOG.md` (satu entri per task), `.cooper/context/`, dan `docs/detection-behavior-inventory.md` (terminologi baru).

## Self-Review

- **Spec user:** tab Deteksi & Model ✓ (Task 8), type Attendance|Behavior ✓ (Task 9), Trigger threshold per behavior ✓ (Task 1/3/9), behavior on/off per kamera ✓ (Task 7/8), motion gate on + override ✓ (Task 4/6/7), overlay "Tampilkan deteksi" ✓ (Task 5), klip pre-roll (R5c) & attendance face-first (R5b) eksplisit di luar plan ini.
- **Placeholder:** tidak ada; setiap task punya test + langkah verifikasi konkret.
- **Risiko yang diakui:** (a) motion gate bisa menunda deteksi orang yang masuk frame tanpa gerak besar → mitigasi `force_interval_s` + test; (b) kolom lama tetap ada (expand-only) sehingga ada dua sumber kebenaran sementara → ditandai deprecated di model + inventory; (c) `analyzers=[]` = kamera tanpa analitik → pastikan config push tetap mengirim kamera (live view tetap jalan).
