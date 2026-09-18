"""GPU hardware probe (pynvml) + heartbeat payload hw/modules."""
import json

import pytest

from vision import hardware
from vision.config import NodeSettings
from vision.node import VisionNode
from vision.pipeline.detector import PersonDetector
from vision.pipeline.source import FrameSource

import numpy as np


def test_collect_gpu_info_empty_without_pynvml(monkeypatch):
    import builtins, sys
    monkeypatch.delitem(sys.modules, "pynvml", raising=False)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pynvml" or name.startswith("pynvml."):
            raise ImportError("no pynvml")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert hardware.collect_gpu_info() == {}
    assert hardware.gpu_count() == 0


def test_collect_gpu_info_reads_nvml(fake_nvml):
    fake_nvml([
        ("NVIDIA GeForce RTX 4090", 9000, 24564, 12, [(1234, "ollama", 9000)]),
        ("NVIDIA GeForce RTX 5080", 0, 16303, 0, []),
    ])
    hw = hardware.collect_gpu_info()
    assert len(hw["gpus"]) == 2
    g0 = hw["gpus"][0]
    assert g0["name"] == "NVIDIA GeForce RTX 4090"
    assert g0["vram_used_mb"] == 9000 and g0["vram_total_mb"] == 24564
    assert g0["util_pct"] == 12
    assert g0["processes"][0]["pid"] == 1234
    assert g0["processes"][0]["mem_mb"] == 9000
    assert hw["gpus"][1]["processes"] == []
    assert hardware.gpu_count() == 2


def test_collect_gpu_info_own_process_vram(fake_nvml):
    import os
    pid = os.getpid()
    fake_nvml([("X", 500, 16303, 0, [(pid, "python", 500)])])
    hw = hardware.collect_gpu_info()
    assert hw["python_vram_mb"] == 500


class FakeTransport:
    def __init__(self):
        self.heartbeats = []

    def publish_event(self, ev):
        pass

    def publish_heartbeat(self, hb):
        self.heartbeats.append(hb)

    def close(self):
        pass


def test_heartbeat_payload_carries_hw_and_modules(fake_nvml):
    fake_nvml([("NVIDIA GeForce RTX 4090", 9000, 24564, 12, [])])
    cfg = NodeSettings(node_id="n1", heartbeat_s=100.0, cameras_json=json.dumps([
        {"camera_id": 1, "source_url": "test://1"}]))
    node = VisionNode(cfg=cfg,
                      detector_factory=lambda cid: PersonDetector("yolo26s.pt"),
                      source_factory=lambda cam: FrameSource.from_frames(
                          [np.zeros((4, 4, 3), dtype=np.uint8)], fps=5.0),
                      transport=FakeTransport())
    node.run()
    hb = node.transport.heartbeats[0]
    assert "hw" in hb and "modules" in hb
    assert len(hb["hw"]["gpus"]) == 1
    assert hb["modules"]["detector"]["device"] == "auto"
    assert hb["modules"]["detector"]["model"] == "yolo26s.pt"
    # heartbeat lama tetap: ts/cpu/cameras ada
    assert hb["ts"] and "cameras" in hb


def test_heartbeat_reports_pinned_device(fake_nvml):
    fake_nvml([("A", 0, 100, 0, []), ("B", 0, 100, 0, [])])
    cfg = NodeSettings(node_id="n1", heartbeat_s=100.0, detector_device="cuda:1",
                       cameras_json="[]")
    node = VisionNode(cfg=cfg, detector_factory=lambda cid: None,
                      source_factory=lambda cam: None, transport=FakeTransport())
    node.run()
    hb = node.transport.heartbeats[0]
    assert hb["modules"]["detector"]["device"] == "cuda:1"
