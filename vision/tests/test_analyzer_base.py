"""Shared zone and wall-clock helpers."""
import time
from datetime import datetime

from vision.analyzers import base
from vision.analyzers.base import break_active, persons_in_zone, schedule_active, wall_time


class T:
    def __init__(self, tid, bbox):
        self.id = tid
        self.bbox = bbox


# Jadwal dengan istirahat: jendela kerja 08:00-17:00, istirahat [12:00, 13:00) pada Senin.
WORK = {"days": [1], "start": "08:00", "end": "17:00", "breaks": [{"start": "12:00", "end": "13:00"}]}


def _ts(hour, minute=0):
    return datetime(2024, 1, 15, hour, minute).timestamp()  # Senin 2024-01-15


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


def test_schedule_active_break_boundaries():
    """Jendela istirahat setengah terbuka [start, end): 11:59 aktif, 12:00-12:59 diam, 13:00 aktif."""
    assert schedule_active(WORK, _ts(11, 59)) is True
    assert schedule_active(WORK, _ts(12, 0)) is False
    assert schedule_active(WORK, _ts(12, 59)) is False
    assert schedule_active(WORK, _ts(13, 0)) is True


def test_schedule_active_two_breaks_and_empty():
    work = {**WORK, "breaks": [{"start": "12:00", "end": "13:00"}, {"start": "15:00", "end": "15:15"}]}
    assert schedule_active(work, _ts(15, 10)) is False
    assert schedule_active(work, _ts(14, 0)) is True
    assert schedule_active({**WORK, "breaks": []}, _ts(12, 30)) is True
    assert schedule_active({"days": [1], "start": "08:00", "end": "17:00"}, _ts(12, 30)) is True  # tanpa kunci breaks: perilaku lama


def test_break_active_ignores_days_and_work_window():
    """break_active murni istirahat: mengabaikan hari dan jendela kerja; None = False."""
    sched = {"days": [2], "start": "08:00", "end": "09:00", "breaks": [{"start": "12:00", "end": "13:00"}]}
    assert break_active(sched, _ts(12, 30)) is True
    assert break_active(None, _ts(12, 30)) is False


def test_persons_in_zone_uses_ground_point():
    square = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
    inside = T(1, (0.1, 0.1, 0.2, 0.4))
    feet_out = T(2, (0.1, 0.3, 0.2, 0.7))
    far = T(3, (0.7, 0.7, 0.8, 0.9))
    assert [t.id for t in persons_in_zone([inside, feet_out, far], square)] == [1]
