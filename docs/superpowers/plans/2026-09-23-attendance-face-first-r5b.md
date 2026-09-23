# R5b Attendance Face-First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate absensi mengenali karyawan dari wajah di main stream 1080p tanpa YOLO: satu event per orang yang lewat, crop wajah dari frame yang sama, overlay kotak wajah hampir real-time.

**Architecture:** `FaceGateWorker` baru per kamera attendance membaca `cam_<id>_main`, menjalankan SCRFD → tracker kotak wajah → gerbang kualitas → ArcFace, lalu menggabungkan K frame bagus menjadi satu embedding dan menerbitkan satu event. `CameraWorker` (substream + YOLO) hanya untuk zona behavior. Backend tetap mencocokkan sekali per event, ditambah cooldown per karyawan dan pembuangan embedding dari payload tersimpan.

**Tech Stack:** Python 3.12 (vision node, FastAPI backend, SQLAlchemy/Alembic), insightface 2.0 (`buffalo_l`: SCRFD `det_10g` + ArcFace) via onnxruntime-gpu, OpenCV, React 19 + Carbon + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-23-attendance-face-first-design.md`

## Global Constraints

- Tidak ada atribusi AI di commit, kode, atau docs (AGENTS.md §9). Commit pesan Conventional Commits, satu commit per perubahan fungsional.
- Semua string UI lewat `frontend/src/app/i18n.tsx` (kunci `id` dan `en`); mobile 390 px tanpa overflow horizontal.
- Vision tetap bisa di-import tanpa CUDA/insightface (import insightface/cv2 secara lazy); yang butuh GPU/RTSP diberi marker `gpu`.
- Device pin tidak diubah: detector `cuda:1`, face `cuda:2`.
- Embedding wajah tidak boleh tersimpan di tabel `event` (spec §6).
- Default setelan (spec §5.2, §5.5, §6, §8): `face_min_width_px=80`, `face_min_det_score=0.6`, `face_max_yaw=0.35`, `face_blur_min=120`, `face_min_frames=3`, `ATTENDANCE_COOLDOWN_MIN=5`, `ByteTracker.max_age_s=3.0`, padding crop 30%, lebar snapshot 1280, tanpa clip.
- Perintah tes (dari root repo kecuali disebut lain):
  - vision: `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`
  - backend: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`
  - frontend: `cd frontend && npx vitest run && npm run build && npm run lint`
- Baseline sebelum plan: backend **309 passed**, vision **151 passed, 2 deselected**, frontend **94 passed**, build exit 0; lint: set warning yang sama sebelum/sesudah (bandingkan via `git stash`).

## Review Focus

1. **Dua wajah dalam satu frame** (satu karyawan, satu tamu) → dua track, dua event terpisah, embedding tidak tercampur. Tes: Task 5 `test_two_faces_same_frame_two_events`.
2. **Wajah di tepi frame** → kotak crop berpadding dipotong batas frame, crop tidak kosong dan tidak crash. Tes: Task 4 `test_crop_box_is_clamped_at_frame_edges`.
3. **Main stream belum tersedia saat worker start** (go2rtc belum punya `cam_<id>_main`) → worker mencoba ulang, tidak mati. Tes: Task 2 `test_source_unavailable_at_start_retries_instead_of_raising`.
4. **Event attendance tiba tidak urut** (antrean disk node flush setelah MQTT putus) → cooldown simetris, tetap satu `attendance_event`. Tes: Task 8 `test_out_of_order_delivery_within_cooldown_records_once`.
5. **Config push tanpa setelan wajah** (backend lama atau key hilang) → node memakai default. Tes: Task 4 `test_face_settings_defaults_and_partial_config` dan Task 6 `test_attendance_only_camera_runs_face_worker_without_yolo`.

---

### Task 1: `ByteTracker.max_age` berbasis waktu

**Files:**
- Modify: `vision/vision/pipeline/tracker.py`
- Modify: `vision/vision/node.py` (hapus komentar `ponytail:` max_age di `CameraWorker.__init__`)
- Modify: `vision/vision/motion.py` (docstring baris "jarak frame di bawah `max_age` tracker")
- Test: `vision/tests/test_tracker.py`, `vision/tests/test_motion_gate.py`

**Interfaces:**
- Produces: `ByteTracker(max_age_s: float = 3.0, min_conf=0.3, dist_threshold=0.15)`; `Track.last_seen: float`; `ByteTracker.lost_ids: set[int]` (id yang dibuang pada `update` terakhir, tidak berubah).

- [ ] **Step 1: Tulis tes yang gagal**

`vision/tests/test_motion_gate.py` — tambah `import pytest` di atas, lalu ganti tes lama `test_static_track_survives_the_gated_gap_at_deployed_settings` dengan versi berparameter:

```python
@pytest.mark.parametrize("ai_fps", [5.0, 10.0, 15.0])
def test_static_track_survives_the_gated_gap_at_deployed_settings(ai_fps):
    """Objek diam: gate menahan inferensi selama force_interval_s dan tiap frame
    tertahan memanggil tracker.update([]). Track harus masih hidup saat inferensi
    paksa berikutnya pada AI FPS yang diizinkan UI; jika tidak, id berganti dan timer
    dwell/loitering serta penggabungan wajah R5b ter-reset terus.
    """
    from vision.pipeline.detector import Detection
    from vision.pipeline.tracker import ByteTracker

    force_interval_s = 2.0
    gated_frames = int(force_interval_s * ai_fps)

    tracker = ByteTracker()
    det = Detection(bbox=(0.4, 0.4, 0.5, 0.6), conf=0.9)
    track_id = tracker.update([det], ts=0.0)[0].id

    for i in range(gated_frames):
        tracker.update([], ts=(i + 1) / ai_fps)

    survivors = tracker.update([det], ts=force_interval_s)
    assert [t.id for t in survivors] == [track_id], (
        f"track mati setelah {gated_frames} frame tertahan @ {ai_fps} fps"
    )
```

`vision/tests/test_tracker.py` — ganti dua tes lama dan tambah satu:

```python
def test_track_dropped_after_max_age_seconds():
    tr = ByteTracker(max_age_s=3.0)
    tr.update([D(0.5, 0.5)], ts=0.0)
    lost_at = None
    for i in range(1, 21):
        tracks = tr.update([], ts=i / 5)
        if 1 in tr.lost_ids:
            lost_at = i
            break
    assert lost_at == 16  # 3,2 s sejak terakhir terlihat > 3,0 s -> dibuang
    assert all(t.id != 1 for t in tracks)


def test_missed_track_still_active_until_max_age():
    tr = ByteTracker(max_age_s=0.6)
    tr.update([D(0.5, 0.5)], ts=0.0)
    tracks = tr.update([], ts=0.2)
    assert [t.id for t in tracks] == [1]
    assert tracks[0].misses == 1
    tracks = tr.update([], ts=0.4)
    assert tracks[0].misses == 2


def test_track_age_is_time_based_not_frame_count():
    """25 fps: 30 frame kosong = 1,2 s. Hitungan frame (15) membunuh track; waktu (3 s) tidak."""
    tr = ByteTracker(max_age_s=3.0)
    tr.update([D(0.5, 0.5)], ts=0.0)
    for i in range(1, 31):
        tracks = tr.update([], ts=i / 25)
    assert [t.id for t in tracks] == [1]
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_motion_gate.py vision/tests/test_tracker.py -q`
Expected: `test_static_track_survives_the_gated_gap_at_deployed_settings[10.0]` dan `[15.0]` FAIL ("track mati setelah 20 frame tertahan"); tes tracker baru ERROR `TypeError: ... unexpected keyword argument 'max_age_s'`.

- [ ] **Step 3: Implementasi minimal**

`vision/vision/pipeline/tracker.py`:

```python
@dataclass
class Track:
    id: int
    bbox: tuple[float, float, float, float]
    centroid: tuple[float, float]
    age: int
    velocity: tuple[float, float]
    misses: int = 0
    last_seen: float = 0.0


@dataclass
class ByteTracker:
    # detik sejak terakhir terlihat (setara 15 frame @ 5 fps); berbasis waktu supaya
    # gap motion gate (force_interval_s) aman di AI FPS berapa pun
    max_age_s: float = 3.0
    min_conf: float = 0.3
    dist_threshold: float = 0.15
```

Di `update`: saat track dicocokkan tambahkan `tr.last_seen = ts`; track baru dibuat dengan `last_seen=ts`; blok track yang tidak cocok menjadi:

```python
        for ti, tr in enumerate(self._tracks):
            if ti < n_prior and ti not in used_t:
                tr.misses += 1
                if ts - tr.last_seen > self.max_age_s:
                    self.lost_ids.add(tr.id)
                    continue
            active.append(tr)
```

Hapus komentar `# ponytail: umur track ByteTrack dihitung per-frame ...` (6 baris, termasuk rujukan tes) di `CameraWorker.__init__` (`vision/vision/node.py`). Di docstring `vision/vision/motion.py` ganti "(jarak frame di bawah `max_age` tracker)" menjadi "(gap di bawah `max_age_s` tracker, dalam detik)".

- [ ] **Step 4: Jalankan tes**

Run: `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`
Expected: semua PASS (151 + 2 param baru + 1 tes tracker baru = 154 passed).

- [ ] **Step 5: Commit**

```bash
git add vision/vision/pipeline/tracker.py vision/vision/node.py vision/vision/motion.py vision/tests/test_tracker.py vision/tests/test_motion_gate.py
git commit -m "fix(vision): umur track ByteTracker berbasis detik, bukan hitungan frame"
```

---

### Task 2: `FrameSource` mencoba ulang bila stream belum ada saat start

**Files:**
- Modify: `vision/vision/pipeline/source.py`
- Test: `vision/tests/test_source.py`

**Interfaces:**
- Produces: konstanta modul `RECONNECT_START_S = 1.0`; `FrameSource.start()` tidak lagi raise `RuntimeError` ketika `isOpened()` False — reader thread yang mencoba ulang dengan backoff 1, 2, 4 … 30 s.

- [ ] **Step 1: Tulis tes yang gagal**

Tambah di `vision/tests/test_source.py`:

```python
class OpensOnSecondTry:
    """go2rtc belum punya stream saat worker start; stream muncul sesudahnya."""

    attempts = 0

    def __init__(self, url):
        OpensOnSecondTry.attempts += 1
        self.ok = OpensOnSecondTry.attempts >= 2
        self.n = 0

    def isOpened(self):
        return self.ok

    def read(self):
        if not self.ok:
            return False, None
        time.sleep(0.01)
        self.n += 1
        return True, np.array([self.n])

    def release(self):
        pass


def test_source_unavailable_at_start_retries_instead_of_raising(monkeypatch):
    import vision.pipeline.source as source_mod
    monkeypatch.setattr(source_mod, "RECONNECT_START_S", 0.01)
    OpensOnSecondTry.attempts = 0
    src = FrameSource("fake://cam", target_fps=10.0, open_capture=OpensOnSecondTry)
    frame = next(src)          # dulu: RuntimeError "cannot open video source" -> worker mati
    src.close()
    assert int(frame.data[0]) >= 1
    assert OpensOnSecondTry.attempts >= 2
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_source.py -q -k retries`
Expected: FAIL/ERROR `RuntimeError: cannot open video source: fake://cam` (atau `AttributeError` untuk `RECONNECT_START_S`).

- [ ] **Step 3: Implementasi minimal**

Di `vision/vision/pipeline/source.py` tambahkan setelah import:

```python
import logging

log = logging.getLogger(__name__)

RECONNECT_START_S = 1.0  # backoff awal reconnect; digandakan s/d 30 s
```

Ganti `start()`:

```python
    def start(self) -> None:
        self._cap = self._open()
        if not self._cap.isOpened():
            # jangan raise: stream bisa menyusul (go2rtc baru membuat alias); reader
            # thread mencoba ulang dengan backoff dan worker tetap hidup
            log.warning("cannot open video source %s, retrying", self.url)
        self._next_due = time.monotonic()
        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name=f"src-{self.url.rsplit('/', 1)[-1]}")
        self._reader.start()
```

Di `_read_loop` ganti dua `delay = 1.0` menjadi `delay = RECONNECT_START_S`.

- [ ] **Step 4: Jalankan tes**

Run: `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`
Expected: semua PASS.

- [ ] **Step 5: Commit**

```bash
git add vision/vision/pipeline/source.py vision/tests/test_source.py
git commit -m "fix(vision): FrameSource mencoba ulang saat stream belum ada, worker tidak mati"
```

---

### Task 3: `FaceEmbedder` — deteksi, align, embedding terpisah

**Files:**
- Modify: `vision/vision/face.py`
- Test: `vision/tests/test_face_embed.py`

**Interfaces:**
- Produces:
  - `FaceDet` dataclass: `bbox: tuple[float, float, float, float]` (piksel xyxy frame input), `kps: np.ndarray` shape `(5, 2)` piksel (mata kiri, mata kanan, hidung, mulut kiri, mulut kanan), `score: float`.
  - `FaceEmbedder.detect_faces(img: np.ndarray) -> list[FaceDet]` (`[]` bila model tak tersedia).
  - `FaceEmbedder.align(img: np.ndarray, kps: np.ndarray) -> np.ndarray` (112×112×3, `insightface.utils.face_align.norm_crop`).
  - `FaceEmbedder.embed(aligned: np.ndarray) -> list[float] | None` (vektor 512 ter-normalisasi L2).
  - `FaceEmbedder.loaded() -> bool`, atribut `detect_n: int`, `embed_n: int`.
  - Model dimuat dengan `allowed_modules=["detection", "recognition"]`.
- `embed_jpeg` dan `detect` lama **tetap ada** sampai Task 6 menghapusnya.

- [ ] **Step 1: Tulis tes yang gagal**

Tambah di `vision/tests/test_face_embed.py` (import `sys`, `types` di atas file bila belum):

```python
class FakeDetModel:
    def detect(self, img, max_num=0, metric="default"):
        boxes = np.array([[10.0, 20.0, 110.0, 140.0, 0.9]])
        kps = np.array([[[40, 60], [80, 60], [60, 85], [45, 110], [75, 110]]], dtype=np.float32)
        return boxes, kps


class FakeRecModel:
    def get_feat(self, imgs):
        return np.full((1, 512), 2.0, dtype=np.float32)   # insightface: belum ternormalisasi


class FakeDetRecApp:
    det_model = FakeDetModel()
    models = {"recognition": FakeRecModel()}


def test_detect_faces_returns_pixel_box_landmarks_and_score():
    emb = FaceEmbedder(model_root="/tmp/x")
    emb._app = FakeDetRecApp()
    faces = emb.detect_faces(np.zeros((240, 320, 3), np.uint8))
    assert len(faces) == 1
    assert faces[0].bbox == (10.0, 20.0, 110.0, 140.0)
    assert faces[0].score == pytest.approx(0.9)
    assert faces[0].kps.shape == (5, 2)
    assert emb.detect_n == 1


def test_embed_returns_unit_vector():
    emb = FaceEmbedder(model_root="/tmp/x")
    emb._app = FakeDetRecApp()
    vec = emb.embed(np.zeros((112, 112, 3), np.uint8))
    assert len(vec) == 512
    assert float(np.linalg.norm(vec)) == pytest.approx(1.0)
    assert emb.embed_n == 1


def test_detect_and_embed_degrade_when_insightface_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "insightface", None)
    monkeypatch.setitem(sys.modules, "insightface.app", None)
    emb = FaceEmbedder(model_root="/tmp/x")
    assert emb.detect_faces(np.zeros((8, 8, 3), np.uint8)) == []
    assert emb.embed(np.zeros((112, 112, 3), np.uint8)) is None
    assert emb.loaded() is False


def test_loader_limits_modules_to_detection_and_recognition(monkeypatch):
    seen = {}

    class FakeFaceAnalysis:
        def __init__(self, name, root, providers, allowed_modules=None):
            seen["allowed_modules"] = allowed_modules

        def prepare(self, ctx_id, det_size):
            pass

    mod = types.ModuleType("insightface.app")
    mod.FaceAnalysis = FakeFaceAnalysis
    monkeypatch.setitem(sys.modules, "insightface", types.ModuleType("insightface"))
    monkeypatch.setitem(sys.modules, "insightface.app", mod)
    assert FaceEmbedder(model_root="/tmp/x", device="cuda:2").loaded() is False  # belum dimuat
    assert FaceEmbedder(model_root="/tmp/x", device="cuda:2").available() is True
    assert seen["allowed_modules"] == ["detection", "recognition"]
```

Ubah `FakeFaceAnalysis.__init__` di tes lama `test_device_pin_reaches_onnxruntime_session` menjadi `def __init__(self, name, root, providers, allowed_modules=None):`.

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_face_embed.py -q`
Expected: tes baru FAIL/ERROR `AttributeError: 'FaceEmbedder' object has no attribute 'detect_faces'` / `'loaded'`; `test_loader_limits...` assert `None == [...]`.

- [ ] **Step 3: Implementasi minimal**

Di `vision/vision/face.py`:

```python
from dataclasses import dataclass

import numpy as np


@dataclass
class FaceDet:
    """Satu wajah SCRFD di koordinat piksel frame input."""

    bbox: tuple[float, float, float, float]  # xyxy
    kps: np.ndarray                            # (5, 2): mata kiri, mata kanan, hidung, mulut kiri, mulut kanan
    score: float
```

Di `__init__` tambahkan `self.detect_n = 0` dan `self.embed_n = 0`. Di `_load`, panggil:

```python
            app = FaceAnalysis(name="buffalo_l", root=self.model_root, providers=providers,
                               allowed_modules=["detection", "recognition"])
```

Tambahkan method:

```python
    def loaded(self) -> bool:
        return self._app is not None

    def detect_faces(self, img) -> list[FaceDet]:
        """SCRFD pada frame BGR (diperkecil internal ke det_size 640); kotak & landmark piksel."""
        app = self._ensure_loaded()
        if app is None:
            return []
        bboxes, kpss = app.det_model.detect(img, max_num=0, metric="default")
        self.detect_n += 1
        if kpss is None:
            return []   # tanpa landmark tidak bisa di-align
        return [FaceDet(bbox=tuple(float(v) for v in b[:4]),
                        kps=np.asarray(k, dtype=np.float32), score=float(b[4]))
                for b, k in zip(bboxes, kpss)]

    def align(self, img, kps):
        """Crop wajah ter-align 112×112 (template ArcFace) dari frame resolusi penuh."""
        from insightface.utils import face_align
        return face_align.norm_crop(img, landmark=kps, image_size=112)

    def embed(self, aligned) -> list[float] | None:
        """ArcFace pada crop ter-align -> vektor 512 ternormalisasi L2."""
        app = self._ensure_loaded()
        if app is None:
            return None
        feat = np.asarray(app.models["recognition"].get_feat(aligned), dtype=np.float64).ravel()
        norm = float(np.linalg.norm(feat))
        if norm == 0.0:
            return None
        self.embed_n += 1
        return [float(v) / norm for v in feat]
```

- [ ] **Step 4: Jalankan tes**

Run: `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`
Expected: semua PASS.

- [ ] **Step 5: Commit**

```bash
git add vision/vision/face.py vision/tests/test_face_embed.py
git commit -m "feat(vision): FaceEmbedder deteksi, align, dan embedding terpisah untuk face-first"
```

---

### Task 4: Gerbang kualitas dan penggabungan (fungsi murni)

**Files:**
- Create: `vision/vision/face_quality.py`
- Test: `vision/tests/test_face_quality.py`

**Interfaces:**
- Consumes: `FaceDet` (Task 3), `point_in_polygon(pt, poly)` dari `vision/vision/analyzers/intrusion.py`.
- Produces:
  - `FaceSettings(min_width_px=80.0, min_det_score=0.6, max_yaw=0.35, blur_min=120.0, min_frames=3)` frozen dataclass + `FaceSettings.from_config(face: dict | None) -> FaceSettings` (kunci config push: `min_width_px`, `min_det_score`, `max_yaw`, `blur_min`, `min_frames`).
  - `yaw_ratio(kps) -> float`, `blur_score(aligned) -> float`, `quality(det_score, width_px, yaw) -> float`.
  - `zone_of(center_norm: tuple[float, float], zones: list[dict]) -> dict | None`.
  - `gate_code(det: FaceDet, frame_w: int, frame_h: int, zones: list[dict], s: FaceSettings) -> tuple[str | None, dict | None]` — kode gagal pertama dari `zone|small|score|yaw` (blur dicek pemanggil setelah align) dan zona yang memuat titik tengah wajah.
  - `aggregate(vectors: list[list[float]], weights: list[float]) -> list[float]`.
  - `crop_box(bbox, frame_w, frame_h, pad=0.30) -> tuple[int, int, int, int]`.

- [ ] **Step 1: Tulis tes yang gagal**

`vision/tests/test_face_quality.py`:

```python
"""Gerbang kualitas wajah R5b: fungsi murni, tanpa GPU."""
import numpy as np
import pytest

from vision.face import FaceDet
from vision.face_quality import (FaceSettings, aggregate, blur_score, crop_box, gate_code,
                                 quality, yaw_ratio, zone_of)

FRONTAL = np.array([[40, 60], [80, 60], [60, 85], [45, 110], [75, 110]], dtype=np.float32)
TURNED = FRONTAL.copy()
TURNED[2, 0] = 78.0          # hidung bergeser 18 px dari tengah mata; jarak mata 40 -> 0,45
ZONE = {"id": 9, "direction": "entry",
        "polygon": [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]}
W, H = 1920, 1080


def face(cx=960.0, cy=540.0, width=120.0, score=0.9, base=FRONTAL):
    """Wajah lebar `width` px berpusat di (cx, cy); landmark diskalakan ikut lebar."""
    x1, y1 = cx - width / 2, cy - width * 0.6
    kps = (base - base.mean(axis=0)) * (width / 60.0) + np.array([cx, cy], dtype=np.float32)
    return FaceDet(bbox=(x1, y1, x1 + width, y1 + width * 1.2), kps=kps, score=score)


def test_yaw_ratio_frontal_is_zero_and_turned_is_large():
    assert yaw_ratio(FRONTAL) == pytest.approx(0.0)
    assert yaw_ratio(TURNED) == pytest.approx(0.45)


def test_yaw_ratio_degenerate_eyes_is_rejected():
    kps = FRONTAL.copy()
    kps[1] = kps[0]
    assert yaw_ratio(kps) == 1.0


def test_blur_score_sharp_noise_vs_flat():
    sharp = np.random.default_rng(0).integers(0, 255, (112, 112, 3), dtype=np.uint8)
    assert blur_score(sharp) > 120
    assert blur_score(np.zeros((112, 112, 3), np.uint8)) == 0.0


def test_quality_formula():
    assert quality(0.9, 56.0, 0.2) == pytest.approx(0.9 * 0.5 * 0.8)
    assert quality(0.9, 224.0, 0.0) == pytest.approx(0.9)   # lebar di atas 112 tidak menambah


def test_gate_code_reports_first_failing_gate():
    s = FaceSettings()
    assert gate_code(face(cx=100.0), W, H, [ZONE], s) == ("zone", None)
    assert gate_code(face(width=60.0), W, H, [ZONE], s)[0] == "small"
    assert gate_code(face(score=0.5), W, H, [ZONE], s)[0] == "score"
    assert gate_code(face(base=TURNED), W, H, [ZONE], s)[0] == "yaw"
    assert gate_code(face(), W, H, [ZONE], s) == (None, ZONE)


def test_zone_of_picks_zone_containing_face_center():
    entry = {"id": 1, "direction": "entry", "polygon": [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]}
    exit_ = {"id": 2, "direction": "exit", "polygon": [[0.5, 0], [1, 0], [1, 1], [0.5, 1]]}
    assert zone_of((0.8, 0.5), [entry, exit_]) is exit_
    assert zone_of((0.2, 0.5), [entry, exit_]) is entry


def _unit(i):
    v = [0.0] * 512
    v[i] = 1.0
    return v


def test_aggregate_is_weighted_and_unit_length():
    out = np.array(aggregate([_unit(0), _unit(1)], [3.0, 1.0]))
    assert float(np.linalg.norm(out)) == pytest.approx(1.0)
    assert out[0] / out[1] == pytest.approx(3.0)


def test_aggregate_drops_outlier_from_swapped_track():
    neg = [-v for v in _unit(0)]
    out = aggregate([_unit(0), _unit(0), neg], [1.0, 1.0, 1.0])
    assert out[0] == pytest.approx(1.0)


def test_aggregate_cancelling_vectors_fall_back_to_heaviest():
    neg = [-v for v in _unit(0)]
    assert aggregate([_unit(0), neg], [1.0, 1.0]) == _unit(0)


def test_crop_box_pads_30_percent():
    assert crop_box((900.0, 468.0, 1020.0, 612.0), W, H) == (864, 424, 1056, 655)


def test_crop_box_is_clamped_at_frame_edges():
    x1, y1, x2, y2 = crop_box((0.0, 0.0, 100.0, 120.0), W, H)
    assert (x1, y1) == (0, 0) and x2 > 100 and y2 > 120
    x1, y1, x2, y2 = crop_box((1850.0, 980.0, 1920.0, 1080.0), W, H)
    assert (x2, y2) == (W, H) and x1 < 1850 and y1 < 980


def test_face_settings_defaults_and_partial_config():
    assert FaceSettings.from_config(None) == FaceSettings()
    s = FaceSettings.from_config({"device": "cuda:2", "min_frames": 5})
    assert s.min_frames == 5 and s.min_width_px == 80.0 and s.blur_min == 120.0
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_face_quality.py -q`
Expected: ERROR `ModuleNotFoundError: No module named 'vision.face_quality'`.

- [ ] **Step 3: Implementasi minimal**

`vision/vision/face_quality.py`:

```python
"""Gerbang kualitas wajah attendance (R5b): fungsi murni, tanpa GPU.

Angka default dan dasarnya: spec 2026-09-23-attendance-face-first-design.md §5.2.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .analyzers.intrusion import point_in_polygon

ARCFACE_SIZE = 112.0
OUTLIER_COS = 0.5   # embedding yang cosine-nya ke rata-rata di bawah ini dianggap orang lain


@dataclass(frozen=True)
class FaceSettings:
    min_width_px: float = 80.0
    min_det_score: float = 0.6
    max_yaw: float = 0.35
    blur_min: float = 120.0
    min_frames: int = 3

    @classmethod
    def from_config(cls, face: dict | None) -> "FaceSettings":
        """Key `face` config push; key yang hilang (backend lama) memakai default."""
        face = face or {}
        d = cls()
        return cls(
            min_width_px=float(face.get("min_width_px", d.min_width_px)),
            min_det_score=float(face.get("min_det_score", d.min_det_score)),
            max_yaw=float(face.get("max_yaw", d.max_yaw)),
            blur_min=float(face.get("blur_min", d.blur_min)),
            min_frames=int(face.get("min_frames", d.min_frames)),
        )


def yaw_ratio(kps) -> float:
    """|x_hidung − x_tengah_mata| ÷ jarak mata; 0 = frontal, ~0,35 ≈ yaw 30°."""
    le, re, nose = kps[0], kps[1], kps[2]
    eye_dist = float(np.hypot(float(re[0] - le[0]), float(re[1] - le[1])))
    if eye_dist <= 0.0:
        return 1.0
    return abs(float(nose[0]) - (float(le[0]) + float(re[0])) / 2.0) / eye_dist


def blur_score(aligned) -> float:
    """Variansi Laplacian crop ter-align; makin kecil makin buram."""
    import cv2
    gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY) if aligned.ndim == 3 else aligned
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def quality(det_score: float, width_px: float, yaw: float) -> float:
    return det_score * min(1.0, width_px / ARCFACE_SIZE) * max(0.0, 1.0 - yaw)


def zone_of(center_norm: tuple[float, float], zones: list[dict]) -> dict | None:
    for z in zones:
        if point_in_polygon(center_norm, [tuple(p) for p in z["polygon"]]):
            return z
    return None


def gate_code(det, frame_w: int, frame_h: int, zones: list[dict],
              s: FaceSettings) -> tuple[str | None, dict | None]:
    """Kode gerbang pertama yang gagal (zone|small|score|yaw) + zona wajah; blur dicek setelah align."""
    x1, y1, x2, y2 = det.bbox
    zone = zone_of(((x1 + x2) / 2.0 / frame_w, (y1 + y2) / 2.0 / frame_h), zones)
    if zone is None:
        return "zone", None
    if (x2 - x1) < s.min_width_px:
        return "small", zone
    if det.score < s.min_det_score:
        return "score", zone
    if yaw_ratio(det.kps) > s.max_yaw:
        return "yaw", zone
    return None, zone


def _unit(v: np.ndarray) -> np.ndarray | None:
    n = float(np.linalg.norm(v))
    return None if n == 0.0 else v / n


def aggregate(vectors: list[list[float]], weights: list[float]) -> list[float]:
    """Rata-rata berbobot kualitas, buang outlier (track tertukar), normalisasi ulang."""
    V = np.asarray(vectors, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    best = [float(x) for x in V[int(np.argmax(w))]]
    mean = _unit((V * w[:, None]).sum(axis=0))
    if mean is None:
        return best
    keep = (V @ mean) >= OUTLIER_COS
    if not keep.any():
        return best
    out = _unit((V[keep] * w[keep, None]).sum(axis=0))
    return best if out is None else [float(x) for x in out]


def crop_box(bbox, frame_w: int, frame_h: int, pad: float = 0.30) -> tuple[int, int, int, int]:
    """Kotak wajah + padding, dipotong batas frame."""
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    return (max(0, int(x1 - bw * pad)), max(0, int(y1 - bh * pad)),
            min(frame_w, int(x2 + bw * pad)), min(frame_h, int(y2 + bh * pad)))
```

- [ ] **Step 4: Jalankan tes**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_face_quality.py -q`
Expected: semua PASS. (Bila `test_crop_box_pads_30_percent` meleset 1 px karena `int()`, hitung ulang dari rumus lalu perbaiki angka di tes, bukan rumusnya.)

- [ ] **Step 5: Commit**

```bash
git add vision/vision/face_quality.py vision/tests/test_face_quality.py
git commit -m "feat(vision): gerbang kualitas dan penggabungan embedding wajah"
```

---

### Task 5: `FaceGateWorker`

**Files:**
- Create: `vision/vision/face_worker.py`
- Test: `vision/tests/test_face_worker.py`

**Interfaces:**
- Consumes: `ByteTracker(max_age_s=...)` (Task 1), `FaceDet`, `FaceEmbedder.detect_faces/align/embed` (Task 3), semua fungsi `face_quality` (Task 4), `FrameMotionGate`, `Detection`, `vision.node._iso` (import lazy di dalam fungsi untuk menghindari import melingkar).
- Produces:
  - `FaceGateWorker(camera_id: int, zones: list[dict], face, transport, node_id: str, settings: FaceSettings, recorder=None, motion: dict | None = None, max_age_s: float = 3.0)`; atribut `source`, `stop_event: threading.Event`, `events: list[dict]`, `recorder`, `camera_id`; method `run()`, `stop()`.
  - Event `attendance` (spec §5.5): top-level `snapshot_path`, `clip_path=None`; payload `track_id, direction, bbox_norm, embedding, face_quality, face_bbox, crop_path, face_stats{width_px, det_score, yaw, blur, frames}`.
  - Overlay `publish_detections(camera_id, boxes, kind="face")`, `label` = `q` 2 desimal atau kode `zone|small|score|yaw|blur`.

- [ ] **Step 1: Tulis tes yang gagal**

`vision/tests/test_face_worker.py`:

```python
"""FaceGateWorker (R5b): face-first di main stream, tanpa YOLO. Mesin wajah palsu, tanpa GPU."""
import threading

import cv2
import numpy as np
import pytest

from vision.face import FaceDet
from vision.face_quality import FaceSettings
from vision.face_worker import FaceGateWorker
from vision.pipeline.source import FrameSource

FRAME = np.zeros((1080, 1920, 3), np.uint8)
SHARP = np.random.default_rng(0).integers(0, 255, (112, 112, 3), dtype=np.uint8)
FRONTAL = np.array([[40, 60], [80, 60], [60, 85], [45, 110], [75, 110]], dtype=np.float32)
ZONE = {"id": 9, "direction": "entry",
        "polygon": [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]}
E1 = [1.0] + [0.0] * 511
NEG = [-1.0] + [0.0] * 511


def face(cx=960.0, cy=540.0, width=120.0, score=0.9):
    x1, y1 = cx - width / 2, cy - width * 0.6
    kps = (FRONTAL - FRONTAL.mean(axis=0)) * (width / 60.0) + np.array([cx, cy], dtype=np.float32)
    return FaceDet(bbox=(x1, y1, x1 + width, y1 + width * 1.2), kps=kps, score=score)


GOOD = face()


class FakeFaces:
    """detect_faces mengembalikan isi per frame berurutan (Exception = raise)."""

    def __init__(self, per_frame, vectors=None, aligned=SHARP):
        self.per_frame = list(per_frame)
        self.vectors = list(vectors or [])
        self.aligned = aligned
        self.embed_calls = 0

    def detect_faces(self, img):
        item = self.per_frame.pop(0) if self.per_frame else []
        if isinstance(item, Exception):
            raise item
        return item

    def align(self, img, kps):
        return self.aligned

    def embed(self, aligned):
        self.embed_calls += 1
        return self.vectors.pop(0) if self.vectors else E1


class FakeTransport:
    def __init__(self):
        self.events, self.detections = [], []

    def publish_event(self, ev):
        self.events.append(ev)

    def publish_detections(self, camera_id, boxes, kind="person"):
        self.detections.append((camera_id, kind, boxes))


class FakeRecorder:
    def __init__(self, fail=False):
        self.fail = fail
        self.uploads = []

    def upload_bytes(self, data, kind, content_type="image/jpeg"):
        self.uploads.append((kind, data))
        return None if self.fail else f"{kind}s/x.jpg"


def run_worker(frames_faces, engine=None, transport=None, recorder=None, settings=FaceSettings()):
    t = transport or FakeTransport()
    eng = engine or FakeFaces(frames_faces)
    w = FaceGateWorker(363, [ZONE], eng, t, "test-node", settings, recorder=recorder, max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * len(frames_faces), fps=10.0)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    return w, t, eng


def labels(t):
    return [b["label"] for _, kind, boxes in t.detections if kind == "face" for b in boxes]


def test_one_event_after_k_good_frames():
    _, t, eng = run_worker([[GOOD]] * 5)
    assert len(t.events) == 1
    ev = t.events[0]
    assert (ev["type"], ev["zone_id"], ev["camera_id"], ev["node_id"]) == ("attendance", 9, 363, "test-node")
    p = ev["payload"]
    assert p["direction"] == "entry" and len(p["embedding"]) == 512
    assert p["face_stats"]["frames"] == 3 and p["face_stats"]["width_px"] == 120
    assert ev["clip_path"] is None
    assert eng.embed_calls == 3          # track selesai: tidak di-embed lagi


def test_no_event_when_no_frame_passes_gates():
    _, t, eng = run_worker([[face(width=40.0)]] * 5)
    assert t.events == [] and eng.embed_calls == 0
    assert set(labels(t)) == {"small"}


def test_face_outside_zone_is_labelled_and_not_embedded():
    _, t, eng = run_worker([[face(cx=100.0)]] * 3)
    assert t.events == [] and eng.embed_calls == 0
    assert set(labels(t)) == {"zone"}


def test_short_pass_emits_when_track_expires():
    _, t, _ = run_worker([[GOOD]] + [[]] * 8)
    assert len(t.events) == 1
    assert t.events[0]["payload"]["face_stats"]["frames"] == 1


def test_overlay_published_before_embedding():
    t = FakeTransport()

    class Recording(FakeFaces):
        seen = []

        def embed(self, aligned):
            Recording.seen.append(len(t.detections))
            return super().embed(aligned)

    run_worker([[GOOD]] * 3, engine=Recording([[GOOD]] * 3), transport=t)
    assert Recording.seen[0] >= 1


def test_swapped_track_outlier_is_dropped():
    _, t, _ = run_worker([[GOOD]] * 3, engine=FakeFaces([[GOOD]] * 3, vectors=[E1, E1, NEG]))
    assert t.events[0]["payload"]["embedding"][0] == pytest.approx(1.0)


def test_face_engine_error_does_not_kill_worker():
    frames = [RuntimeError("onnx"), [GOOD], [GOOD], [GOOD]]
    _, t, _ = run_worker(frames, engine=FakeFaces(frames))
    assert len(t.events) == 1


def test_two_faces_same_frame_two_events():
    left, right = face(cx=700.0), face(cx=1220.0)
    _, t, _ = run_worker([[left, right]] * 4)
    assert len(t.events) == 2
    assert len({ev["payload"]["track_id"] for ev in t.events}) == 2


def test_brief_detection_gap_keeps_one_track():
    _, t, _ = run_worker([[GOOD], [], [GOOD], [GOOD]])
    assert len(t.events) == 1
    assert t.events[0]["payload"]["face_stats"]["frames"] == 3


def test_crop_and_snapshot_come_from_best_frame():
    rec = FakeRecorder()
    _, t, _ = run_worker([[GOOD]] * 3, recorder=rec)
    assert [kind for kind, _ in rec.uploads] == ["crop", "snapshot"]
    crop = cv2.imdecode(np.frombuffer(rec.uploads[0][1], np.uint8), cv2.IMREAD_COLOR)
    snap = cv2.imdecode(np.frombuffer(rec.uploads[1][1], np.uint8), cv2.IMREAD_COLOR)
    assert crop.shape[1] == 192            # 120 px + padding 30% kiri-kanan
    assert snap.shape[1] == 1280
    ev = t.events[0]
    assert ev["snapshot_path"] == "snapshots/x.jpg"
    assert ev["payload"]["crop_path"] == "crops/x.jpg"
    assert ev["payload"]["face_bbox"][0] == pytest.approx(36.0)


def test_upload_failure_still_publishes_event():
    _, t, _ = run_worker([[GOOD]] * 3, recorder=FakeRecorder(fail=True))
    ev = t.events[0]
    assert ev["payload"]["crop_path"] is None and ev["snapshot_path"] is None
    assert len(ev["payload"]["embedding"]) == 512
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_face_worker.py -q`
Expected: ERROR `ModuleNotFoundError: No module named 'vision.face_worker'`.

- [ ] **Step 3: Implementasi minimal**

`vision/vision/face_worker.py`:

```python
"""FaceGateWorker (R5b): gate absensi face-first di main stream, tanpa YOLO.

Alur per frame: motion gate -> SCRFD -> tracker kotak wajah -> overlay (sebelum
embedding) -> gerbang kualitas -> ArcFace. Satu track = satu event, terbit setelah
K frame bagus atau saat track kedaluwarsa. Spec: 2026-09-23-attendance-face-first-design.md.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field

from .face_quality import (FaceSettings, aggregate, blur_score, crop_box, gate_code,
                           quality, yaw_ratio)
from .motion import FrameMotionGate
from .pipeline.detector import Detection
from .pipeline.tracker import ByteTracker

log = logging.getLogger(__name__)

DEDUP_BUCKET_S = 10.0
SNAPSHOT_W = 1280
BOX_BGR = (255, 169, 120)   # #78a9ff, sama dengan warna kotak wajah di overlay


@dataclass
class _TrackState:
    zone: dict
    vectors: list = field(default_factory=list)
    weights: list = field(default_factory=list)
    best_q: float = -1.0
    best: dict | None = None     # {"frame", "bbox", "ts", "stats"} frame dengan q tertinggi
    done: bool = False


def _jpeg(img) -> bytes:
    import cv2
    ok, buf = cv2.imencode(".jpg", img)
    if not ok:
        raise ValueError("imencode gagal")
    return buf.tobytes()


def _snapshot_jpeg(frame, bbox) -> bytes:
    import cv2
    img = frame.copy()
    x1, y1, x2, y2 = (int(v) for v in bbox)
    cv2.rectangle(img, (x1, y1), (x2, y2), BOX_BGR, 3)
    h, w = img.shape[:2]
    if w > SNAPSHOT_W:
        img = cv2.resize(img, (SNAPSHOT_W, int(h * SNAPSHOT_W / w)), interpolation=cv2.INTER_AREA)
    return _jpeg(img)


class FaceGateWorker(threading.Thread):
    def __init__(self, camera_id: int, zones: list[dict], face, transport, node_id: str,
                 settings: FaceSettings, recorder=None, motion: dict | None = None,
                 max_age_s: float = 3.0):
        super().__init__(daemon=True, name=f"face-{camera_id}")
        self.camera_id = camera_id
        self.zones = zones
        self.face = face
        self.transport = transport
        self.node_id = node_id
        self.settings = settings
        self.recorder = recorder
        self.stop_event = threading.Event()
        self.source = None
        self.events: list[dict] = []   # test hook
        motion = motion or {}
        self.motion_gate = (
            FrameMotionGate(threshold=motion.get("threshold", 25.0),
                            min_area=motion.get("min_area", 0.01),
                            force_interval_s=motion.get("force_interval_s", 2.0))
            if (motion and motion.get("enabled", True)) else None
        )
        self._tracker = ByteTracker(max_age_s=max_age_s)
        self._states: dict[int, _TrackState] = {}
        self._faces_shown = False

    def run(self):
        try:
            for frame in self.source:
                if self.stop_event.is_set():
                    break
                if frame.data is None:
                    continue
                if self.motion_gate is not None and not self.motion_gate.update(frame.data, frame.ts):
                    self._tracker.update([], frame.ts)
                    self._expire()
                    continue
                self._process(frame)
        except Exception:
            if not self.stop_event.is_set():
                log.exception("camera %s: face worker died", self.camera_id)

    def stop(self):
        if self.source is not None:
            self.source.close()

    def _process(self, frame) -> None:
        h, w = frame.data.shape[:2]
        try:
            faces = self.face.detect_faces(frame.data)
        except Exception:
            log.warning("camera %s: face detect gagal", self.camera_id, exc_info=True)
            faces = []
        dets = [Detection(bbox=(f.bbox[0] / w, f.bbox[1] / h, f.bbox[2] / w, f.bbox[3] / h),
                          conf=f.score) for f in faces]
        by_bbox = {d.bbox: f for d, f in zip(dets, faces)}
        tracks = self._tracker.update(dets, frame.ts)
        boxes, passed = [], []
        for tr in tracks:
            f = by_bbox.get(tr.bbox)
            if f is None:
                continue   # track bertahan tanpa deteksi di frame ini: jangan digambar
            code, zone = gate_code(f, w, h, self.zones, self.settings)
            aligned = None
            if code is None:
                try:
                    aligned = self.face.align(frame.data, f.kps)
                    if blur_score(aligned) < self.settings.blur_min:
                        code = "blur"
                except Exception:
                    log.warning("camera %s: align wajah gagal", self.camera_id, exc_info=True)
                    code = "blur"
            q = quality(f.score, f.bbox[2] - f.bbox[0], yaw_ratio(f.kps))
            boxes.append({"id": tr.id, "bbox_norm": [round(v, 4) for v in tr.bbox],
                          "label": code or f"{q:.2f}"})
            if code is None:
                passed.append((tr.id, f, zone, aligned, q))
        self._publish(boxes)                       # overlay dulu, embedding sesudahnya
        for tid, f, zone, aligned, q in passed:
            self._accumulate(tid, f, zone, aligned, q, frame)
        self._expire()

    def _publish(self, boxes: list[dict]) -> None:
        if self.transport is None:
            return
        if boxes or self._faces_shown:
            self.transport.publish_detections(self.camera_id, boxes, kind="face")
        self._faces_shown = bool(boxes)

    def _accumulate(self, tid, f, zone, aligned, q, frame) -> None:
        st = self._states.setdefault(tid, _TrackState(zone=zone))
        if st.done:
            return
        try:
            vec = self.face.embed(aligned)
        except Exception:
            log.warning("camera %s: embedding wajah gagal", self.camera_id, exc_info=True)
            return
        if vec is None:
            return
        st.vectors.append(vec)
        st.weights.append(q)
        if q > st.best_q:
            st.best_q = q
            st.best = {"frame": frame.data, "bbox": f.bbox, "ts": frame.ts,
                       "stats": {"width_px": round(f.bbox[2] - f.bbox[0]),
                                 "det_score": round(f.score, 3),
                                 "yaw": round(yaw_ratio(f.kps), 3),
                                 "blur": round(blur_score(aligned), 1)}}
        if len(st.vectors) >= self.settings.min_frames:
            self._emit(tid, st)

    def _expire(self) -> None:
        """Track yang baru dibuang tracker: terbitkan bila punya 1..K-1 frame bagus."""
        for tid in self._tracker.lost_ids:
            st = self._states.pop(tid, None)
            if st is not None and not st.done and st.vectors:
                self._emit(tid, st)

    def _emit(self, tid: int, st: _TrackState) -> None:
        from .node import _iso   # lazy: node.py mengimpor modul ini
        st.done = True
        best, st.best = st.best, None   # lepas referensi frame 1080p
        frame, bbox, ts = best["frame"], best["bbox"], best["ts"]
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        crop_path = snapshot_path = face_bbox = None
        if self.recorder is not None:
            try:
                cx1, cy1, cx2, cy2 = crop_box(bbox, w, h)
                face_bbox = [x1 - cx1, y1 - cy1, x2 - cx1, y2 - cy1]
                crop_path = self.recorder.upload_bytes(_jpeg(frame[cy1:cy2, cx1:cx2]), "crop")
                snapshot_path = self.recorder.upload_bytes(_snapshot_jpeg(frame, bbox), "snapshot")
            except Exception:
                log.warning("camera %s: upload crop/snapshot wajah gagal", self.camera_id,
                            exc_info=True)
        ev = {
            "event_id": str(uuid.uuid4()),
            "type": "attendance",
            "node_id": self.node_id,
            "camera_id": self.camera_id,
            "zone_id": st.zone["id"],
            "severity": "info",
            "ts_event": _iso(ts),
            "payload": {
                "track_id": tid,
                "direction": st.zone.get("direction"),
                "bbox_norm": [x1 / w, y1 / h, x2 / w, y2 / h],
                "embedding": aggregate(st.vectors, st.weights),
                "face_quality": round(st.best_q, 3),
                "face_bbox": face_bbox,
                "crop_path": crop_path,
                "face_stats": {**best["stats"], "frames": len(st.vectors)},
            },
            "dedup_key": f"{self.camera_id}:attendance:face{tid}:{int(ts // DEDUP_BUCKET_S)}",
            "snapshot_path": snapshot_path,
            "clip_path": None,
        }
        self.events.append(ev)
        self.transport.publish_event(ev)
```

- [ ] **Step 4: Jalankan tes**

Run: `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`
Expected: semua PASS (termasuk 11 tes baru).

- [ ] **Step 5: Commit**

```bash
git add vision/vision/face_worker.py vision/tests/test_face_worker.py
git commit -m "feat(vision): FaceGateWorker face-first, satu event per orang lewat"
```

---

### Task 6: Pasang `FaceGateWorker` di node, hapus jalur absensi berbasis person

**Files:**
- Modify: `vision/vision/node.py`
- Modify: `vision/vision/face.py` (hapus `embed_jpeg` dan `detect`)
- Modify: `vision/vision/recorder.py` (hapus `fetch_frame`)
- Modify: `vision/vision/analyzers/__init__.py`
- Delete: `vision/vision/analyzers/face_gate.py`, `vision/tests/test_face_gate.py`
- Test: `vision/tests/test_node.py`, `vision/tests/test_node_face_embed.py`, `vision/tests/test_face_embed.py`, `vision/tests/test_recorder.py`, `vision/tests/test_intrusion.py`

**Interfaces:**
- Consumes: `FaceGateWorker` (Task 5), `FaceSettings.from_config` (Task 4).
- Produces:
  - `attendance_zones(cam: CameraCfg) -> list[dict]` (modul `vision.node`): zona yang punya behavior `attendance` (termasuk config pra-R5 `absensi`), tanpa memandang `cam.analyzers`.
  - `main_stream_url(source_url: str) -> str`: `rtsp://h:8554/cam_363` → `rtsp://h:8554/cam_363_main`; URL non-`cam_*` dikembalikan apa adanya.
  - `VisionNode._face_settings: FaceSettings` (diisi dari `cfg_dict["face"]`), `VisionNode._face_module_info() -> dict` (`device, loaded, detect_n, embed_n`), heartbeat `modules.face`.
  - `CameraWorker.camera_id` (atribut baru, dipakai heartbeat untuk kedua jenis worker).

- [ ] **Step 1: Tulis tes yang gagal**

Di `vision/tests/test_node.py`:
- Hapus tes `test_attendance_gate_ignores_camera_analyzers_master` (dari `5711160`).
- Tambah import `from vision.node import attendance_zones, main_stream_name, main_stream_url`.
- Tambah:

```python
SQUARE_POLY = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


@pytest.mark.parametrize("master", [["intrusion"], []])
def test_attendance_zone_not_filtered_by_camera_master(master):
    """Absensi diatur dari tab Gate Absensi; master analyzers kamera tidak mematikannya."""
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [ATTENDANCE_ZONE], "analyzers": master}
    node = _node_with(cam)
    cams = node._cameras_from_config({"cameras": [cam]})
    assert [z["id"] for z in attendance_zones(cams[0])] == [9]
    assert node._make_analyzers(cams[0]) == []      # attendance bukan analyzer person lagi


def test_legacy_absensi_zone_is_attendance():
    legacy = {"id": 11, "type": "absensi", "direction": "entry", "polygon": SQUARE_POLY,
              "dwell_seconds": 3}
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [legacy]}
    node = _node_with(cam)
    cams = node._cameras_from_config({"cameras": [cam]})
    assert [z["id"] for z in attendance_zones(cams[0])] == [11]


def test_main_stream_url_and_name():
    assert main_stream_name("rtsp://localhost:8554/cam_4") == "cam_4_main"
    assert main_stream_name("rtsp://localhost:8554/cam_12/") == "cam_12_main"
    assert main_stream_name("test://1") is None
    assert main_stream_url("rtsp://h:8554/cam_363") == "rtsp://h:8554/cam_363_main"
    assert main_stream_url("test://1") == "test://1"


class _NoFaces:
    detect_n = 0
    embed_n = 0

    def loaded(self):
        return True

    def detect_faces(self, img):
        return []

    def align(self, img, kps):
        return img

    def embed(self, aligned):
        return None


def _wired_node(tmp_path, zones, api_key=""):
    urls, det_calls = [], []
    frame = np.zeros((4, 4, 3), np.uint8)
    cfg = NodeSettings(node_id="n", cameras_json="[]", api_key=api_key, data_dir=str(tmp_path))

    def source_factory(cam):
        urls.append(cam.source_url)
        return FrameSource.from_frames([frame] * 2, fps=5.0)

    def detector_factory(cid):
        det_calls.append(cid)
        return MockDetector([[], []])

    node = VisionNode(cfg=cfg, detector_factory=detector_factory,
                      source_factory=source_factory, transport=FakeTransport())
    node.face = _NoFaces()
    node.apply_config({"cameras": [{"camera_id": 363, "source_url": "rtsp://h:8554/cam_363",
                                    "zones": zones}],
                       "face": {"device": "", "min_frames": 5}})
    workers = list(node._workers)
    node._stop_workers()
    return node, workers, urls, det_calls


def test_attendance_only_camera_runs_face_worker_without_yolo(tmp_path):
    node, workers, urls, det_calls = _wired_node(tmp_path, [ATTENDANCE_ZONE])
    assert [type(w).__name__ for w in workers] == ["FaceGateWorker"]
    assert urls == ["rtsp://h:8554/cam_363_main"]
    assert det_calls == []
    assert node._face_settings.min_frames == 5 and node._face_settings.min_width_px == 80.0


def test_mixed_camera_runs_both_workers_sharing_one_recorder(tmp_path):
    _, workers, urls, det_calls = _wired_node(tmp_path, [ATTENDANCE_ZONE, BEHAVIOR_ZONE], api_key="k")
    assert sorted(type(w).__name__ for w in workers) == ["CameraWorker", "FaceGateWorker"]
    assert sorted(urls) == ["rtsp://h:8554/cam_363", "rtsp://h:8554/cam_363_main"]
    assert workers[0].recorder is workers[1].recorder is not None
    assert det_calls == [363]


def test_heartbeat_reports_face_module(tmp_path):
    node, *_ = _wired_node(tmp_path, [ATTENDANCE_ZONE])
    assert node._face_module_info() == {"device": "auto", "loaded": True, "detect_n": 0, "embed_n": 0}
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_node.py -q`
Expected: ERROR `ImportError: cannot import name 'attendance_zones'`.

- [ ] **Step 3: Implementasi**

Di `vision/vision/node.py`:

1. Import: hapus `from .analyzers.face_gate import FaceGateAnalyzer, crop_upper_body`; tambah `from .face_quality import FaceSettings` dan `from .face_worker import FaceGateWorker`.
2. `CameraWorker.__init__`: tambah `self.camera_id = camera_cfg.camera_id`; hapus `self.face = None`, `self._face_overlay = ...`, `self._faces_shown = ...`.
3. `CameraWorker.run`: hapus blok `if self._face_overlay and self.face is not None ...: self._publish_faces(...)` dan baris `self._attach_crop(partial, frame)` di loop analyzer.
4. Hapus method `CameraWorker._publish_faces`, `_attach_crop`, `_draw_face_box`, `_mainstream_crop`, `_frame_crop`, `_encode_crop`.
5. Tambah fungsi modul setelah `main_stream_name`:

```python
def main_stream_url(source_url: str) -> str:
    """URL go2rtc main stream (resolusi penuh) untuk pipeline wajah; non-cam_* apa adanya."""
    name = main_stream_name(source_url)
    if name is None:
        return source_url
    return source_url.rstrip("/").rsplit("/", 1)[0] + "/" + name


def attendance_zones(cam) -> list[dict]:
    """Zona gate absensi kamera (termasuk config pra-R5 `absensi`).

    Tidak disaring `cam.analyzers`: absensi diatur dari tab Gate Absensi (zona
    `active`), UI tak bisa menaruh `attendance` di master analyzer.
    """
    return [z for z in cam.zones
            if any(b.get("kind") == "attendance" for b in behaviors_of(z))]
```

6. `_make_analyzers`: di awal loop behavior tambah `if kind == "attendance": continue  # FaceGateWorker (R5b)`, kembalikan filter master ke `if cam.analyzers is not None and kind not in cam.analyzers: continue`, hapus cabang `elif kind == "attendance"`, dan perbarui docstring (absensi ditangani `FaceGateWorker`, bukan analyzer).
7. `VisionNode.__init__`: tambah `self._face_settings = FaceSettings()`.
8. `apply_config`: sebelum `self._start_workers(...)` tambah `self._face_settings = FaceSettings.from_config(cfg_dict.get("face"))`.
9. Ganti isi `_start_workers`:

```python
    def _start_workers(self, cameras: list[CameraCfg]) -> None:
        self._stop_workers()
        for cam in cameras:
            recorder = None
            if self.cfg.api_key:  # produksi: upload blob ke backend
                from .recorder import Recorder
                recorder = Recorder(cam.camera_id, self.cfg, self.transport)
            analyzers = self._make_analyzers(cam)
            gates = attendance_zones(cam)
            if analyzers or not gates:   # kamera hanya-attendance tidak menjalankan YOLO
                w = CameraWorker(cam, self.detector_factory, self.transport,
                                 threading.Event(), self.cfg.node_id,
                                 analyzers=analyzers, recorder=recorder,
                                 emit_person_detect=self.cfg.emit_person_detect,
                                 motion=cam.motion)
                w.source = self.source_factory(cam)
                w.start()
                self._workers.append(w)
            if gates and self.face is not None:
                fw = FaceGateWorker(cam.camera_id, gates, self.face, self.transport,
                                    self.cfg.node_id, self._face_settings,
                                    recorder=recorder, motion=cam.motion)
                fw.source = self.source_factory(
                    cam.model_copy(update={"source_url": main_stream_url(cam.source_url)}))
                fw.start()
                self._workers.append(fw)
        log.info("started %d worker(s) for %d camera(s)", len(self._workers), len(cameras))
```

10. `_stop_workers`: tutup recorder bersama sekali saja:

```python
    def _stop_workers(self) -> list:
        for w in self._workers:
            w.stop_event.set()
            w.stop()
        recorders = {}
        for w in self._workers:
            w.join(timeout=5.0)
            if getattr(w, "recorder", None) is not None:
                recorders[id(w.recorder)] = w.recorder
        for rec in recorders.values():
            rec.close()
        stopped, self._workers = self._workers, []
        return stopped
```

11. Heartbeat: `cam_ids = sorted({w.camera_id for w in getattr(self, "_workers", [])})` dan `hb["modules"] = {"detector": self._detector_module_info(), "face": self._face_module_info()}` dengan:

```python
    def _face_module_info(self) -> dict:
        f = self.face
        return {"device": self.cfg.face_device or "auto",
                "loaded": bool(f is not None and f.loaded()),
                "detect_n": f.detect_n if f is not None else 0,
                "embed_n": f.embed_n if f is not None else 0}
```

    Catatan: log "started 5 camera worker(s)" di journal berubah menjadi "started N worker(s) for M camera(s)" — perbarui perintah `until journalctl ... grep "started"` di runbook Task 11.

12. `vision/vision/face.py`: hapus `embed_jpeg` dan `detect` (dari `e508a97`); perbarui docstring kelas menjadi `"""Lazy InsightFace wrapper: detect_faces / align / embed (R5b face-first)."""`.
13. `vision/vision/recorder.py`: hapus `fetch_frame`.
14. `vision/vision/analyzers/__init__.py`: hapus import `FaceGateAnalyzer, crop_upper_body`, entri `"face_gate"` di `ANALYZERS`, dan keduanya dari `__all__`. Hapus file `vision/vision/analyzers/face_gate.py`.
15. Tes lama: hapus `vision/tests/test_face_gate.py`; di `test_node_face_embed.py` hapus empat tes `test_attach_crop_*` beserta helper yang hanya dipakai mereka (`FakeRecorder`, `FakeEmbedder`, `_partial`, `_frame`, `_worker`), sisakan tiga tes setelan/konstruksi embedder; di `test_face_embed.py` hapus `FakeApp`, `_jpeg_bytes`, tiga tes `test_embed_jpeg_*`, dan ubah `test_embedder_unavailable_without_insightface` / `test_embedder_not_retried_after_failure` agar memanggil `emb.detect_faces(np.zeros((8, 8, 3), np.uint8)) == []` sebagai ganti `embed_jpeg`; di `test_recorder.py` hapus dua tes `test_fetch_frame_*`; di `test_intrusion.py` (`test_all_zone_analyzers_use_the_same_ground_point`) hapus `"face_gate"` dari tuple nama dan dari docstring.

- [ ] **Step 4: Jalankan tes**

Run: `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"` lalu `grep -rn "face_gate\|FaceGateAnalyzer\|_attach_crop\|embed_jpeg\|fetch_frame\|crop_upper_body" vision/`
Expected: semua PASS; grep kosong (kecuali nama tes/doc yang memang membahas sejarah — tidak boleh ada di kode produksi).

- [ ] **Step 5: Commit**

```bash
git add -A vision/
git commit -m "feat(vision): kamera attendance memakai FaceGateWorker di main stream, jalur absensi berbasis person dihapus"
```

---

### Task 7: Backend — setelan wajah global, migration 0016, config push

**Files:**
- Modify: `backend/app/core/config.py`, `backend/app/models/detector_setting.py`, `backend/app/schemas/detector_setting.py`, `backend/app/api/detector_settings.py`, `backend/app/services/config_push.py`, `.env.example`
- Create: `backend/alembic/versions/0016_face_gate_settings.py`, `backend/tests/test_migration_0016.py`
- Test: `backend/tests/test_detector_settings_api.py`

**Interfaces:**
- Produces:
  - Kolom `detector_setting`: `face_min_width_px FLOAT`, `face_min_det_score FLOAT`, `face_max_yaw FLOAT`, `face_blur_min FLOAT`, `face_min_frames INTEGER` (non-null, server default 80/0.6/0.35/120/3).
  - `Settings.face_min_width_px=80.0`, `face_min_det_score=0.6`, `face_max_yaw=0.35`, `face_blur_min=120.0`, `face_min_frames=3`, `attendance_cooldown_min=5`.
  - API `GET/PUT /api/v1/detector-settings` memuat lima field wajah (wajib di PUT).
  - Config push `face = {"device", "min_width_px", "min_det_score", "max_yaw", "blur_min", "min_frames"}`.
  - Migration helper `strip_embedding(payload) -> dict | None`.

- [ ] **Step 1: Tulis tes yang gagal**

`backend/tests/test_migration_0016.py`:

```python
"""Logika murni migration 0016 — pembersihan embedding dari payload event lama."""
import importlib.util
import pathlib

_PATH = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0016_face_gate_settings.py"
_spec = importlib.util.spec_from_file_location("mig0016", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_strip_embedding_removes_only_embedding():
    assert mig.strip_embedding({"embedding": [0.1] * 512, "crop_path": "crops/x.jpg"}) == {
        "crop_path": "crops/x.jpg"}


def test_strip_embedding_leaves_other_payloads_untouched():
    assert mig.strip_embedding({"crop_path": "crops/x.jpg"}) is None
    assert mig.strip_embedding(None) is None
```

Di `backend/tests/test_detector_settings_api.py` perluas `VALUES` dan tes:

```python
VALUES = {
    "default_ai_fps": 8.0, "default_confidence": 0.45,
    "motion_enabled": False, "motion_threshold": 30.0,
    "motion_min_area": 0.02, "motion_force_interval_s": 3.0,
    "face_min_width_px": 100.0, "face_min_det_score": 0.7, "face_max_yaw": 0.3,
    "face_blur_min": 90.0, "face_min_frames": 4,
}
```

Tambahkan di akhir `test_admin_put_persists_global_settings_and_config_uses_them`:

```python
    face = build_node_config(db, node)["face"]
    assert {k: face[k] for k in ("min_width_px", "min_det_score", "max_yaw", "blur_min", "min_frames")} == {
        "min_width_px": 100.0, "min_det_score": 0.7, "max_yaw": 0.3, "blur_min": 90.0, "min_frames": 4}
```

Tambah tes:

```python
def test_face_settings_validated(client):
    bad = {**VALUES, "face_min_frames": 0}
    response = client.put("/api/v1/detector-settings", json=bad, headers=admin_headers(client))
    assert response.status_code == 422


def test_get_without_row_returns_face_defaults(client):
    body = client.get("/api/v1/detector-settings", headers=admin_headers(client)).json()
    assert (body["face_min_width_px"], body["face_min_frames"]) == (80.0, 3)
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_migration_0016.py tests/test_detector_settings_api.py -q`
Expected: `FileNotFoundError` untuk migration; tes API FAIL (`KeyError: 'face_min_width_px'` / 422 tidak muncul).

- [ ] **Step 3: Implementasi**

`backend/app/core/config.py` (di blok face recognition):

```python
    # gerbang wajah attendance R5b (fallback bila baris detector_setting belum ada)
    face_min_width_px: float = 80.0
    face_min_det_score: float = 0.6
    face_max_yaw: float = 0.35
    face_blur_min: float = 120.0
    face_min_frames: int = 3
    attendance_cooldown_min: int = 5  # karyawan+arah sama dalam N menit = satu absensi
```

`backend/app/models/detector_setting.py` (import `Integer` sudah ada):

```python
    face_min_width_px: Mapped[float] = mapped_column(Float, nullable=False, default=80.0)
    face_min_det_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    face_max_yaw: Mapped[float] = mapped_column(Float, nullable=False, default=0.35)
    face_blur_min: Mapped[float] = mapped_column(Float, nullable=False, default=120.0)
    face_min_frames: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
```

`backend/alembic/versions/0016_face_gate_settings.py`:

```python
"""detector_setting: gerbang wajah attendance (R5b) + buang embedding dari payload event lama.

Revision ID: 0016
Revises: 0015
"""

from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

FACE_COLUMNS = (
    ("face_min_width_px", sa.Float(), "80"),
    ("face_min_det_score", sa.Float(), "0.6"),
    ("face_max_yaw", sa.Float(), "0.35"),
    ("face_blur_min", sa.Float(), "120"),
    ("face_min_frames", sa.Integer(), "3"),
)


def strip_embedding(payload):
    """Payload tanpa `embedding`; None bila tidak ada yang perlu dibuang."""
    if not isinstance(payload, dict) or "embedding" not in payload:
        return None
    return {k: v for k, v in payload.items() if k != "embedding"}


def upgrade() -> None:
    for name, type_, default in FACE_COLUMNS:
        op.add_column("detector_setting",
                      sa.Column(name, type_, nullable=False, server_default=default))
    # data biometrik tidak disimpan di tabel event (spec R5b §6); tidak bisa dikembalikan
    event = sa.table("event", sa.column("id", sa.Integer), sa.column("type", sa.String),
                     sa.column("payload", sa.JSON))
    bind = op.get_bind()
    rows = bind.execute(sa.select(event.c.id, event.c.payload).where(event.c.type == "attendance"))
    for row_id, payload in rows.fetchall():
        cleaned = strip_embedding(payload)
        if cleaned is not None:
            bind.execute(event.update().where(event.c.id == row_id).values(payload=cleaned))


def downgrade() -> None:
    for name, _, _ in reversed(FACE_COLUMNS):
        op.drop_column("detector_setting", name)
```

`backend/app/schemas/detector_setting.py` — tambah ke `DetectorSettingsIn`:

```python
    face_min_width_px: float = Field(ge=16, le=1000)
    face_min_det_score: float = Field(ge=0.1, le=0.99)
    face_max_yaw: float = Field(gt=0, le=1)
    face_blur_min: float = Field(ge=0)
    face_min_frames: int = Field(ge=1, le=20)
```

`backend/app/api/detector_settings.py` — di `_effective` fallback tambahkan:

```python
        face_min_width_px=settings.face_min_width_px,
        face_min_det_score=settings.face_min_det_score,
        face_max_yaw=settings.face_max_yaw,
        face_blur_min=settings.face_blur_min,
        face_min_frames=settings.face_min_frames,
```

`backend/app/services/config_push.py` — ganti baris `face = {...}`:

```python
    gs = global_settings
    face = {
        "device": node.face_device or "",  # "" = node pakai env/auto
        "min_width_px": gs.face_min_width_px if gs else settings.face_min_width_px,
        "min_det_score": gs.face_min_det_score if gs else settings.face_min_det_score,
        "max_yaw": gs.face_max_yaw if gs else settings.face_max_yaw,
        "blur_min": gs.face_blur_min if gs else settings.face_blur_min,
        "min_frames": gs.face_min_frames if gs else settings.face_min_frames,
    }
```

`.env.example` — di blok face tambahkan `ATTENDANCE_COOLDOWN_MIN=5` dengan komentar satu baris.

- [ ] **Step 4: Jalankan tes**

Run: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`
Expected: semua PASS (309 + tes baru). Bila `test_config_push.py` membandingkan `face` secara utuh, perbarui ekspektasinya ke dict enam kunci di atas.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/app/models/detector_setting.py backend/app/schemas/detector_setting.py backend/app/api/detector_settings.py backend/app/services/config_push.py backend/alembic/versions/0016_face_gate_settings.py backend/tests/test_migration_0016.py backend/tests/test_detector_settings_api.py backend/tests/test_config_push.py .env.example
git commit -m "feat(api): setelan gerbang wajah global + migration 0016 buang embedding lama"
```

---

### Task 8: Backend — cooldown, embedding tidak disimpan, event tanpa crop tetap dicocokkan

**Files:**
- Modify: `backend/app/services/attendance.py`
- Test: `backend/tests/test_attendance_logic.py`

**Interfaces:**
- Consumes: `settings.attendance_cooldown_min` (Task 7), `face.match_vector(vector, quality)`, `face.match_crop(db, path)`.
- Produces: `handle_face_event(db, event)` — pada semua jalur `event.payload` tidak lagi memuat `embedding`; payload hasil cocok memuat `employee_id`, `employee_name`, `face_score`, `match_reason` (`matched` | `cooldown`); jalur tidak cocok `employee_id=None`, `match_reason` dari matcher.

- [ ] **Step 1: Tulis tes yang gagal**

Tambah di `backend/tests/test_attendance_logic.py`:

```python
def _matched_vec(eid, score=0.8):
    return lambda vector, quality=None: MatchResult(eid, score, quality, "matched")


def _no_match_vec():
    return lambda vector, quality=None: MatchResult(None, None, quality, "no_match")


VEC = {"embedding": [0.1] * 512, "face_quality": 0.8}


def test_embedding_never_stored_after_match(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    ev = _raw_event(db, "entry", _at(*MON, 7, 10), VEC)
    assert attendance.handle_face_event(db, ev) is not None
    db.refresh(ev)
    assert "embedding" not in ev.payload
    assert (ev.payload["employee_name"], ev.payload["match_reason"]) == ("Budi", "matched")


def test_embedding_stripped_on_unmatched_and_invalid_paths(db, monkeypatch):
    _camera(db)
    _emp(db, _shift(db))
    monkeypatch.setattr(attendance.face, "match_vector", _no_match_vec())
    unmatched = _raw_event(db, "entry", _at(*MON, 7, 10), VEC)
    invalid = _raw_event(db, "sideways", _at(*MON, 7, 11), VEC)
    attendance.handle_face_event(db, unmatched)
    attendance.handle_face_event(db, invalid)
    for ev in (unmatched, invalid):
        db.refresh(ev)
        assert "embedding" not in ev.payload
    assert unmatched.payload["match_reason"] == "no_match"


def test_embedding_event_without_crop_is_still_matched(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    ev = _raw_event(db, "entry", _at(*MON, 7, 10), {**VEC, "crop_path": None})
    row = attendance.handle_face_event(db, ev)
    assert row is not None and row.snapshot_path is None


def test_second_pass_within_cooldown_records_one_attendance(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    second = _raw_event(db, "entry", _at(*MON, 7, 13), VEC)
    assert attendance.handle_face_event(db, second) is None
    assert db.query(AttendanceEvent).count() == 1
    db.refresh(second)
    assert (second.payload["match_reason"], second.payload["employee_id"]) == ("cooldown", e.id)


def test_pass_after_cooldown_records_again(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 16), VEC))
    assert db.query(AttendanceEvent).count() == 2


def test_cooldown_is_per_direction(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    attendance.handle_face_event(db, _raw_event(db, "exit", _at(*MON, 7, 12), VEC))
    assert db.query(AttendanceEvent).count() == 2


def test_out_of_order_delivery_within_cooldown_records_once(db, monkeypatch):
    """Antrean disk node bisa mengirim event lama setelah yang baru."""
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 8), VEC))
    assert db.query(AttendanceEvent).count() == 1
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_attendance_logic.py -q`
Expected: tes baru FAIL (`'embedding' in payload`, `KeyError: 'employee_name'`, count 2 ≠ 1, event tanpa crop → None).

- [ ] **Step 3: Implementasi**

Ganti `handle_face_event` di `backend/app/services/attendance.py` dan tambahkan dua helper:

```python
def _save(db, event, payload: dict, result):
    """Tulis payload event (JSON tidak dilacak mutasi, jadi di-assign ulang) lalu commit."""
    event.payload = payload
    db.commit()
    return result


def _in_cooldown(db, employee_id: int, direction: str, ts: datetime) -> bool:
    """Sudah ada absensi karyawan+arah dalam ±cooldown. Simetris: antrean disk node bisa
    mengirim event lebih tua setelah yang baru. Filter waktu di Python (lihat recompute_day)."""
    window = timedelta(minutes=settings.attendance_cooldown_min)
    ts_local = _local(ts)
    rows = db.query(AttendanceEvent).filter(
        AttendanceEvent.employee_id == employee_id, AttendanceEvent.direction == direction)
    return any(abs(_local(r.ts_event) - ts_local) <= window for r in rows)


def handle_face_event(db, event) -> AttendanceEvent | None:
    """Event attendance -> match -> AttendanceEvent + recompute_day.

    Embedding dibuang dari payload pada semua jalur (data biometrik tidak disimpan di
    tabel event). Exception dibiarkan naik; caller (events_consumer) yang rollback.
    """
    if event.type != "attendance":
        return None

    payload = dict(event.payload or {})
    embedding = payload.pop("embedding", None)
    crop = payload.get("crop_path")

    direction = payload.get("direction")
    if direction not in VALID_DIRECTIONS:
        logger.warning("attendance: direction %r tidak valid pada event %s — skip", direction, event.event_id)
        return _save(db, event, payload, None)

    if embedding:
        res = face.match_vector(embedding, payload.get("face_quality"))
    elif crop:
        res = face.match_crop(db, str(Path(settings.storage_root) / crop))
    else:
        logger.info("attendance: event %s tanpa embedding dan crop — skip", event.event_id)
        return _save(db, event, payload, None)

    if res.employee_id is None:
        payload["employee_id"] = None
        payload["match_reason"] = res.reason
        logger.info("attendance: event %s tidak cocok (%s)", event.event_id, res.reason)
        return _save(db, event, payload, None)

    emp = db.get(Employee, res.employee_id)
    payload["employee_id"] = res.employee_id
    payload["employee_name"] = emp.name if emp is not None else None
    payload["face_score"] = res.score
    if emp is not None and crop:
        annotate_face_crop(str(Path(settings.storage_root) / crop),
                           emp.name, res.score or 0.0, payload.get("face_bbox"))

    if _in_cooldown(db, res.employee_id, direction, event.ts_event):
        payload["match_reason"] = "cooldown"
        return _save(db, event, payload, None)

    payload["match_reason"] = "matched"
    row = AttendanceEvent(
        employee_id=res.employee_id,
        camera_id=event.camera_id,
        zone_id=event.zone_id,
        direction=direction,
        ts_event=event.ts_event,
        match_score=res.score,
        snapshot_path=crop,
        event_id=event.event_id,
    )
    db.add(row)
    _save(db, event, payload, None)
    db.refresh(row)
    recompute_day(db, res.employee_id, _local(event.ts_event).date())
    return row
```

- [ ] **Step 4: Jalankan tes**

Run: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`
Expected: semua PASS, termasuk tes lama `test_handle_face_event_*` (jalur `match_crop` dan skip tanpa crop tetap berlaku).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/attendance.py backend/tests/test_attendance_logic.py
git commit -m "feat(attendance): cooldown per karyawan+arah, embedding tidak disimpan, match tanpa crop"
```

---

### Task 9: Frontend — setelan wajah di Advanced, editor zona attendance tanpa trigger

**Files:**
- Modify: `frontend/src/api/detection.ts`, `frontend/src/features/config/DetectionPage.tsx`, `frontend/src/features/config/ZonesPage.tsx`, `frontend/src/features/config/GatesPage.tsx`, `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/detection.test.tsx`, `frontend/src/__tests__/zones.test.tsx`, `frontend/src/__tests__/gates.test.tsx`

**Interfaces:**
- Consumes: API `detector-settings` dengan lima field wajah (Task 7).
- Produces: `DetectorSettings` type memuat `face_min_width_px, face_min_det_score, face_max_yaw, face_blur_min, face_min_frames: number`; testid `zone-attendance-hint`, `gates-face-hint`; input id `face-min-width`, `face-min-score`, `face-max-yaw`, `face-blur-min`, `face-min-frames`.

- [ ] **Step 1: Tulis tes yang gagal**

`detection.test.tsx` — perluas fixture `settings` dengan `face_min_width_px: 80, face_min_det_score: 0.6, face_max_yaw: 0.35, face_blur_min: 120, face_min_frames: 3`, lalu tambah:

```tsx
test('grup Wajah attendance di Advanced ikut tersimpan', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const body = url.includes('/detector-settings') ? settings : url.includes('/zones') ? [zone] : url.includes('/cameras') ? [camera] : { id: 1, username: 'admin', role: 'admin' }
    return { ok: true, status: 200, json: async () => body }
  }))
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=detection']}><ConfigurationPage /></MemoryRouter></I18nProvider>)

  expect(await screen.findByText('Deteksi & Model')).toBeInTheDocument()
  await userEvent.click(screen.getByText('Advanced'))
  expect(screen.getByText('Wajah attendance')).toBeInTheDocument()
  await userEvent.clear(screen.getByLabelText('Jumlah frame wajah bagus (K)'))
  await userEvent.type(screen.getByLabelText('Jumlah frame wajah bagus (K)'), '5')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan setelan global' }))
  await waitFor(() => {
    const put = calls.find((c) => c.url.endsWith('/detector-settings') && c.init?.method === 'PUT')
    expect(put).toBeTruthy()
    const body = JSON.parse(String(put!.init!.body))
    expect(body.face_min_frames).toBe(5)
    expect(body.face_min_width_px).toBe(80)
  })
})
```

`zones.test.tsx` — ganti tes `'tipe Attendance: arah + satu trigger threshold, tanpa daftar behavior'` dengan:

```tsx
test('tipe Attendance: arah + petunjuk area wajah, tanpa input trigger', async () => {
  const fetchMock = await selectZone([
    zoneFix({ type: 'attendance', direction: 'entry', behaviors: [{ kind: 'attendance', trigger_seconds: 0 }] }),
  ])

  expect(screen.getByLabelText('Masuk')).toBeInTheDocument()
  expect(screen.queryByTestId('zone-behavior-intrusion')).not.toBeInTheDocument()
  expect(screen.queryByTestId('zone-trigger')).not.toBeInTheDocument()
  expect(screen.getByTestId('zone-attendance-hint')).toHaveTextContent(/wajah/i)
  fireEvent.click(screen.getByTestId('zone-save'))

  await waitFor(() => expect(patchBody(fetchMock).direction).toBe('entry'))
})
```

`gates.test.tsx` — hapus `'admin ubah trigger threshold per gate ...'` dan `'viewer tidak bisa ubah trigger threshold'`; di `'perubahan gate yang tersimpan memunculkan notifikasi sukses'` ganti baris `fireEvent.change(screen.getByTestId('gate-trigger-1'), ...)` dengan `fireEvent.change(document.querySelector('#gate-dir-1')!, { target: { value: 'exit' } })`; tambah:

```tsx
test('gate attendance tanpa kolom trigger, dengan petunjuk area wajah', async () => {
  stubFetch([gate(1, 'entry')])
  renderPage()

  await screen.findByTestId('gate-row-1')
  expect(screen.queryByTestId('gate-trigger-1')).not.toBeInTheDocument()
  expect(screen.getByTestId('gates-face-hint')).toHaveTextContent(/wajah/i)
})
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/detection.test.tsx src/__tests__/zones.test.tsx src/__tests__/gates.test.tsx`
Expected: tiga tes baru FAIL (teks "Wajah attendance" tidak ada, `zone-trigger` masih ada, `gates-face-hint` tidak ada).

- [ ] **Step 3: Implementasi**

`src/app/i18n.tsx` — kunci baru di `id` (dan padanannya di `en`); hapus `'gates.col.trigger'` dari kedua kamus:

| kunci | id | en |
|---|---|---|
| `detection.faceGroup` | Wajah attendance | Attendance face |
| `detection.faceMinWidth` | Lebar wajah minimum (px) | Minimum face width (px) |
| `detection.faceMinScore` | Skor deteksi wajah minimum | Minimum face detection score |
| `detection.faceMaxYaw` | Batas menyamping (yaw, 0–1) | Maximum yaw (0–1) |
| `detection.faceBlurMin` | Ambang ketajaman (blur) | Sharpness threshold (blur) |
| `detection.faceMinFrames` | Jumlah frame wajah bagus (K) | Good face frames (K) |
| `zones.attendanceHint` | Gambar poligon di area tempat wajah terlihat, bukan lantai. Event terbit setelah beberapa frame wajah yang jelas (atur di Deteksi & Model → Advanced). | Draw the polygon where faces are visible, not the floor. An event fires after a few clear face frames (set in Detection & Model → Advanced). |
| `gates.faceHint` | Gate dikenali dari wajah: gambar zona di area tempat wajah terlihat (tab Zona Deteksi). | Gates recognise faces: draw the zone where faces are visible (Detection Zones tab). |

`src/api/detection.ts` — tambah ke `DetectorSettings`: `face_min_width_px: number; face_min_det_score: number; face_max_yaw: number; face_blur_min: number; face_min_frames: number`.

`DetectionPage.tsx` — `save` mengirim kelima field wajah; di blok `det-advanced` setelah tombol-toggle motion dan sebelum tombol simpan:

```tsx
          <h4>{t('detection.faceGroup')}</h4>
          <NumberInput id="face-min-width" label={t('detection.faceMinWidth')} min={16} max={1000} step={1}
            value={settings.face_min_width_px}
            onChange={(_, { value }) => setSettings({ ...settings, face_min_width_px: Number(value) })} />
          <NumberInput id="face-min-score" label={t('detection.faceMinScore')} min={0.1} max={0.99} step={0.05}
            value={settings.face_min_det_score}
            onChange={(_, { value }) => setSettings({ ...settings, face_min_det_score: Number(value) })} />
          <NumberInput id="face-max-yaw" label={t('detection.faceMaxYaw')} min={0.05} max={1} step={0.05}
            value={settings.face_max_yaw}
            onChange={(_, { value }) => setSettings({ ...settings, face_max_yaw: Number(value) })} />
          <NumberInput id="face-blur-min" label={t('detection.faceBlurMin')} min={0} step={10}
            value={settings.face_blur_min}
            onChange={(_, { value }) => setSettings({ ...settings, face_blur_min: Number(value) })} />
          <NumberInput id="face-min-frames" label={t('detection.faceMinFrames')} min={1} max={20} step={1}
            value={settings.face_min_frames}
            onChange={(_, { value }) => setSettings({ ...settings, face_min_frames: Number(value) })} />
```

`ZonesPage.tsx` — hapus `setAttendanceTrigger`; ganti cabang `selected.type === 'attendance'` (NumberInput `zone-trigger`) dengan:

```tsx
                {selected.type === 'attendance' ? (
                  <p data-testid="zone-attendance-hint" style={{ fontSize: 12, color: 'var(--cds-text-secondary)', margin: 0 }}>
                    {t('zones.attendanceHint')}
                  </p>
                ) : (
```

`GatesPage.tsx` — hapus `'gates.col.trigger'` dari `headers` dan `TableCell` yang berisi `NumberInput` `gate-trigger-${z.id}`; tambahkan di atas tabel:

```tsx
      <p data-testid="gates-face-hint" style={{ fontSize: 12, color: 'var(--cds-text-secondary)', margin: '0 0 8px' }}>
        {t('gates.faceHint')}
      </p>
```

- [ ] **Step 4: Jalankan tes**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: vitest semua PASS; build exit 0; lint tanpa warning baru (bandingkan dengan `git stash`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/detection.ts frontend/src/features/config/DetectionPage.tsx frontend/src/features/config/ZonesPage.tsx frontend/src/features/config/GatesPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/detection.test.tsx frontend/src/__tests__/zones.test.tsx frontend/src/__tests__/gates.test.tsx
git commit -m "feat(config-ui): setelan wajah attendance di Advanced, zona attendance tanpa trigger"
```

---

### Task 10: Frontend — overlay halus + TTL, label gerbang, badge mode player, hasil wajah di Events

**Files:**
- Create: `frontend/src/features/live/playerMode.ts`
- Modify: `frontend/src/features/live/LiveViewPage.tsx`, `frontend/src/features/events/EventsPage.tsx`, `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/liveview.test.tsx`, `frontend/src/__tests__/events.test.tsx`

**Interfaces:**
- Consumes: overlay `kind="face"` dengan `label` kode gerbang (Task 5); payload event `employee_name`, `match_reason` (Task 8).
- Produces: `playerMode(video) -> 'WebRTC' | 'MSE' | null`; testid `player-mode`, `event-face-match`; `DetBox.at: number`; konstanta `BOX_TTL_MS = 1000`.

- [ ] **Step 1: Tulis tes yang gagal**

`liveview.test.tsx` — tambah import `import { playerMode } from '../features/live/playerMode'` dan tiga tes (salin setup `FakeWS` dari tes `'WS detections renders kind-specific boxes ...'`):

```tsx
test('kotak deteksi hilang sendiri bila tidak diperbarui 1 detik', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const handlers: { onmessage?: (ev: { data: string }) => void }[] = []
  class FakeWS {
    onmessage: ((ev: { data: string }) => void) | null = null
    onerror: (() => void) | null = null
    constructor(_url: string) { handlers.push(this as { onmessage?: (ev: { data: string }) => void }) }
    close() {}
    send() {}
    addEventListener() {}
    removeEventListener() {}
  }
  vi.stubGlobal('WebSocket', FakeWS as unknown as typeof WebSocket)
  vi.stubGlobal('fetch', stubFetch())
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  renderPage()
  await screen.findByText('CAM-01')
  await user.click(screen.getByTestId('cam-tile-1'))
  await act(async () => {
    handlers[0].onmessage?.({ data: JSON.stringify({
      type: 'detections', camera_id: 1, kind: 'person',
      boxes: [{ id: 9, bbox_norm: [0.1, 0.1, 0.5, 0.6], label: null }],
    }) })
  })
  expect(screen.getByTestId('debug-box-person-9')).toBeInTheDocument()
  await act(async () => { vi.advanceTimersByTime(1300) })
  expect(screen.queryByTestId('debug-box-person-9')).not.toBeInTheDocument()
  vi.useRealTimers()
})

test('label kode gerbang wajah diterjemahkan', async () => {
  const handlers: { onmessage?: (ev: { data: string }) => void }[] = []
  class FakeWS {
    onmessage: ((ev: { data: string }) => void) | null = null
    onerror: (() => void) | null = null
    constructor(_url: string) { handlers.push(this as { onmessage?: (ev: { data: string }) => void }) }
    close() {}
    send() {}
    addEventListener() {}
    removeEventListener() {}
  }
  vi.stubGlobal('WebSocket', FakeWS as unknown as typeof WebSocket)
  vi.stubGlobal('fetch', stubFetch())
  renderPage()
  await screen.findByText('CAM-01')
  await userEvent.click(screen.getByTestId('cam-tile-1'))
  await act(async () => {
    handlers[0].onmessage?.({ data: JSON.stringify({
      type: 'detections', camera_id: 1, kind: 'face',
      boxes: [{ id: 2, bbox_norm: [0.2, 0.2, 0.3, 0.3], label: 'small' }],
    }) })
  })
  expect(screen.getByTestId('debug-box-face-2')).toBeInTheDocument()
  expect(screen.getByTestId('debug-overlay')).toHaveTextContent('wajah terlalu kecil')
})

test('playerMode membaca transport aktif dari elemen video', () => {
  expect(playerMode({ srcObject: {} as MediaStream, src: '' })).toBe('WebRTC')
  expect(playerMode({ srcObject: null, src: 'blob:http://x/1' })).toBe('MSE')
  expect(playerMode({ srcObject: null, src: '' })).toBeNull()
  expect(playerMode(null)).toBeNull()
})
```

`events.test.tsx`:

```tsx
test('detail event attendance menampilkan hasil pencocokan wajah', async () => {
  const att: EventOut[] = [{ id: 3, event_id: 'ev-3', type: 'attendance', camera_id: 1, zone_id: 9, severity: 'info',
    ts_event: '2026-09-23T02:00:00Z', payload: { match_reason: 'no_match', employee_id: null, crop_path: 'crops/x.jpg' },
    clip_path: null, snapshot_path: null }]
  vi.stubGlobal('fetch', stubFetch(att))
  renderPage()
  expect(await screen.findByTestId('event-face-match')).toHaveTextContent('Tidak dikenal')
})

test('detail event attendance cooldown menampilkan nama + keterangan', async () => {
  const att: EventOut[] = [{ id: 4, event_id: 'ev-4', type: 'attendance', camera_id: 1, zone_id: 9, severity: 'info',
    ts_event: '2026-09-23T02:00:00Z', payload: { match_reason: 'cooldown', employee_id: 1, employee_name: 'Budi' },
    clip_path: null, snapshot_path: null }]
  vi.stubGlobal('fetch', stubFetch(att))
  renderPage()
  expect(await screen.findByTestId('event-face-match')).toHaveTextContent('Budi · sudah tercatat (cooldown)')
})
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/liveview.test.tsx src/__tests__/events.test.tsx`
Expected: FAIL — modul `playerMode` tidak ada, kotak tidak hilang, teks label/`event-face-match` tidak ada.

- [ ] **Step 3: Implementasi**

`src/features/live/playerMode.ts`:

```ts
/** Transport aktif player go2rtc: WebRTC memakai srcObject, MSE memakai blob URL. */
export function playerMode(video: Pick<HTMLVideoElement, 'srcObject' | 'src'> | null): 'WebRTC' | 'MSE' | null {
  if (!video) return null
  if (video.srcObject) return 'WebRTC'
  if (video.src?.startsWith('blob:')) return 'MSE'
  return null
}
```

`src/app/i18n.tsx` — kunci baru:

| kunci | id | en |
|---|---|---|
| `live.faceGate.zone` | di luar zona | outside zone |
| `live.faceGate.small` | wajah terlalu kecil | face too small |
| `live.faceGate.score` | skor rendah | low score |
| `live.faceGate.yaw` | menyamping | turned away |
| `live.faceGate.blur` | buram | blurry |
| `events.col.face` | Wajah | Face |
| `events.face.unknown` | Tidak dikenal | Unknown |
| `events.face.cooldown` | sudah tercatat (cooldown) | already recorded (cooldown) |

`LiveViewPage.tsx`:
- `type DetBox = { id: number; bbox_norm: number[]; label?: string | null; kind: DetectionKind; at: number }`; konstanta `const BOX_TTL_MS = 1000` dan `const FACE_GATE_CODES = ['zone', 'small', 'score', 'yaw', 'blur']`.
- Handler WS: `const at = Date.now()` lalu map box `({ ...box, kind, at })`.
- Di `LiveViewPage` tambah efek pembersih kotak basi:

```tsx
  useEffect(() => {
    const timer = setInterval(() => {
      setBoxes((prev) => {
        const now = Date.now()
        const fresh = prev.filter((b) => now - b.at < BOX_TTL_MS)
        return fresh.length === prev.length ? prev : fresh
      })
    }, 250)
    return () => clearInterval(timer)
  }, [])
```

- Di `DebugOverlay`, `<rect>` diberi `style={{ transition: 'x 150ms linear, y 150ms linear, width 150ms linear, height 150ms linear' }}`, dan label memakai:

```tsx
  const boxLabel = (b: DetBox) =>
    b.kind === 'face' && b.label && FACE_GATE_CODES.includes(b.label)
      ? t(`live.faceGate.${b.label}` as TKey)
      : b.label ?? t('live.trackId').replace('{n}', String(b.id))
```

  (import `type TKey` dari `../../app/i18n`).
- Di `CameraTile` (hanya untuk `big`):

```tsx
  const [mode, setMode] = useState<'WebRTC' | 'MSE' | null>(null)
  useEffect(() => {
    if (!big || !streaming) return
    const timer = setInterval(() => setMode(playerMode(elRef.current?.querySelector('video') ?? null)), 1000)
    return () => clearInterval(timer)
  }, [big, streaming])
```

  dan render, di dalam div tile setelah elemen video/snapshot:

```tsx
      {big && mode && (
        <span data-testid="player-mode" style={{ position: 'absolute', bottom: 6, left: 10, fontSize: 10,
          color: '#c6c6c6', fontFamily: 'var(--cds-font-family-mono, monospace)' }}>{mode}</span>
      )}
```

`EventsPage.tsx` — helper di dalam komponen dan baris baru di `ev-meta-grid` (setelah `events.col.type`):

```tsx
  const faceMatch = (p: Record<string, unknown> | null): string => {
    const name = typeof p?.employee_name === 'string' ? p.employee_name : null
    if (name) return p?.match_reason === 'cooldown' ? `${name} · ${t('events.face.cooldown')}` : name
    if (p?.match_reason === 'no_match' || p?.match_reason === 'low_quality') return t('events.face.unknown')
    return '—'
  }
```

```tsx
                {selected.type === 'attendance' && (
                  <div className="ev-meta">
                    <dt className="ev-meta__k">{t('events.col.face')}</dt>
                    <dd className="ev-meta__v" data-testid="event-face-match">{faceMatch(selected.payload)}</dd>
                  </div>
                )}
```

- [ ] **Step 4: Jalankan tes**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: vitest semua PASS; build exit 0; lint tanpa warning baru.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/live/playerMode.ts frontend/src/features/live/LiveViewPage.tsx frontend/src/features/events/EventsPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/liveview.test.tsx frontend/src/__tests__/events.test.tsx
git commit -m "feat(live,events): overlay halus + TTL, label gerbang wajah, mode player, hasil wajah di Events"
```

---

### Task 11: Tes GPU, docs, deploy, verifikasi lapangan

**Files:**
- Create: `vision/tests/test_face_worker_gpu.py`, `docs/runbooks/attendance-face-first.md`
- Modify: `CHANGELOG.md`, `ROADMAP.md`, `README.md` (baris `analyzers/` di peta repo: `face_gate.py` → `face_worker.py` di `vision/vision/`), `docs/detection-behavior-inventory.md` (§6 rantai attendance dan §10 batas max_age → sudah diperbaiki)
- Evidence: `docs/evidence/r5b-*.png`

**Interfaces:**
- Consumes: semua task sebelumnya.

- [ ] **Step 1: Tes bertanda `gpu` (dijalankan di server)**

`vision/tests/test_face_worker_gpu.py`:

```python
"""R5b end-to-end di GPU server: SCRFD + ArcFace asli pada foto enrollment."""
import glob
import os

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.gpu

ROOT = os.environ.get("VISION_FACE_MODEL_DIR", "")
PHOTOS = sorted(glob.glob(os.path.join(os.path.dirname(ROOT), "faces", "*", "*_crop.jpg")))


@pytest.mark.skipif(not ROOT or not PHOTOS, reason="butuh VISION_FACE_MODEL_DIR + foto enrollment")
def test_real_models_embed_enrollment_photo_consistently():
    from vision.face import FaceEmbedder
    emb = FaceEmbedder(ROOT, "cuda:2")
    img = cv2.imread(PHOTOS[0])
    faces = emb.detect_faces(img)
    assert faces, "SCRFD tidak menemukan wajah di foto enrollment"
    f = max(faces, key=lambda d: d.bbox[2] - d.bbox[0])
    v1 = np.array(emb.embed(emb.align(img, f.kps)))
    v2 = np.array(emb.embed(emb.align(cv2.GaussianBlur(img, (3, 3), 0), f.kps)))
    assert float(v1 @ v2) > 0.9      # foto yang sama, sedikit diburamkan -> tetap orang yang sama
```

Run di server: `cd /home/gspe-ai3/project_cv/I-Sentinel && set -a && . ./vision.env && set +a && /home/gspe-ai3/vision-venv/bin/python -m pytest vision/tests/test_face_worker_gpu.py -q -m gpu`
Expected: 1 passed.

- [ ] **Step 2: Runbook**

`docs/runbooks/attendance-face-first.md` berisi: urutan deploy (`git pull` → `alembic upgrade head` dengan venv `/home/gspe-ai3/isentinel-venv` → restart `isentinel-api` → restart `vision-node`, tunggu `journalctl -u vision-node | grep "started .* worker"`), **gambar ulang zona attendance 7/8/9/11 di area kepala**, cara membaca label gerbang di debugger, langkah kalibrasi `face_stats` (≥10 lintasan, catat distribusi `blur` dan `width_px`, setel `face_blur_min`/`face_min_width_px` di Advanced), dan rollback (`git revert` rentang R5b, `alembic downgrade 0015`, restart API + vision; pembersihan embedding lama tidak kembali).

- [ ] **Step 3: Verifikasi suite lengkap lokal**

Run berurutan: vision, backend, frontend (perintah di Global Constraints). Catat angka persis.

- [ ] **Step 4: Deploy (izin user diperlukan untuk push branch ini dan tulis ke server)**

Push `feat/attendance-face-first`, lalu jalankan urutan runbook di `gspe-ai3`. Verifikasi:
- `alembic current` = `0016`; `SELECT count(*) FROM event WHERE type='attendance' AND payload::text LIKE '%embedding%'` = 0.
- Retained config `isentinel/config/server` memuat `face` dengan enam kunci.
- Heartbeat `modules.face.device == "cuda:2"`; setelah ada orang di kamera attendance, `loaded == true` dan `nvidia-smi --query-compute-apps` menunjukkan proses vision di GPU index 2.

- [ ] **Step 5: Verifikasi lapangan bersama user (spec §11)**

User menggambar ulang zona 9 lalu melakukan skenario 2–6 spec §11. Periksa juga UI baru (grup
Advanced "Wajah attendance", petunjuk zona/gate, badge mode player) di 1440 px dan 390 px tanpa
overflow horizontal (`node temp/tools/cdp-viewport.mjs`), screenshot ke `docs/evidence/`. Untuk tiap skenario ambil bukti dari DB (`event`, `attendance_event`) dan file di `STORAGE_ROOT`; screenshot debugger dan detail Events ke `docs/evidence/r5b-*.png`. Jangan klaim berhasil tanpa baris DB + file di disk. Lakukan kalibrasi (skenario 7) dan catat nilai final.

- [ ] **Step 6: Dokumentasi dan commit**

- `CHANGELOG.md`: bagian "R5b — Attendance face-first" (konteks, commit per task, bukti angka tes dan lapangan, dampak GPU/CPU, rollback).
- `ROADMAP.md`: bagian R5b dengan status dan bukti; tandai temuan terbuka #2 (max_age) selesai.
- `README.md`, `docs/detection-behavior-inventory.md`: sesuaikan alur attendance.

```bash
git add docs/ CHANGELOG.md ROADMAP.md README.md vision/tests/test_face_worker_gpu.py
git commit -m "docs: R5b attendance face-first — runbook, bukti lapangan, roadmap"
```
