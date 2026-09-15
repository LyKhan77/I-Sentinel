import numpy as np
import pytest

from vision.pipeline.detector import Detection, MockDetector, PersonDetector


def test_mock_detector_scripted_list():
    script = [
        [Detection(bbox=(0.1, 0.1, 0.3, 0.5), conf=0.9)],
        [Detection(bbox=(0.2, 0.1, 0.4, 0.5), conf=0.8)],
    ]
    det = MockDetector(script)
    assert det.detect() == script[0]
    assert det.detect() == script[1]
    assert det.detect() == []  # exhausted


def test_mock_detector_callable():
    det = MockDetector(lambda ts: [Detection(bbox=(ts, 0, ts + 0.1, 0.2), conf=0.9)])
    out = det.detect(ts=0.5)
    assert out[0].bbox == (0.5, 0.0, 0.6, 0.2)


def test_person_detector_raises_without_ultralytics(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "ultralytics" or name.startswith("ultralytics."):
            raise ImportError("No module named 'ultralytics'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    det = PersonDetector(model_path="yolo26s.pt")
    with pytest.raises(RuntimeError, match="vision\\[gpu\\]"):
        det.detect(np.zeros((480, 640, 3), dtype=np.uint8))
