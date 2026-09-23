# Face Embed at Node (Opsi B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pindahkan inferensi face (deteksi + ArcFace embedding) ke vision node, sehingga delegasi per-node menyeluruh (YOLO + face); backend hanya match cosine vs gallery terpusat.

**Architecture:** Vision node memotong crop (logika existing `needs_crop`) lalu embed di GPU node via InsightFace `buffalo_l`. Event MQTT payload ditambah `embedding` (512-d L2-normed) + `face_quality`. Backend `handle_face_event`: payload ada `embedding` → match gallery langsung (tanpa InsightFace); tidak ada → fallback status quo (backend embed crop). Gallery tetap server — enroll baru tetap efektif tanpa sentuh edge (kriteria brief Fase E tetap terpenuhi). Crop jpeg tetap di-upload untuk bukti UI.

**Tech Stack:** InsightFace (SCRFD + ArcFace, onnxruntime) di vision node (extra `face`), numpy/cv2 existing, FastAPI backend unchanged deps.

**Branch:** `feat/face-embed-at-node`

**Compat / rollback:** Tanpa `embedding` di payload, backend jalan persis seperti sekarang. Node fallback otomatis ke kirim-crop-saja bila insightface tidak terpasang/model gagal dimuat. Kill-switch env `VISION_FACE_EMBED=false`.

---

### Task 0: Branch

- [ ] **Step 1: Buat branch**

```bash
git checkout main && git pull && git checkout -b feat/face-embed-at-node
```

---

### Task 1: FaceEmbedder di vision node

**Files:**
- Create: `vision/vision/face.py`
- Test: `vision/tests/test_face_embed.py`

- [ ] **Step 1: Write the failing test**

```python
"""Opsi B: FaceEmbedder di node — lazy import, fallback, embed_jpeg."""
import numpy as np
import pytest

from vision.face import FaceEmbedder


def _jpeg_bytes(w=320, h=240):
    import cv2
    img = np.zeros((h, w, 3), np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


class FakeApp:
    """Fake insightface FaceAnalysis: satu 'wajah' fixed."""
    def get(self, img):
        class F:
            det_score = 0.9
            bbox = np.array([10.0, 10.0, 100.0, 100.0])
            normed_embedding = np.ones(512) / np.sqrt(512)
        return [F()]


def test_embedder_unavailable_without_insightface(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "insightface", None)
    emb = FaceEmbedder(model_root="/tmp/x")
    assert emb.available() is False
    assert emb.embed_jpeg(_jpeg_bytes()) is None


def test_embedder_load_failure_is_graceful(monkeypatch):
    calls = {"n": 0}
    fake_mod = types.SimpleNamespace()  # import app gagal
    import sys, types
    monkeypatch.setitem(sys.modules, "insightface.app", None)
    emb = FaceEmbedder(model_root="/tmp/x")
    assert emb.available() is False
    assert emb._failed is True  # tidak retry terus-menerus


def test_embed_jpeg_returns_vector_and_quality():
    emb = FaceEmbedder(model_root="/tmp/x")
    emb._app = FakeApp()  # inject, skip load
    res = emb.embed_jpeg(_jpeg_bytes())
    assert res is not None
    assert len(res["vector"]) == 512
    assert res["det_score"] == pytest.approx(0.9)


def test_embed_jpeg_no_face_returns_none():
    emb = FaceEmbedder(model_root="/tmp/x")
    emb._app = FakeApp()
    emb._app.get = lambda img: []
    assert emb.embed_jpeg(_jpeg_bytes()) is None


def test_embed_jpeg_bad_jpeg_returns_none():
    emb = FaceEmbedder(model_root="/tmp/x")
    emb._app = FakeApp()
    assert emb.embed_jpeg(b"notjpeg") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python -m pytest tests/test_face_embed.py -v -m "not gpu"`
Expected: FAIL — `ModuleNotFoundError: No module named 'vision.face'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Face embedding at node (Opsi B): SCRFD deteksi + ArcFace embedding di GPU node.

Insightface = dependency opsional (extra `face`). Embedder absent/gagal → node
kirim crop saja (backend embed, status quo Fase 5). `_failed` meng-cache
kegagalan supaya tidak coba muat ulang tiap frame/event.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class FaceEmbedder:
    """Lazy InsightFace wrapper: embed_jpeg(jpeg) -> {vector, det_score, bbox} | None."""

    def __init__(self, model_root: str, device: str = ""):
        self.model_root = model_root
        self.device = device  # ""=auto (CUDA→CPU), "cpu", "cuda:N"
        self._app = None
        self._failed = False

    def _ensure_loaded(self):
        if self._app is not None or self._failed:
            return self._app
        try:
            from insightface.app import FaceAnalysis
        except ImportError:
            logger.info("insightface tidak terpasang — node kirim crop saja")
            self._failed = True
            return None
        if self.device == "cpu":
            providers, ctx = ["CPUExecutionProvider"], 0
        elif self.device.startswith("cuda:"):
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            ctx = int(self.device.split(":", 1)[1])
        else:
            providers, ctx = ["CUDAExecutionProvider", "CPUExecutionProvider"], 0
        try:
            app = FaceAnalysis(name="buffalo_l", root=self.model_root,
                               providers=providers)
            app.prepare(ctx_id=ctx, det_size=(640, 640))
        except Exception:
            logger.warning("face embedder gagal dimuat — fallback crop saja",
                           exc_info=True)
            self._failed = True
            return None
        self._app = app
        return app

    def available(self) -> bool:
        return self._ensure_loaded() is not None

    def embed_jpeg(self, jpeg: bytes) -> dict | None:
        """Deteksi + embedding wajah TERBESAR di jpeg. None bila gagal/tidak ada wajah."""
        app = self._ensure_loaded()
        if app is None:
            return None
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        faces = app.get(img)
        if not faces:
            return None
        best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        vec = getattr(best, "normed_embedding", None)
        if vec is None:
            return None
        return {
            "vector": [float(x) for x in vec],
            "det_score": float(best.det_score),
            "bbox": [float(x) for x in best.bbox],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd vision && python -m pytest tests/test_face_embed.py -v -m "not gpu"`
Expected: PASS (5 tests)

- [ ] **Step 5: Daftarkan package + extra dependency**

Modify: `vision/pyproject.toml`

```toml
[tool.setuptools]
packages = ["vision", "vision.pipeline", "vision.transport", "vision.analyzers"]

[project.optional-dependencies]
dev = ["pytest>=8"]
gpu = ["ultralytics>=8.3", "onnxruntime-gpu>=1.19"]
face = ["insightface>=0.7", "onnxruntime-gpu>=1.19"]
```

(Cek dulu apakah `vision.analyzers` sudah terdaftar — bila ya, jangan duplikat.)

- [ ] **Step 6: Commit**

```bash
git add vision/vision/face.py vision/tests/test_face_embed.py vision/pyproject.toml
git commit -m "feat(vision): FaceEmbedder — SCRFD+ArcFace di node, fallback crop-saja"
```

---

### Task 2: Wiring node — embed dari crop, kirim embedding di payload

**Files:**
- Modify: `vision/vision/config.py` (NodeSettings)
- Modify: `vision/vision/node.py` (`__init__`, `_attach_crop`)
- Test: `vision/tests/test_node_face_embed.py`

- [ ] **Step 1: Write the failing test**

```python
"""Opsi B: node._attach_crop menempelkan embedding bila embedder siap."""
from unittest.mock import MagicMock

from vision.node import VisionNode  # sesuaikan nama class existing di node.py
from vision.face import FaceEmbedder


def _node_with_recorder(monkeypatch):
    """Node + recorder mock yang 'upload' sukses; frame substream tersedia."""
    node = MagicMock(spec=VisionNode)
    return node  # diganti setup nyata mengikuti pola test_node.py existing


def test_attach_crop_adds_embedding():
    # Pola: buat instance node minimal (ikuti fixture test_node.py), recorder
    # mock upload_bytes -> "crops/x.jpg", _mainstream_crop -> jpeg bytes,
    # face = FaceEmbedder dengan _app fake yang return vektor.
    # partial payload {"needs_crop": True, "bbox_norm": [...]}
    # expect: payload["embedding"] len 512, payload["face_quality"] float,
    #         payload["crop_path"] tetap ada.
    ...


def test_attach_crop_fallback_without_embedder():
    # face = None (atau available() False) -> payload TANPA "embedding",
    # crop_path tetap di-set (status quo).
    ...
```

(PENTING saat eksekusi: buka `vision/tests/test_node.py`, pakai fixture/cara bikin node yang sama — jangan mock spec jika ada pola nyata. Dua test di atas: embedding ditempel + fallback tanpa embedder.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python -m pytest tests/test_node_face_embed.py -v -m "not gpu"`
Expected: FAIL (payload tidak punya `embedding`)

- [ ] **Step 3: Implement**

`vision/vision/config.py` — tambah 2 setting:

```python
    face_embed: bool = True   # Opsi B: embed wajah di node; False = kirim crop saja
    face_device: str = ""     # ""=auto, "cpu", "cuda:N"
    face_model_dir: str = ""  # default: <data_dir>/faces_models
```

`vision/vision/node.py`:

Di `__init__` (setelah recorder setup):

```python
        from .face import FaceEmbedder
        self.face = (FaceEmbedder(self.cfg.face_model_dir
                                  or os.path.join(self.cfg.data_dir, "faces_models"),
                                  self.cfg.face_device)
                     if self.cfg.face_embed else None)
```

Di `_attach_crop`, setelah `path = self.recorder.upload_bytes(...)` sukses (sebelum `payload["crop_path"] = path`):

```python
        if path:
            payload["crop_path"] = path
            if self.face is not None:
                res = self.face.embed_jpeg(jpeg)
                if res:
                    payload["embedding"] = res["vector"]
                    payload["face_quality"] = res["det_score"]
```

(Jpeg bytes sudah ada di variabel `jpeg` — tidak ada fetch kedua.)

- [ ] **Step 4: Run tests to verify it passes + regresi**

Run: `cd vision && python -m pytest tests -q -m "not gpu"`
Expected: semua PASS (termasuk test_node.py existing — fallback path pasti tetap jalan karena embedder None di test env tanpa insightface)

- [ ] **Step 5: Commit**

```bash
git add vision/vision/config.py vision/vision/node.py vision/tests/test_node_face_embed.py
git commit -m "feat(vision): embed wajah di node — payload event bawa embedding + face_quality"
```

---

### Task 3: Backend — match dari embedding node

**Files:**
- Modify: `backend/app/services/face.py` (tambah `match_vector`)
- Modify: `backend/app/services/attendance.py:92-119` (`handle_face_event`)
- Test: `backend/tests/test_attendance_logic.py` (tambah kasus)

- [ ] **Step 1: Write the failing test**

Tambah ke `backend/tests/test_attendance_logic.py` (ikuti fixture existing — event attendance + crop):

```python
def test_handle_face_event_with_node_embedding(db, monkeypatch):
    """Payload bawa embedding → match gallery langsung, tanpa engine backend."""
    called = {"embed": 0}
    monkeypatch.setattr(face, "match_crop", lambda db_, p: called.__setitem__("embed", called["embed"] + 1))
    monkeypatch.setattr(face, "match_vector",
                        lambda vec, q=None: face.MatchResult(7, 0.83, q, "matched"))
    ev = _make_attendance_event(payload={
        "direction": "in", "crop_path": "crops/x.jpg",
        "embedding": [0.1] * 512, "face_quality": 0.9,
    })
    row = attendance.handle_face_event(db, ev)
    assert row is not None and row.employee_id == 7
    assert called["embed"] == 0  # backend TIDAK embed ulang


def test_handle_face_event_low_quality_rejected(db, monkeypatch):
    monkeypatch.setattr(face, "match_vector",
                        lambda vec, q=None: face.MatchResult(None, None, q, "low_quality"))
    ev = _make_attendance_event(payload={
        "direction": "in", "crop_path": "crops/x.jpg",
        "embedding": [0.1] * 512, "face_quality": 0.1,
    })
    assert attendance.handle_face_event(db, ev) is None


def test_handle_face_event_fallback_crop_without_embedding(db, monkeypatch):
    """Tanpa embedding → jalur lama (match_crop) — status quo terjaga."""
    monkeypatch.setattr(face, "match_crop",
                        lambda db_, p: face.MatchResult(3, 0.8, 0.9, "matched"))
    ev = _make_attendance_event(payload={"direction": "in", "crop_path": "crops/x.jpg"})
    row = attendance.handle_face_event(db, ev)
    assert row is not None and row.employee_id == 3
```

(Nama helper `_make_attendance_event` mengikuti yang sudah ada di file itu; bila belum ada, ekstrak dari test existing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_attendance_logic.py -v -m "not gpu"`
Expected: FAIL — `match_vector` belum ada

- [ ] **Step 3: Implement**

`backend/app/services/face.py` — tambah setelah `match_crop`:

```python
def match_vector(vector, quality: float | None = None) -> MatchResult:
    """Cocokkan embedding dari node (Opsi B) ke gallery. reason: low_quality|matched|no_match.

    quality berasal dari det_score node; threshold sama dengan match_crop.
    """
    if quality is not None and quality < settings.face_min_quality:
        return MatchResult(None, None, quality, "low_quality")
    hit = gallery.match(list(vector))
    if hit is None:
        return MatchResult(None, None, quality, "no_match")
    employee_id, score = hit
    return MatchResult(employee_id, score, quality, "matched")
```

(Verifikasi nama global gallery di face.py — dipakai `match_crop` existing, sama punya.)

`backend/app/services/attendance.py` — ganti baris `res = face.match_crop(...)`:

```python
    if payload.get("embedding"):
        res = face.match_vector(payload["embedding"], payload.get("face_quality"))
    else:
        res = face.match_crop(db, str(Path(settings.storage_root) / crop))
```

- [ ] **Step 4: Run tests + regresi backend**

Run: `cd backend && python -m pytest tests -q -m "not gpu"`
Expected: semua PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/face.py backend/app/services/attendance.py backend/tests/test_attendance_logic.py
git commit -m "feat(backend): match embedding dari node — tanpa inferensi wajah di server"
```

---

### Task 4: Docs + CHANGELOG + deploy note

**Files:**
- Modify: `DESIGN.md` (section attendance/face: alur Opsi B)
- Modify: `CHANGELOG.md` (entry baru)
- Modify: `docs/runbooks/` bila ada runbook vision env

- [ ] **Step 1: DESIGN.md** — update alur attendance: node crop → embed di GPU node → event MQTT bawa `embedding`+`face_quality` → backend match gallery (tanpa engine wajah); fallback: tanpa embedding → backend embed crop. Enroll tetap di server.
- [ ] **Step 2: CHANGELOG.md** — context (delegasi per-node utk Fase E), files, evidence, impact, rollback (`VISION_FACE_EMBED=false`).
- [ ] **Step 3: Deploy note (server gspe-ai3):**
  - `pip install -e "vision/[face]"` di venv server (insightface + onnxruntime-gpu)
  - model `faces_models` sudah ada di STORAGE_ROOT — set `VISION_FACE_MODEL_DIR` mengarah ke situ
  - restart `isentinel-vision` (kill cgroup procs, Restart=always)
- [ ] **Step 4: Commit**

```bash
git add DESIGN.md CHANGELOG.md docs/runbooks/
git commit -m "docs: alur attendance Opsi B — embed di node, match di server"
```

---

### Task 5: Verifikasi end-to-end (server)

- [ ] **Step 1: Deploy ke gspe-ai3** (butuh akses/key dari user): pull branch, install extra face, restart vision unit.
- [ ] **Step 2: Uji attendance nyata**: orang lewat face-gate zone → AttendanceEvent terbentuk via jalur embedding (log backend `attendance: ... matched`, payload event ada `embedding`), crop tetap tampil di UI.
- [ ] **Step 3: Uji fallback**: `VISION_FACE_EMBED=false` + restart → event tanpa embedding tetap match via crop (jalur lama).
- [ ] **Step 4: Update checkpoint** `.cooper/context/task12-face-embed.md` + merge ke main bila lulus.

## Self-Review

- Spec coverage: delegasi inferensi wajah ke node (B) ✓; galeri tetap server ✓; fallback status quo ✓; kill-switch ✓; device pin face via env ✓ (UI pin face = Fase E, tidak sekarang).
- Placeholder: Task 2 Step 1 sengaja merujuk pola fixture `test_node.py` existing — eksekutor wajib baca file itu dulu (di-plan eksplisit).
- Type consistency: `MatchResult(employee_id, score, quality, reason)` konsisten dgn existing; payload key `embedding`/`face_quality` dipakai sama di node & backend.
