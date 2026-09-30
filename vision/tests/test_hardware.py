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

    def publish_detections(self, camera_id, boxes, kind="person"):
        self.detections = getattr(self, 'detections', [])
        self.detections.append((camera_id, kind, boxes))

    def close(self):
        pass


def test_heartbeat_payload_carries_hw_and_modules(fake_nvml):
    fake_nvml([("NVIDIA GeForce RTX 4090", 9000, 24564, 12, [])])
    cfg = NodeSettings(node_id="n1", heartbeat_s=100.0, emit_person_detect=True,
                       cameras_json=json.dumps([
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


def test_heartbeat_reports_detector_call_count(fake_nvml):
    """detect_n = jumlah pemanggilan detektor — instrumen untuk mengukur motion gate."""
    fake_nvml([("NVIDIA GeForce RTX 4090", 9000, 24564, 12, [])])
    cfg = NodeSettings(node_id="n1", heartbeat_s=100.0, cameras_json="[]")
    node = VisionNode(cfg=cfg, transport=FakeTransport())
    PersonDetector.detect_n = 7
    PersonDetector.detect_ms_total = 140.0

    assert node._detector_module_info()["detect_n"] == 7


def _proc(tmp_path, stat_line, avail_kb=4_000_000, total_kb=16_000_000):
    (tmp_path / "stat").write_text(stat_line + "\ncpu0 1 1 1 1 0 0 0 0\n")
    (tmp_path / "meminfo").write_text(f"MemTotal: {total_kb} kB\nMemFree: 1 kB\nMemAvailable: {avail_kb} kB\n")
    return str(tmp_path)


def test_host_stats_cpu_delta_ram_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(hardware, "_prev_cpu", None)
    root = _proc(tmp_path, "cpu  100 0 100 800 0 0 0 0 0 0")
    first = hardware.host_stats(str(tmp_path), proc_root=root)
    assert first["cpu_pct"] is None  # butuh dua sampel
    assert first["ram_total_mb"] == 15625 and first["ram_used_mb"] == 11719
    assert 0 <= first["disk_used_pct"] <= 100 and first["disk_free_gb"] > 0
    _proc(tmp_path, "cpu  200 0 200 900 0 0 0 0 0 0")  # +200 busy, +100 idle
    assert hardware.host_stats(str(tmp_path), proc_root=root)["cpu_pct"] == 66.7


def test_host_stats_without_proc_is_null(tmp_path, monkeypatch):
    monkeypatch.setattr(hardware, "_prev_cpu", None)
    s = hardware.host_stats(str(tmp_path), proc_root=str(tmp_path / "missing"))
    assert s["cpu_pct"] is None and s["ram_total_mb"] is None and s["disk_free_gb"] is not None
