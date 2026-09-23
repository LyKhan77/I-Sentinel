"""Face embedding at node (Opsi B): SCRFD deteksi + ArcFace embedding di GPU node.

Insightface = dependency opsional (extra `face`). Embedder absent/gagal → node
kirim crop saja (backend embed, status quo Fase 5). `_failed` meng-cache
kegagalan supaya tidak coba muat ulang tiap frame/event.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class FaceEmbedder:
    """Lazy InsightFace wrapper: embed_jpeg(jpeg) -> {vector, det_score, bbox} | None."""

    def __init__(self, model_root: str, device: str = ""):
        self.model_root = model_root
        self.device = device  # ""=auto (CUDA→CPU), "cpu", "cuda:N"
        self._app = None
        self._failed = False
        # worker kamera attendance memanggil detect() per frame secara paralel:
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

    def detect(self, img) -> list[tuple[float, float, float, float, float]]:
        """Deteksi saja (SCRFD, tanpa embedding) pada frame BGR -> [(x1,y1,x2,y2,score)] piksel."""
        app = self._ensure_loaded()
        if app is None:
            return []
        bboxes, _ = app.det_model.detect(img, max_num=0, metric="default")
        return [tuple(float(v) for v in b[:5]) for b in bboxes]

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
