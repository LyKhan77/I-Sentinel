"""Shared zone and wall-clock helpers."""
import time
from datetime import datetime

from vision.analyzers import base
from vision.analyzers.base import persons_in_zone, schedule_active, wall_time


class T:
    def __init__(self, tid, bbox):
        self.id = tid
        self.bbox = bbox


def test_wall_time_converts_monotonic_and_keeps_epoch():
    assert abs(wall_time(time.monotonic()) - time.time()) < 1
    epoch = datetime(2026, 9, 28, 10, 0).timestamp()
    assert wall_time(epoch) == epoch


def test_schedule_active_with_monotonic_frame_ts(monkeypatch):
    """Live frames carry monotonic timestamps, not dates in 1970."""
    monday_3am = datetime(2024, 1, 15, 3, 0).timestamp()
    monkeypatch.setattr(base.time, "time", lambda: monday_3am)
    monkeypatch.setattr(base.time, "monotonic", lambda: 5000.0)
    assert schedule_active({"days": [1], "start": "02:00", "end": "04:00"}, 5000.0) is True
    assert schedule_active({"days": [1], "start": "04:00", "end": "05:00"}, 5000.0) is False
    assert schedule_active({"days": [2], "start": "00:00", "end": "23:59"}, 5000.0) is False
    assert schedule_active(None, 5000.0) is True


def test_persons_in_zone_uses_ground_point():
    square = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
    inside = T(1, (0.1, 0.1, 0.2, 0.4))
    feet_out = T(2, (0.1, 0.3, 0.2, 0.7))
    far = T(3, (0.7, 0.7, 0.8, 0.9))
    assert [t.id for t in persons_in_zone([inside, feet_out, far], square)] == [1]
