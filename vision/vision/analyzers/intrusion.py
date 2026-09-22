"""Intrusion analyzer: ray-casting point-in-polygon on track centroids, schedule-gated."""
from __future__ import annotations

from datetime import datetime

from .base import Analyzer


def point_in_polygon(pt: tuple[float, float], poly: list) -> bool:
    """Ray casting, handles concave polygons. poly: [[x, y], ...] normalized."""
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


def _schedule_active(schedule: dict | None, ts: float) -> bool:
    if not schedule:
        return True
    local = datetime.fromtimestamp(ts)
    iso_dow = local.isoweekday()  # Monday=1..Sunday=7
    if iso_dow not in schedule.get("days", []):
        return False
    hhmm = local.strftime("%H:%M")
    return schedule["start"] <= hhmm <= schedule["end"]


class IntrusionAnalyzer(Analyzer):
    """Emits an intrusion event when a track transitions outside->inside a restricted zone."""

    def __init__(self, zone: dict):
        self.zone_id = zone["id"]
        self.zone_name = zone.get("name", "")
        self.severity = zone.get("severity", "warning")
        self.schedule = zone.get("schedule")
        self.polygon = [tuple(p) for p in zone["polygon"]]
        # R5: trigger_seconds = lama di zona sebelum event terbit (0 = saat masuk)
        self.trigger = float(zone.get("trigger_seconds", 0) or 0)
        self._inside: set[int] = set()
        self._first_seen: dict[int, float] = {}
        self._done: set[int] = set()      # kunjungan ini sudah emit

    def on_frame(self, ts: float, tracks: list, frame_w: int, frame_h: int) -> list[dict]:
        if not _schedule_active(self.schedule, ts):
            # off-window: _inside frozen intentionally — a track still inside at
            # window close does not re-emit when the next window opens
            return []
        events = []
        new_inside: set[int] = set()
        present: set[int] = set()
        for tr in tracks:
            present.add(tr.id)
            # centroid already normalized 0-1 (tracker bboxes are normalized xyxy)
            in_poly = point_in_polygon(tr.centroid, self.polygon)
            if in_poly and tr.id not in self._inside:
                self._first_seen[tr.id] = ts
                self._done.discard(tr.id)
            if in_poly:
                new_inside.add(tr.id)
                if tr.id in self._done:
                    continue
                if ts - self._first_seen.get(tr.id, ts) < self.trigger:
                    continue  # belum cukup lama di zona — tahan emit
                self._done.add(tr.id)
                events.append({
                    "zone_id": self.zone_id,
                    "type": "intrusion",
                    "severity": self.severity,
                    "payload": {
                        "zone_name": self.zone_name,
                        "track_id": tr.id,
                        "confidence": None,
                        "bbox_norm": list(tr.bbox),
                    },
                })
        # state = ids currently inside; leaving or losing the track removes the id
        # (so re-entry re-emits)
        self._inside = new_inside
        for tid in [t for t in self._first_seen if t not in present]:
            del self._first_seen[tid]
            self._done.discard(tid)
        return events
