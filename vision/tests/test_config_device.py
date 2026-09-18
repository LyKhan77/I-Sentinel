"""Config push device: apply_config terima/reject pin, hot-reload tanpa restart."""
import json

import numpy as np
import pytest

from vision import hardware
from vision.config import CameraCfg, NodeSettings
from vision.node import VisionNode
from vision.pipeline.detector import MockDetector
from vision.pipeline.source import FrameSource


def _node(device="", detector_device_env="", cameras=None):
    cfg = NodeSettings(node_id="n1", detector_device=detector_device_env,
                       cameras_json=cameras or "[]")
    node = VisionNode(cfg=cfg, transport=type("T", (), {"close": staticmethod(lambda: None)})())
    return node


def test_apply_config_accepts_valid_device(fake_nvml, monkeypatch):
    fake_nvml([("A", 0, 100, 0, []), ("B", 0, 100, 0, []), ("C", 0, 100, 0, [])])
    cfg = NodeSettings(node_id="n1", cameras_json=json.dumps(
        [{"camera_id": 1, "source_url": "test://1"}]))
    node = VisionNode(cfg=cfg, transport=type("T", (), {"close": staticmethod(lambda: None)})(),
                      source_factory=lambda cam: FrameSource.from_frames(
                          [np.zeros((4, 4, 3), dtype=np.uint8)], fps=5.0))
    node.apply_config({"detector": {"model": "yolo26s.engine", "device": "cuda:2"},
                       "cameras": [{"camera_id": 1, "source_url": "test://1"}]})
    assert node.cfg.detector_device == "cuda:2"
    # factory hasil rebuild memakai device yang dipush
    assert node.detector_factory(1).device == "cuda:2"


def test_apply_config_invalid_device_rejected_keeps_old(fake_nvml):
    fake_nvml([("A", 0, 100, 0, []), ("B", 0, 100, 0, [])])
    node = _node(detector_device_env="cuda:0")
    node.apply_config({"detector": {"device": "cuda:5"}, "cameras": []})
    assert node.cfg.detector_device == "cuda:0"  # keep old, node alive


def test_apply_config_empty_device_falls_back_to_env(fake_nvml):
    fake_nvml([("A", 0, 100, 0, [])])
    node = _node(detector_device_env="cuda:0")
    node.apply_config({"detector": {"device": ""}, "cameras": []})
    assert node.cfg.detector_device == "cuda:0"


def test_apply_config_without_device_key_keeps_env(fake_nvml):
    fake_nvml([("A", 0, 100, 0, [])])
    node = _node(detector_device_env="cuda:0")
    node.apply_config({"detector": {"model": "m"}, "cameras": []})
    assert node.cfg.detector_device == "cuda:0"
