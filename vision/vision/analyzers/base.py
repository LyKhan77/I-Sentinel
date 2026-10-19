"""Analyzer base and shared zone geometry, schedule, and wall-clock helpers."""
from __future__ import annotations

import time
from datetime import datetime

MONOTONIC_MAX = 1_700_000_000  # Below this threshold timestamps are seconds since boot.


class Analyzer:
    def on_frame(self, ts: float, tracks: list, frame_w: int, frame_h: int) -> list[dict]:
        """Return partial event dicts: {"zone_id", "type", "severity", "payload"}."""
        raise NotImplementedError


def wall_time(ts: float) -> float:
    """Convert live-frame monotonic timestamps to epoch for schedules and labels."""
    return ts + (time.time() - time.monotonic()) if ts < MONOTONIC_MAX else ts


def schedule_active(schedule: dict | None, ts: float) -> bool:
    """ISO weekdays + inclusive HH:MM work window; optional `breaks` silences the
    zone during its `[start, end)` rest windows. `schedule=None` = always active."""
    if not schedule:
        return True
    local = datetime.fromtimestamp(wall_time(ts))
    if local.isoweekday() not in schedule.get("days", []):
        return False
    if not schedule["start"] <= local.strftime("%H:%M") <= schedule["end"]:
        return False
    return not break_active(schedule, ts)


def break_active(schedule: dict | None, ts: float) -> bool:
    """True during a rest window: any `breaks` item with `start <= HH:MM < end` on
    local wall time. Ignores weekdays and the work window; gate-only helpers use it."""
    if not isinstance(schedule, dict):
        return False
    breaks = schedule.get("breaks")
    if not breaks:
        return False
    hhmm = datetime.fromtimestamp(wall_time(ts)).strftime("%H:%M")
    return any(b["start"] <= hhmm < b["end"] for b in breaks)


def point_in_polygon(pt: tuple[float, float], poly: list) -> bool:
    """Ray casting for normalized polygons, including concave polygons."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def ground_point(track) -> tuple[float, float]:
    """Normalized ground point at the bottom center of a track's bbox."""
    x1, _, x2, y2 = track.bbox
    return ((x1 + x2) / 2, y2)


def persons_in_zone(tracks: list, polygon: list) -> list:
    """Return tracks whose ground points lie in the zone polygon."""
    return [t for t in tracks if point_in_polygon(ground_point(t), polygon)]
