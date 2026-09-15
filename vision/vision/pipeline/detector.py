"""Person detector interface: Ultralytics YOLO behind lazy import + test mock."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Detection:
    bbox: tuple[float, float, float, float]  # xyxy NORMALIZED 0-1
    conf: float


class PersonDetector:
    """Ultralytics YOLO person detector (class 0), normalized xyxy output.

    ultralytics is imported lazily on first detect() call — install the
    `gpu` extra to use it. Model loading happens on first detect().
    """

    def __init__(self, model_path: str, nms: bool = False, conf: float = 0.4, imgsz: int = 640):
        self.model_path = model_path
        self.nms = nms
        self.conf = conf
        self.imgsz = imgsz
        self._model = None

    def _load(self):
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise RuntimeError(
                "ultralytics not installed — install vision[gpu] extra to use PersonDetector"
            ) from e
        self._model = YOLO(self.model_path)

    def detect(self, frame: np.ndarray, ts: float = 0.0) -> list[Detection]:
        if self._model is None:
            self._load()
        results = self._model.predict(
            frame, conf=self.conf, iou=0.7 if self.nms else 0.0, imgsz=self.imgsz, verbose=False
        )
        out: list[Detection] = []
        for r in results:
            h, w = r.orig_shape
            for box in r.boxes:
                if int(box.cls) != 0:  # person only
                    continue
                x1, y1, x2, y2 = (float(v) for v in box.xyxyn[0])
                out.append(Detection(bbox=(x1, y1, x2, y2), conf=float(box.conf)))
        return out


class MockDetector:
    """Returns pre-scripted detections: list-of-lists per call, or callable(ts)."""

    def __init__(self, script):
        if not callable(script):
            script = iter(list(script))
        self._script = script

    def detect(self, frame: np.ndarray | None = None, ts: float = 0.0) -> list[Detection]:
        if callable(self._script):
            return list(self._script(ts))
        try:
            return list(next(self._script))
        except StopIteration:
            return []
