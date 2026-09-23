"""Optional node-side SCRFD face detection and ArcFace embeddings.

Failed model loads are cached to avoid retrying every frame.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FaceDet:
    """SCRFD face box and five landmarks in input-frame pixel coordinates."""

    bbox: tuple[float, float, float, float]  # xyxy
    kps: np.ndarray  # (5, 2): eyes, nose, mouth corners
    score: float


class FaceEmbedder:
    """Lazy InsightFace wrapper: detect_faces / align / embed (R5b face-first)."""

    def __init__(self, model_root: str, device: str = ""):
        self.model_root = model_root
        self.device = device  # ""=auto (CUDA→CPU), "cpu", "cuda:N"
        self._app = None
        self._failed = False
        self.detect_n = 0
        self.embed_n = 0
        # worker kamera attendance memanggil detect_faces() per frame secara paralel:
        # tanpa lock, first-load bisa memuat FaceAnalysis dua kali di GPU
        self._load_lock = threading.Lock()

    def _ensure_loaded(self):
        if self._app is not None or self._failed:
            return self._app
        with self._load_lock:
            return self._load()

    def _load(self):
        if self._app is not None or self._failed:
            return self._app
        try:
            from insightface.app import FaceAnalysis
        except ImportError:
            logger.info("insightface tidak terpasang — face detection unavailable")
            self._failed = True
            return None
        if self.device == "cpu":
            providers, ctx = ["CPUExecutionProvider"], 0
        elif self.device.startswith("cuda:"):
            ctx = int(self.device.split(":", 1)[1])
            # insightface mengabaikan ctx_id >= 0; tanpa device_id sesi jatuh ke GPU 0
            providers = [("CUDAExecutionProvider", {"device_id": ctx}), "CPUExecutionProvider"]
        else:
            providers, ctx = ["CUDAExecutionProvider", "CPUExecutionProvider"], 0
        try:
            app = FaceAnalysis(name="buffalo_l", root=self.model_root,
                               providers=providers,
                               allowed_modules=["detection", "recognition"])
            app.prepare(ctx_id=ctx, det_size=(640, 640))
        except Exception:
            logger.warning("face embedder gagal dimuat — face detection unavailable",
                           exc_info=True)
            self._failed = True
            return None
        self._app = app
        return app

    def available(self) -> bool:
        return self._ensure_loaded() is not None

    def loaded(self) -> bool:
        """Report whether the model has already loaded without triggering a load."""
        return self._app is not None

    def detect_faces(self, img: np.ndarray) -> list[FaceDet]:
        """Detect faces and five landmarks in BGR frame pixel coordinates."""
        app = self._ensure_loaded()
        if app is None:
            return []
        bboxes, kpss = app.det_model.detect(img, max_num=0, metric="default")
        self.detect_n += 1
        if kpss is None:
            return []
        return [FaceDet(bbox=tuple(float(v) for v in b[:4]),
                        kps=np.asarray(k, dtype=np.float32), score=float(b[4]))
                for b, k in zip(bboxes, kpss)]

    def align(self, img: np.ndarray, kps: np.ndarray) -> np.ndarray:
        """Align full-resolution face landmarks to ArcFace's 112×112 BGR crop."""
        from insightface.utils import face_align
        return face_align.norm_crop(img, landmark=kps, image_size=112)

    def embed(self, aligned: np.ndarray) -> list[float] | None:
        """Return normalized ArcFace embedding; omit an unavailable or zero vector."""
        app = self._ensure_loaded()
        if app is None:
            return None
        feat = np.asarray(app.models["recognition"].get_feat(aligned), dtype=np.float64).ravel()
        norm = float(np.linalg.norm(feat))
        if norm == 0.0:
            return None
        self.embed_n += 1
        return [float(v) / norm for v in feat]
