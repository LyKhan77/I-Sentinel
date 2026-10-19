"""LoiteringAnalyzer tests: dwell accumulation per zone. Pure math, no cv2/MQTT."""
from datetime import datetime

from vision.analyzers import ANALYZERS
from vision.analyzers.loitering import LoiteringAnalyzer, point_in_polygon

SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
INSIDE = (0.5, 0.5)
OUTSIDE = (1.5, 0.5)
# Jadwal kerja 08:00-17:00 dengan istirahat 12:00-13:00 pada Senin 2024-01-15.
WORK_BREAK = {"days": [1], "start": "08:00", "end": "17:00", "breaks": [{"start": "12:00", "end": "13:00"}]}


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


def _bbox_standing_at(centroid):
    """bbox yang titik pijaknya TEPAT di `centroid` — analyzer zona memakai titik pijak,
    jadi 'track di titik P' pada tes lama tetap berarti P."""
    cx, cy = centroid
    return (cx - 0.05, cy - 0.1, cx + 0.05, cy)


def one_track(tid, centroid, bbox=None):
    return [FakeTrack(tid, bbox or _bbox_standing_at(centroid), centroid)]


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
    assert p["bbox_norm"] == list(_bbox_standing_at(INSIDE))
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


def test_loitering_silent_outside_schedule_and_during_break():
    """Zona jadwal penuh: 07:00 (di luar jam) dan 12:30 (istirahat) diam; 09:00 kontrol 1 event."""
    # 07:00 — di luar jendela kerja: tanpa event walau track menginap dwell
    az = LoiteringAnalyzer(zone(schedule=WORK_BREAK))
    ts = datetime(2024, 1, 15, 7, 0).timestamp()
    for i in range(4):
        assert az.on_frame(ts + i * 5, one_track(1, INSIDE), 640, 480) == []
    # 12:30 — di dalam istirahat: tanpa event
    az = LoiteringAnalyzer(zone(schedule=WORK_BREAK))
    ts = datetime(2024, 1, 15, 12, 30).timestamp()
    for i in range(4):
        assert az.on_frame(ts + i * 5, one_track(1, INSIDE), 640, 480) == []
    # 09:00 — jendela kerja: kontrol terbit (4×5 dtk dwell = 15)
    az = LoiteringAnalyzer(zone(schedule=WORK_BREAK))
    ts = datetime(2024, 1, 15, 9, 0).timestamp()
    evs = [az.on_frame(ts + i * 5, one_track(1, INSIDE), 640, 480) for i in range(4)]
    assert len(evs[-1]) == 1
    assert len(evs[-2]) == 0


def test_loitering_dwell_does_not_carry_across_break():
    """Dwell pra-istirahat tidak terbawa: state dibuang di frame off-window (semua gap <= MAX_DELTA)."""
    az = LoiteringAnalyzer(zone(schedule=WORK_BREAK))
    t0 = datetime(2024, 1, 15, 11, 59, 45).timestamp()
    assert az.on_frame(t0, one_track(1, INSIDE), 640, 480) == []        # dwell 0
    assert az.on_frame(t0 + 5, one_track(1, INSIDE), 640, 480) == []    # dwell 5
    # tepat 12:00 off-window: membuang _dwell/_last_ts, bukan menambah dwell (bug: dwell 15 emit)
    assert az.on_frame(t0 + 10, one_track(1, INSIDE), 640, 480) == []
    assert az.on_frame(t0 + 15, one_track(1, INSIDE), 640, 480) == []
    assert az._dwell == {} and az._last_ts == {}
    # sesudah istirahat: gap 3556 dtk reset; dwell segar tidak memenuhi ambang
    t1 = datetime(2024, 1, 15, 13, 0, 1).timestamp()
    assert az.on_frame(t1, one_track(1, INSIDE), 640, 480) == []
    assert az.on_frame(t1 + 5, one_track(1, INSIDE), 640, 480) == []
    assert az.on_frame(t1 + 10, one_track(1, INSIDE), 640, 480) == []
