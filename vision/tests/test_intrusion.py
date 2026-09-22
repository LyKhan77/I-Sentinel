"""IntrusionAnalyzer + point_in_polygon tests. Pure math, no cv2/MQTT."""
from datetime import datetime

from vision.analyzers import ANALYZERS
from vision.analyzers.intrusion import IntrusionAnalyzer, point_in_polygon

SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
# concave L-shape: notch cut out of bottom-right quadrant
CONCAVE = [[0.0, 0.0], [1.0, 0.0], [1.0, 0.4], [0.4, 0.4], [0.4, 1.0], [0.0, 1.0]]


class FakeTrack:
    def __init__(self, tid, bbox, centroid):
        self.id = tid
        self.bbox = bbox
        self.centroid = centroid


def zone(**kw):
    z = {"id": 7, "name": "Zona A", "type": "restricted", "severity": "warning",
         "polygon": SQUARE, "schedule": None}
    z.update(kw)
    return z


def one_track(tid, centroid, bbox=(0.0, 0.0, 0.1, 0.1)):
    return [FakeTrack(tid, bbox, centroid)]


# --- point_in_polygon ---

def test_point_in_polygon_square():
    assert point_in_polygon((0.5, 0.5), SQUARE) is True
    assert point_in_polygon((1.5, 0.5), SQUARE) is False
    assert point_in_polygon((-0.1, 0.5), SQUARE) is False


def test_point_in_polygon_concave():
    assert point_in_polygon((0.2, 0.7), CONCAVE) is True   # inside vertical arm
    assert point_in_polygon((0.7, 0.7), CONCAVE) is False  # inside the notch
    assert point_in_polygon((0.7, 0.2), CONCAVE) is True   # inside horizontal arm


# --- IntrusionAnalyzer ---

def test_registry_has_intrusion():
    assert ANALYZERS["intrusion"] is IntrusionAnalyzer


def test_enter_emit_once_stay_silent_leave_reenter():
    az = IntrusionAnalyzer(zone())
    ts = datetime(2024, 1, 15, 10, 0).timestamp()  # Monday 10:00 local
    # enters polygon
    evs = az.on_frame(ts, one_track(1, (0.5, 0.5)), 640, 480)
    assert len(evs) == 1
    ev = evs[0]
    assert ev == {"zone_id": 7, "type": "intrusion", "severity": "warning",
                  "payload": {"zone_name": "Zona A", "track_id": 1,
                              "confidence": None, "bbox_norm": [0.0, 0.0, 0.1, 0.1]}}
    # stays inside -> nothing
    assert az.on_frame(ts + 1, one_track(1, (0.6, 0.5)), 640, 480) == []
    # leaves -> nothing
    assert az.on_frame(ts + 2, one_track(1, (1.5, 0.5)), 640, 480) == []
    # re-enters -> emits again
    evs = az.on_frame(ts + 3, one_track(1, (0.5, 0.5)), 640, 480)
    assert len(evs) == 1 and evs[0]["payload"]["track_id"] == 1


def test_schedule_inactive_no_events():
    az = IntrusionAnalyzer(zone(schedule={"days": [1], "start": "04:00", "end": "05:00"}))
    ts = datetime(2024, 1, 15, 3, 0).timestamp()  # Monday 03:00 — outside window
    assert az.on_frame(ts, one_track(1, (0.5, 0.5)), 640, 480) == []


def test_schedule_active_emits():
    az = IntrusionAnalyzer(zone(schedule={"days": [1], "start": "02:00", "end": "04:00"}))
    ts = datetime(2024, 1, 15, 3, 0).timestamp()  # Monday 03:00 — inside window
    assert len(az.on_frame(ts, one_track(1, (0.5, 0.5)), 640, 480)) == 1


def test_schedule_wrong_day_no_events():
    az = IntrusionAnalyzer(zone(schedule={"days": [2], "start": "00:00", "end": "23:59"}))
    ts = datetime(2024, 1, 15, 10, 0).timestamp()  # Monday=1, days=[2]
    assert az.on_frame(ts, one_track(1, (0.5, 0.5)), 640, 480) == []


def test_lost_track_state_cleaned():
    az = IntrusionAnalyzer(zone())
    ts = datetime(2024, 1, 15, 10, 0).timestamp()
    az.on_frame(ts, one_track(1, (0.5, 0.5)), 640, 480)
    assert az._inside == {1}
    # track disappears (lost) -> removed from state so a re-appearing id re-emits
    az.on_frame(ts + 1, [], 640, 480)
    assert az._inside == set()
    assert len(az.on_frame(ts + 2, one_track(1, (0.5, 0.5)), 640, 480)) == 1


# --- R5: trigger threshold (lama di zona sebelum emit) -----------------------

def test_trigger_threshold_holds_emit_until_track_stays():
    from vision.analyzers.intrusion import IntrusionAnalyzer
    zone = {"id": 1, "name": "Z", "severity": "warning",
            "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            "trigger_seconds": 2}
    az = IntrusionAnalyzer(zone)
    assert az.on_frame(1000.0, one_track(1, (0.5, 0.5)), 640, 480) == []       # baru masuk
    assert az.on_frame(1001.9, one_track(1, (0.5, 0.5)), 640, 480) == []       # belum 2s
    evs = az.on_frame(1002.0, one_track(1, (0.5, 0.5)), 640, 480)              # tepat 2s
    assert len(evs) == 1 and evs[0]["type"] == "intrusion"
    assert az.on_frame(1003.0, one_track(1, (0.5, 0.5)), 640, 480) == []       # tidak dobel


def test_trigger_threshold_restarts_after_leaving():
    from vision.analyzers.intrusion import IntrusionAnalyzer
    zone = {"id": 1, "name": "Z", "severity": "warning",
            "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            "trigger_seconds": 2}
    az = IntrusionAnalyzer(zone)
    assert az.on_frame(1000.0, one_track(1, (0.5, 0.5)), 640, 480) == []
    assert az.on_frame(1001.0, one_track(1, (1.5, 0.5)), 640, 480) == []       # keluar
    assert az.on_frame(1001.5, one_track(1, (0.5, 0.5)), 640, 480) == []       # masuk lagi
    assert az.on_frame(1003.4, one_track(1, (0.5, 0.5)), 640, 480) == []       # 1.9s
    assert len(az.on_frame(1003.5, one_track(1, (0.5, 0.5)), 640, 480)) == 1   # 2s sejak masuk
