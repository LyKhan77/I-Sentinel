"""LoiteringAnalyzer tests: dwell accumulation per zone. Pure math, no cv2/MQTT."""
from vision.analyzers import ANALYZERS
from vision.analyzers.loitering import LoiteringAnalyzer, point_in_polygon

SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
INSIDE = (0.5, 0.5)
OUTSIDE = (1.5, 0.5)


class FakeTrack:
    def __init__(self, tid, bbox, centroid):
        self.id = tid
        self.bbox = bbox
        self.centroid = centroid


def zone(**kw):
    z = {"id": 7, "name": "Zona A", "type": "restricted", "severity": "warning",
         "polygon": SQUARE, "loiter_seconds": 15}
    z.update(kw)
    return z


def one_track(tid, centroid, bbox=(0.0, 0.0, 0.1, 0.1)):
    return [FakeTrack(tid, bbox, centroid)]


def test_registry_has_loitering():
    assert ANALYZERS["loitering"] is LoiteringAnalyzer


def test_reuses_point_in_polygon():
    assert point_in_polygon(INSIDE, SQUARE) is True
    assert point_in_polygon(OUTSIDE, SQUARE) is False


def test_dwell_below_threshold_silent_then_emit_once():
    az = LoiteringAnalyzer(zone())
    ts = 1000.0
    # (a) 6 frames x 2s = 10s inside < 15 -> no emit
    for i in range(6):
        assert az.on_frame(ts + i * 2, one_track(1, INSIDE), 640, 480) == []
    # (b) continue to 16s -> exactly one emit with a valid payload
    evs = az.on_frame(ts + 16, one_track(1, INSIDE), 640, 480)
    assert len(evs) == 1
    ev = evs[0]
    assert ev["type"] == "loitering"
    assert ev["zone_id"] == 7
    assert ev["severity"] == "warning"
    p = ev["payload"]
    assert p["zone_name"] == "Zona A"
    assert p["track_id"] == 1
    assert p["dwell_s"] >= 15
    assert p["confidence"] is None
    assert p["bbox_norm"] == [0.0, 0.0, 0.1, 0.1]
    # (c) keep loitering 30 more seconds -> still exactly one emit
    for i in range(1, 16):
        assert az.on_frame(ts + 16 + i * 2, one_track(1, INSIDE), 640, 480) == []


def test_leave_then_reenter_emits_again():
    az = LoiteringAnalyzer(zone())
    ts = 1000.0
    for i in range(9):
        az.on_frame(ts + i * 2, one_track(1, INSIDE), 640, 480)  # 16s -> emit
    assert az._emitted == {1}
    # leaves polygon -> dwell + emitted reset
    assert az.on_frame(ts + 20, one_track(1, OUTSIDE), 640, 480) == []
    assert 1 not in az._dwell and 1 not in az._emitted
    # re-enters, 14s -> still silent, then 18s -> second emit
    for i in range(7):
        assert az.on_frame(ts + 22 + i * 2, one_track(1, INSIDE), 640, 480) == []
    evs = az.on_frame(ts + 38, one_track(1, INSIDE), 640, 480)
    assert len(evs) == 1 and evs[0]["payload"]["track_id"] == 1


def test_lost_track_state_cleaned_restarts_dwell():
    az = LoiteringAnalyzer(zone())
    ts = 1000.0
    for i in range(4):
        az.on_frame(ts + i * 2, one_track(1, INSIDE), 640, 480)  # 6s dwell
    assert 1 in az._dwell and 1 in az._last_ts
    # track disappears -> state removed
    az.on_frame(ts + 8, [], 640, 480)
    assert 1 not in az._dwell and 1 not in az._emitted and 1 not in az._last_ts
    # re-appears: dwell restarts, no emit until a full dwell accrues again
    assert az.on_frame(ts + 10, one_track(1, INSIDE), 640, 480) == []
    assert az._dwell[1] == 0.0
    assert az.on_frame(ts + 20, one_track(1, INSIDE), 640, 480) == []  # dwell 10 < 15
    evs = az.on_frame(ts + 25, one_track(1, INSIDE), 640, 480)         # dwell 15 -> emit
    assert len(evs) == 1


def test_zero_loiter_seconds_is_inert():
    az = LoiteringAnalyzer(zone(loiter_seconds=0))
    ts = 1000.0
    for i in range(100):
        assert az.on_frame(ts + i * 2, one_track(1, INSIDE), 640, 480) == []
    assert az._dwell == {}


def test_ts_gap_resets_dwell_no_fake_accumulation():
    az = LoiteringAnalyzer(zone())
    ts = 1000.0
    az.on_frame(ts, one_track(1, INSIDE), 640, 480)          # dwell 0
    az.on_frame(ts + 2, one_track(1, INSIDE), 640, 480)      # dwell 2
    # >10s gap while inside -> dwell reset, no accumulation across the gap
    assert az.on_frame(ts + 100, one_track(1, INSIDE), 640, 480) == []
    assert az._dwell[1] == 0.0
    # 14s after reset (two <=10s steps) -> still below 15 (would be 116s unreset)
    az.on_frame(ts + 106, one_track(1, INSIDE), 640, 480)
    assert az.on_frame(ts + 114, one_track(1, INSIDE), 640, 480) == []
    assert az._dwell[1] == 14.0
    # 16s -> emits
    assert len(az.on_frame(ts + 116, one_track(1, INSIDE), 640, 480)) == 1
