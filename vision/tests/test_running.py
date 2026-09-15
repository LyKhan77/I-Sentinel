"""RunningAnalyzer tests: calibrated per-track speed (m/s) inside a zone.

Pure math + node factory, no cv2/MQTT.
"""
import logging

from vision.analyzers import ANALYZERS
from vision.analyzers.running import RunningAnalyzer
from vision.node import VisionNode
from vision.config import NodeSettings

SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]

FRAME_W = 640
FRAME_H = 480
MPP = 0.01


class FakeTrack:
    def __init__(self, tid, bbox, centroid):
        self.id = tid
        self.bbox = bbox
        self.centroid = centroid


def zone(**kw):
    z = {"id": 7, "name": "Zona Lari", "type": "restricted", "severity": "warning",
         "polygon": SQUARE, "speed_limit_mps": 1.0}
    z.update(kw)
    return z


def one_track(centroid, tid=1, bbox=(0.0, 0.0, 0.1, 0.1)):
    return [FakeTrack(tid, bbox, centroid)]


def test_registry_has_running():
    assert ANALYZERS["running"] is RunningAnalyzer


def test_slow_track_no_emit():
    # (b) 0.001 norm/frame @ dt=0.2s, mpp=0.01, frame_w=640
    # -> 0.001*640*0.01/0.2 = 0.032 m/s < limit 1.0
    az = RunningAnalyzer(zone(speed_limit_mps=1.0), MPP)
    ts = 1000.0
    for i in range(10):
        assert az.on_frame(ts + i * 0.2, one_track((0.4 + i * 0.001, 0.5)),
                           FRAME_W, 480) == []


def test_fast_track_emits_with_speed():
    # (c) 0.05 norm/frame @ dt=0.2s -> 0.05*640*0.01/0.2 = 1.6 m/s > 1.0
    az = RunningAnalyzer(zone(speed_limit_mps=1.0), MPP)
    assert az.on_frame(1000.0, one_track((0.4, 0.5)), FRAME_W, 480) == []
    evs = az.on_frame(1000.2, one_track((0.45, 0.5)), FRAME_W, 480)
    assert len(evs) == 1
    ev = evs[0]
    assert ev["type"] == "running"
    assert ev["zone_id"] == 7
    assert ev["severity"] == "warning"
    p = ev["payload"]
    assert p["zone_name"] == "Zona Lari"
    assert p["track_id"] == 1
    # 0.05*640*0.01/0.2 = 1.6 m/s exactly (EMA first sample = new_s)
    assert abs(p["speed_mps"] - 1.6) <= 0.05
    assert p["confidence"] is None
    assert p["bbox_norm"] == [0.0, 0.0, 0.1, 0.1]


def test_fast_vertical_track_scales_by_frame_height():
    # y axis must scale by frame_h (480), not frame_w: 0.05*480*0.01/0.2 = 1.2 m/s
    az = RunningAnalyzer(zone(speed_limit_mps=1.0), MPP)
    assert az.on_frame(1000.0, one_track((0.4, 0.4)), FRAME_W, FRAME_H) == []
    evs = az.on_frame(1000.2, one_track((0.4, 0.45)), FRAME_W, FRAME_H)
    assert len(evs) == 1
    assert abs(evs[0]["payload"]["speed_mps"] - 1.2) <= 0.05


def test_cooldown_per_track():
    # (d) still fast next frame < 5s -> no 2nd emit; after >5s fast -> 2nd emit
    az = RunningAnalyzer(zone(speed_limit_mps=1.0), MPP)
    az.on_frame(1000.0, one_track((0.4, 0.5)), FRAME_W, 480)
    assert len(az.on_frame(1000.2, one_track((0.45, 0.5)), FRAME_W, 480)) == 1
    assert az.on_frame(1000.4, one_track((0.50, 0.5)), FRAME_W, 480) == []
    # 6s later, moved 0.2 norm -> new_s=0.213, EMA=0.6*1.6+0.4*0.213=1.045 > 1.0
    assert len(az.on_frame(1006.4, one_track((0.70, 0.5)), FRAME_W, 480)) == 1


def test_fast_outside_polygon_no_emit():
    # (e) fast but centroid outside the zone polygon
    az = RunningAnalyzer(zone(speed_limit_mps=1.0), MPP)
    az.on_frame(1000.0, one_track((1.1, 0.5)), FRAME_W, 480)
    assert az.on_frame(1000.2, one_track((1.15, 0.5)), FRAME_W, 480) == []


def test_speed_limit_zero_inert():
    # (f) speed_limit_mps default 0 -> inert even at high speed
    az = RunningAnalyzer(zone(speed_limit_mps=0), MPP)
    az.on_frame(1000.0, one_track((0.1, 0.5)), FRAME_W, 480)
    assert az.on_frame(1000.2, one_track((0.9, 0.5)), FRAME_W, 480) == []


def test_state_cleanup_on_track_loss():
    # track disappears -> state dropped, new id starts from scratch (no emit)
    az = RunningAnalyzer(zone(speed_limit_mps=1.0), MPP)
    az.on_frame(1000.0, one_track((0.4, 0.5), tid=1), FRAME_W, 480)
    az.on_frame(1000.2, one_track((0.45, 0.5), tid=1), FRAME_W, 480)
    assert az.on_frame(1000.4, [], FRAME_W, 480) == []
    assert az._last == {} and az._speed == {} and az._last_emit == {}


def test_factory_skips_running_without_calibration(caplog):
    # (a) zone has speed_limit_mps > 0 but no meters_per_pixel -> analyzer not built
    node = VisionNode(NodeSettings(), transport=object(), source_factory=lambda c: None)
    cfg = {"cameras": [{"camera_id": 3, "source_url": "test://3", "zones": [
        {"id": 1, "name": "R", "type": "free", "polygon": SQUARE,
         "speed_limit_mps": 2.0}]}]}
    cam = node._cameras_from_config(cfg)[0]
    assert cam.meters_per_pixel is None
    # speed_limit zone survives the camera filter (else this proves nothing)
    assert len(cam.zones) == 1
    with caplog.at_level(logging.INFO):
        assert node._make_analyzers(cam) == []
        assert node._make_analyzers(cam) == []  # rebuild must not log again
    msgs = [r.getMessage() for r in caplog.records if "no calibration" in r.getMessage()]
    assert len(msgs) == 1
    assert "camera 3" in msgs[0]


def test_factory_builds_running_with_calibration():
    node = VisionNode(NodeSettings(), transport=object(), source_factory=lambda c: None)
    cfg = {"cameras": [{"camera_id": 4, "source_url": "test://4", "meters_per_pixel": 0.01,
                        "zones": [{"id": 1, "name": "R", "type": "free",
                                   "polygon": SQUARE, "speed_limit_mps": 2.0}]}]}
    cam = node._cameras_from_config(cfg)[0]
    az = node._make_analyzers(cam)
    assert [type(a).__name__ for a in az] == ["RunningAnalyzer"]
    assert az[0].mpp == 0.01
