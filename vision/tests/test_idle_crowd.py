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
