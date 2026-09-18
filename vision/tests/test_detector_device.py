"""Task 9: detector_device pin — forwarding ke predict + fail-fast saat invalid."""
import numpy as np
import pytest

from vision import hardware
from vision.config import NodeSettings
from vision.node import VisionNode
from vision.pipeline.detector import PersonDetector


def test_validate_pin_accepts_valid_cuda_index(fake_nvml):
    fake_nvml([("A", 0, 100, 0, []), ("B", 0, 100, 0, []), ("C", 0, 100, 0, [])])
    assert hardware.validate_device_pin("cuda:2") is None
    assert hardware.validate_device_pin("") is None
    assert hardware.validate_device_pin("cpu") is None


def test_validate_pin_rejects_missing_cuda_index(fake_nvml):
    fake_nvml([("A", 0, 100, 0, []), ("B", 0, 100, 0, [])])
    assert hardware.validate_device_pin("cuda:1") is None  # idx 0..count-1 valid
    assert "cuda:2" in hardware.validate_device_pin("cuda:2")
    assert "cuda:5" in hardware.validate_device_pin("cuda:5")


def test_node_exits_when_pin_invalid(fake_nvml):
    fake_nvml([])
    cfg = NodeSettings(node_id="n1", detector_device="cuda:0", cameras_json="[]")
    node = VisionNode(cfg=cfg, transport=type("T", (), {"close": staticmethod(lambda: None)})())
    with pytest.raises(SystemExit):
        node.run()


def test_node_starts_when_pin_valid(fake_nvml):
    fake_nvml([("A", 0, 100, 0, []), ("B", 0, 100, 0, [])])
    cfg = NodeSettings(node_id="n1", detector_device="cuda:1", cameras_json="[]")
    node = VisionNode(cfg=cfg, transport=type("T", (), {"close": staticmethod(lambda: None)})())
    node.run()  # tidak ada kamera: run selesai normal tanpa SystemExit


def test_detector_forwards_device_to_predict(monkeypatch):
    sent = {}

    class FakeYOLO:
        def __init__(self, path):
            pass

        def predict(self, frame, **kw):
            sent.update(kw)
            return []

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "ultralytics":
            import types
            m = types.ModuleType("ultralytics")
            m.YOLO = FakeYOLO
            return m
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    det = PersonDetector("m.pt", device="cuda:1")
    det.detect(np.zeros((480, 640, 3), dtype=np.uint8))
    assert sent["device"] == "cuda:1"

    sent.clear()
    det_auto = PersonDetector("m.pt")
    det_auto.detect(np.zeros((480, 640, 3), dtype=np.uint8))
    assert "device" not in sent
