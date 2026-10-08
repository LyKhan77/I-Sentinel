"""identity_zones + _start_camera: registry identitas hanya untuk zona critical ber-face_id."""
import json

import pytest

from vision.config import NodeSettings
from vision.node import VisionNode, identity_zones
from vision.pipeline.detector import MockDetector
from vision.pipeline.source import FrameSource

from tests.test_config_apply_per_camera import (FakeRecorder, FakeTransport, HoldSource,
                                                make_node, node_with)  # noqa: F401

CRITICAL_POLY = [[0, 0], [1, 0], [1, 1], [0, 1]]


def zone_with(severity="critical", behaviors=None, zone_id=15):
    return {"id": zone_id, "name": "Server", "polygon": CRITICAL_POLY,
            "severity": severity, "direction": "entry",
            "behaviors": behaviors if behaviors is not None else
            [{"kind": "intrusion", "trigger_seconds": 0, "face_id": True},
             {"kind": "attendance", "trigger_seconds": 3}]}


def test_identity_zones_requires_critical_intrusion_with_face_id_true():
    assert [z["id"] for z in identity_zones({"zones": [zone_with()]})] == [15]
    assert identity_zones({"zones": [zone_with(severity="warning")]}) == []
    no_flag = [{"kind": "intrusion", "trigger_seconds": 0}]
    assert identity_zones({"zones": [zone_with(behaviors=no_flag)]}) == []  # face_id absen
    off = [{"kind": "intrusion", "trigger_seconds": 0, "face_id": False}]
    assert identity_zones({"zones": [zone_with(behaviors=off)]}) == []
    str_flag = [{"kind": "intrusion", "trigger_seconds": 0, "face_id": "true"}]
    assert identity_zones({"zones": [zone_with(behaviors=str_flag)]}) == []
    loiter = [{"kind": "loitering", "trigger_seconds": 30, "face_id": True}]
    assert identity_zones({"zones": [zone_with(behaviors=loiter)]}) == []


def _face_node(tmp_path, monkeypatch, cameras):
    monkeypatch.setattr("vision.recorder.Recorder", FakeRecorder)
    FakeRecorder.instances = []
    cfg = NodeSettings(node_id="n", cameras_json=json.dumps(cameras), await_config=True,
                       data_dir=str(tmp_path), api_key="")
    from tests.test_config_apply_per_camera import FakeFace
    node = VisionNode(cfg=cfg, detector_factory=lambda cid: MockDetector([]),
                      source_factory=lambda cam: HoldSource(), transport=FakeTransport())
    node.face = FakeFace()
    return node


def test_start_camera_shares_one_registry_between_detect_and_face_workers(tmp_path, monkeypatch):
    node = _face_node(tmp_path, monkeypatch, [{
        "camera_id": 1, "source_url": "test://1", "zones": [zone_with()],
    }])
    node._start_camera(node._cameras_from_config(
        {"cameras": [{"camera_id": 1, "source_url": "test://1", "zones": [zone_with()]}]})[0])
    kinds = sorted(type(w).__name__ for w in node._workers)
    assert kinds == ["CameraWorker", "FaceGateWorker"]
    cam = next(w for w in node._workers if type(w).__name__ == "CameraWorker")
    face = next(w for w in node._workers if type(w).__name__ == "FaceGateWorker")
    assert cam.registry is face.collector.registry and cam.registry is not None
    assert [z["id"] for z in cam.ident_zones] == [15]
    assert face.collector is not None
    node._stop_workers()


def test_start_camera_without_face_id_creates_no_registry(tmp_path, monkeypatch):
    z = zone_with(behaviors=[{"kind": "intrusion", "trigger_seconds": 0}])
    node = _face_node(tmp_path, monkeypatch, [{"camera_id": 1, "source_url": "test://1", "zones": [z]}])
    node._start_camera(node._cameras_from_config(
        {"cameras": [{"camera_id": 1, "source_url": "test://1", "zones": [z]}]})[0])
    cam = next(w for w in node._workers if type(w).__name__ == "CameraWorker")
    assert cam.registry is None and cam.ident_zones == []
    node._stop_workers()


def test_start_camera_face_id_without_attendance_zone_warns_and_skips(tmp_path, monkeypatch, caplog):
    """Kamera critical ber-face_id tanpa zona attendance (worker wajah): peringatan, tanpa registry."""
    z = zone_with(behaviors=[{"kind": "intrusion", "trigger_seconds": 0, "face_id": True}])
    node = _face_node(tmp_path, monkeypatch, [{"camera_id": 1, "source_url": "test://1", "zones": [z]}])
    import logging
    with caplog.at_level(logging.WARNING, logger="vision.node"):
        node._start_camera(node._cameras_from_config(
        {"cameras": [{"camera_id": 1, "source_url": "test://1", "zones": [z]}]})[0])
    assert any("face_id" in r.message.lower() for r in caplog.records)
    cams = [w for w in node._workers if type(w).__name__ == "CameraWorker"]
    assert cams and cams[0].registry is None  # tanpa worker wajah → identitas tidak aktif
    node._stop_workers()


def test_face_id_toggle_restarts_only_that_camera(tmp_path, monkeypatch):
    node = _face_node(tmp_path, monkeypatch, [])
    z1 = zone_with(zone_id=15)
    z1_off = zone_with(zone_id=15, behaviors=[
        {"kind": "intrusion", "trigger_seconds": 0, "face_id": False},
        {"kind": "attendance", "trigger_seconds": 3}])
    z2 = {"id": 20, "name": "Gudang", "polygon": CRITICAL_POLY, "severity": "critical",
          "direction": "entry",
          "behaviors": [{"kind": "intrusion", "trigger_seconds": 0, "face_id": True},
                        {"kind": "attendance", "trigger_seconds": 3}]}
    cfg1 = {"camera_id": 1, "source_url": "test://1", "zones": [z1]}
    cfg2 = {"camera_id": 2, "source_url": "test://2", "zones": [z2]}
    node.apply_config({"cameras": [cfg1, cfg2]})
    before2 = [w for w in node._workers if w.camera_id == 2]
    node.apply_config({"cameras": [dict(cfg1, zones=[z1_off]), cfg2]})
    after2 = [w for w in node._workers if w.camera_id == 2]
    assert all(not w2 is w1 for w1, w2 in zip(before2, after2)) or after2 == before2
    assert all(w.is_alive() for w in after2)  # kamera 2 tidak direstart
    cam1 = next(w for w in node._workers if w.camera_id == 1
                and type(w).__name__ == "CameraWorker")
    assert cam1.registry is None  # face_id dimatikan → registry dibongkar
    node._stop_workers()


def test_identity_zones_tolerates_legacy_zone_without_severity():
    z = {"id": 3, "polygon": CRITICAL_POLY,
         "behaviors": [{"kind": "intrusion", "trigger_seconds": 0, "face_id": True}]}
    assert identity_zones({"zones": [z]}) == []  # tanpa severity critical → tidak masuk
