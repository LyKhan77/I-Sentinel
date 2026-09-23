"""IntrusionAnalyzer + point_in_polygon tests. Pure math, no cv2/MQTT."""
from datetime import datetime

from vision.analyzers import ANALYZERS
from vision.analyzers.intrusion import IntrusionAnalyzer, ground_point, point_in_polygon
from vision.analyzers.running import RunningAnalyzer

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


def _bbox_standing_at(centroid):
    """bbox yang titik pijaknya TEPAT di `centroid` — analyzer zona memakai titik pijak,
    jadi 'track di titik P' pada tes lama tetap berarti P."""
    cx, cy = centroid
    return (cx - 0.05, cy - 0.1, cx + 0.05, cy)


def one_track(tid, centroid, bbox=None):
    return [FakeTrack(tid, bbox or _bbox_standing_at(centroid), centroid)]


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
                              "confidence": None, "bbox_norm": list(_bbox_standing_at((0.5, 0.5)))}}
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


# --- keanggotaan zona diukur dari titik pijak (bottom-center), bukan centroid ----

# Pita lantai di bagian bawah frame, seperti zona 6 cam 357 di gspe-ai3.
FLOOR_BAND = [[0.33, 1.0], [0.65, 1.0], [0.61, 0.72], [0.36, 0.72]]


def standing_person(tid=1, feet_y=0.90, height=0.40, x=0.50, width=0.12):
    """Orang berdiri: kaki di `feet_y`, centroid melayang setengah tinggi di atasnya."""
    bbox = (x - width / 2, feet_y - height, x + width / 2, feet_y)
    centroid = (x, feet_y - height / 2)
    return FakeTrack(tid, bbox, centroid)


def test_person_standing_on_zone_counts_as_inside_even_if_centroid_is_above_it():
    """Zona digambar di lantai; makin jauh orang dari kamera makin tinggi centroid-nya.

    Kaki di y=0.90 (di dalam pita 0.72-1.0) tapi centroid di y=0.70 (di luar).
    Orang ini berdiri DI ATAS zona, jadi harus dihitung masuk.
    """
    track = standing_person(feet_y=0.90, height=0.40)
    assert not point_in_polygon(track.centroid, FLOOR_BAND)   # centroid memang di luar

    analyzer = IntrusionAnalyzer(zone(polygon=FLOOR_BAND, trigger_seconds=0))
    events = analyzer.on_frame(0.0, [track], 1920, 1080)

    assert [e["type"] for e in events] == ["intrusion"]


def test_person_walking_past_above_the_zone_stays_outside():
    """Kaki di y=0.60, di atas pita — tidak boleh memicu."""
    analyzer = IntrusionAnalyzer(zone(polygon=FLOOR_BAND, trigger_seconds=0))
    assert analyzer.on_frame(0.0, [standing_person(feet_y=0.60, height=0.30)], 1920, 1080) == []


def test_all_zone_analyzers_use_the_same_ground_point():
    """intrusion/loitering/running sepakat: orang berdiri DI ATAS zona
    dihitung masuk, walau centroid-nya melayang di luar polygon."""
    on_zone = standing_person(feet_y=0.90, height=0.40)
    above_zone = standing_person(feet_y=0.60, height=0.30)
    assert not point_in_polygon(on_zone.centroid, FLOOR_BAND)
    assert point_in_polygon(ground_point(on_zone), FLOOR_BAND)
    assert not point_in_polygon(ground_point(above_zone), FLOOR_BAND)

    spec = zone(polygon=FLOOR_BAND, trigger_seconds=0, loiter_seconds=1, direction="in")

    def emitted(name, track):
        az = ANALYZERS[name](dict(spec))
        # dua frame: loitering perlu akumulasi dwell lintas frame
        return az.on_frame(0.0, [track], 1920, 1080) + az.on_frame(2.0, [track], 1920, 1080)

    for name in ("intrusion", "loitering"):
        assert emitted(name, on_zone), f"{name}: orang berdiri di atas zona tidak dianggap masuk"
        assert emitted(name, above_zone) == [], f"{name}: orang di luar zona malah memicu"


def test_running_measures_membership_from_ground_point():
    """running memakai titik pijak untuk keanggotaan zona (kecepatan tetap dari centroid)."""
    spec = zone(polygon=FLOOR_BAND, speed_limit_mps=0.5, trigger_seconds=0)
    analyzer = RunningAnalyzer(dict(spec), meters_per_pixel=0.01)
    a = standing_person(tid=1, feet_y=0.90, height=0.40, x=0.40)
    b = standing_person(tid=1, feet_y=0.90, height=0.40, x=0.60)

    analyzer.on_frame(0.0, [a], 1920, 1080)
    assert analyzer.on_frame(1.0, [b], 1920, 1080), "track berlari di atas zona tidak terdeteksi"
