"""GPU smoke test untuk YOLO26s TensorRT engine — marker @pytest.mark.gpu.

Jalankan di server GPU (gspe-ai3):
    cd vision && python -m pytest tests/test_detector_gpu.py -v -m gpu
Prasyarat: engine hasil scripts/export_engine.py + VISION_GPU_ENGINE=<path> env.
"""
import os

import numpy as np
import pytest

pytestmark = pytest.mark.gpu


def _engine_path() -> str:
    p = os.environ.get("VISION_GPU_ENGINE", "")
    if not p:
        pytest.skip("VISION_GPU_ENGINE not set")
    return p


def test_engine_loads_and_detects() -> None:
    from vision.pipeline.detector import PersonDetector

    det = PersonDetector(model_path=_engine_path(), nms=False, conf=0.4, imgsz=640)
    # frame sintetis 640x640 — asersi minimal: pipeline jalan & keluar struktur valid
    frame = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
    dets = det.detect(frame)
    assert isinstance(dets, list)
    for d in dets:
        assert 0.0 <= d.bbox[0] < d.bbox[2] <= 1.0
        assert 0.0 <= d.bbox[1] < d.bbox[3] <= 1.0
        assert d.conf > 0.0


def test_engine_latency_logged() -> None:
    from vision.pipeline.detector import PersonDetector

    det = PersonDetector(model_path=_engine_path(), nms=False, conf=0.4, imgsz=640)
    frame = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
    for _ in range(10):
        det.detect(frame)
    import time
    t0 = time.time()
    for _ in range(50):
        det.detect(frame)
    dt = (time.time() - t0) / 50 * 1000
    print(f"\n[gpu] latency {dt:.1f} ms/frame")
    assert dt < 200  # sanity: engine, bukan CPU fallback
