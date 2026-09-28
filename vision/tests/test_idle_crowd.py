"""Idle and crowd episodes, reminders, schedule, and node integration."""
from datetime import datetime

from vision.analyzers import ANALYZERS
from vision.analyzers.crowd import CrowdAnalyzer
from vision.analyzers.idle_zone import IdleZoneAnalyzer

SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
T0 = datetime(2026, 9, 28, 10, 0).timestamp()


class T:
    def __init__(self, tid, x=0.5):
        self.id = tid
        self.bbox = (x - 0.05, 0.3, x + 0.05, 0.6)


def zone(**kw):
    z = {"id": 3, "name": "Pos", "severity": "warning", "polygon": SQUARE, "schedule": None,
         "trigger_seconds": 60, "reminder_minutes": 2}
    z.update(kw)
    return z


def run(az, frames):
    out = []
    for sec, tracks in frames:
        for ev in az.on_frame(T0 + sec, tracks, 640, 480):
            out.append((sec, ev["type"], ev["payload"]["reminder"]))
    return out


def test_registry_has_new_kinds():
    assert ANALYZERS["idle_zone"] is IdleZoneAnalyzer and ANALYZERS["crowd"] is CrowdAnalyzer


def test_idle_alerts_after_trigger_then_reminders_and_rearms():
    az = IdleZoneAnalyzer(zone())
    assert run(az, [(s, []) for s in range(0, 301, 2)]) == [
        (60, "idle_zone", 0), (180, "idle_zone", 1), (300, "idle_zone", 2)]
    assert run(az, [(302, [T(1)])]) == []
    assert run(az, [(s, []) for s in range(304, 366, 2)]) == [(364, "idle_zone", 0)]


def test_idle_payload_and_no_reminder_when_zero():
    az = IdleZoneAnalyzer(zone(reminder_minutes=0))
    evs = [ev for s in range(0, 400, 2) for ev in az.on_frame(T0 + s, [], 640, 480)]
    assert len(evs) == 1
    p = evs[0]["payload"]
    assert p["idle_s"] == 60 and p["track_id"] is None and p["bbox_norm"] is None
    assert p["zone_polygon"] == [list(pt) for pt in SQUARE] and evs[0]["zone_id"] == 3


def test_idle_respects_schedule():
    az = IdleZoneAnalyzer(zone(schedule={"days": [1], "start": "10:01", "end": "11:00"}))
    assert run(az, [(s, []) for s in range(0, 130, 2)]) == [(120, "idle_zone", 0)]


def test_crowd_alert_payload_and_reminder():
    az = CrowdAnalyzer(zone(min_count=3, trigger_seconds=10, reminder_minutes=1))
    people = [T(i, 0.2 + 0.2 * i) for i in range(3)]
    got = []
    for s in range(0, 71, 2):
        got += [(s, ev) for ev in az.on_frame(T0 + s, people, 640, 480)]
    assert [(s, e["payload"]["reminder"]) for s, e in got] == [(10, 0), (70, 1)]
    p = got[0][1]["payload"]
    assert (p["count"], p["min_count"], p["duration_s"], p["track_id"]) == (3, 3, 10, None)
    assert len(p["bboxes"]) == 3


def test_crowd_below_threshold_never_alerts():
    az = CrowdAnalyzer(zone(min_count=3, trigger_seconds=10))
    assert run(az, [(s, [T(1), T(2)]) for s in range(0, 60, 2)]) == []


def test_crowd_grace_and_reset():
    az = CrowdAnalyzer(zone(min_count=2, trigger_seconds=10, reminder_minutes=0))
    two, one = [T(1, 0.3), T(2, 0.7)], [T(1, 0.3)]
    assert run(az, [(0, two), (2, two), (4, two), (6, two), (8, one), (10, two)]) == [(10, "crowd", 0)]
    # kerumunan diam: frame paksa motion gate ~2 s + jitter; satu deteksi meleset tidak me-reset
    az = CrowdAnalyzer(zone(min_count=2, trigger_seconds=10, reminder_minutes=0))
    assert run(az, [(0, two), (2.1, two), (4.3, one), (6.6, two), (8.8, two), (10.9, two)]) == [(10.9, "crowd", 0)]
    # jumlah turun > GRACE_S (6 s) → reset; hitung ulang dari 10
    az = CrowdAnalyzer(zone(min_count=2, trigger_seconds=10, reminder_minutes=0))
    frames = [(0, two), (2, two), (4, one), (6, one), (8, one), (10, two), (12, two), (20, two), (22, two)]
    assert run(az, frames) == [(20, "crowd", 0)]


def test_merge_event_without_track():
    from vision.node import _merge_event
    partial = {"zone_id": 3, "type": "idle_zone", "severity": "warning",
               "payload": {"track_id": None, "bbox_norm": None, "idle_s": 60, "reminder": 2}}
    ev = _merge_event(9, "node", partial, T0)
    assert ev["payload"]["track_id"] is None and ev["payload"]["bbox_norm"] is None
    assert ev["dedup_key"].startswith("9:idle_zone:r2:")


def test_make_analyzers_builds_new_kinds_with_params():
    from vision.config import NodeSettings
    from vision.node import VisionNode
    z = {"id": 5, "name": "Z", "type": "behavior", "polygon": SQUARE, "active": True, "clip": True,
         "behaviors": [{"kind": "idle_zone", "trigger_seconds": 300, "reminder_minutes": 15, "clip": False},
                       {"kind": "crowd", "trigger_seconds": 30, "min_count": 7, "reminder_minutes": 0}]}
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [z]}
    node = VisionNode(NodeSettings(face_embed=False), transport=object(), source_factory=lambda c: None)
    azs = node._make_analyzers(node._cameras_from_config({"cameras": [cam]})[0])
    idle, crowd = azs
    assert (type(idle).__name__, idle.trigger, idle.reminder_s, idle.media["clip"]) == ("IdleZoneAnalyzer", 300.0, 900.0, False)
    assert (type(crowd).__name__, crowd.min_count, crowd.trigger, crowd.reminder_s) == ("CrowdAnalyzer", 7, 30.0, 0.0)


def test_trackless_events_from_different_zones_do_not_collide():
    from vision.node import _merge_event
    partial = {"zone_id": 3, "type": "idle_zone", "severity": "warning",
               "payload": {"track_id": None, "bbox_norm": None, "reminder": 0}}
    first = _merge_event(9, "n", partial, T0)
    second = _merge_event(9, "n", {**partial, "zone_id": 4}, T0)
    assert first["dedup_key"] != second["dedup_key"]
    assert _merge_event(9, "n", {**partial, "payload": {**partial["payload"], "reminder": 1}}, T0)["dedup_key"] != first["dedup_key"]
    tracked = _merge_event(9, "n", {**partial, "type": "intrusion",
                                    "payload": {"track_id": 7, "bbox_norm": [0.1, 0.2, 0.3, 0.4]}}, T0)
    assert tracked["dedup_key"] == f"9:intrusion:7:{int(T0 // 10)}"


def test_missing_behavior_params_use_new_kind_defaults():
    from vision.config import NodeSettings
    from vision.node import VisionNode
    z = zone(id=5, type="behavior", active=True,
             behaviors=[{"kind": "idle_zone"}, {"kind": "crowd", "min_count": 2}])
    node = VisionNode(NodeSettings(face_embed=False), transport=object(), source_factory=lambda c: None)
    idle, crowd = node._make_analyzers(node._cameras_from_config(
        {"cameras": [{"camera_id": 1, "source_url": "test://1", "zones": [z]}]})[0])
    assert (idle.trigger, idle.reminder_s) == (300.0, 900.0)
    assert (crowd.trigger, crowd.reminder_s, crowd.min_count) == (30.0, 900.0, 2)


def test_crowd_recovery_after_long_gap_rearms():
    az = CrowdAnalyzer(zone(min_count=2, trigger_seconds=10, reminder_minutes=0))
    two, one = [T(1, 0.3), T(2, 0.7)], [T(1, 0.3)]
    # low frame terakhir di 4, pulih di 10 (> GRACE_S tanpa frame low berikutnya) → reset di 10
    assert run(az, [(0, two), (2, two), (4, one), (10, two), (12, two),
                    (18, two), (20, two)]) == [(20, "crowd", 0)]
