"""Intrusion analyzer: ray-casting point-in-polygon on track ground points, schedule-gated."""
from __future__ import annotations

from .base import Analyzer, ground_point, point_in_polygon, schedule_active  # noqa: F401 (re-export)


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
        if not schedule_active(self.schedule, ts):
            # off-window: _inside frozen intentionally — a track still inside at
            # window close does not re-emit when the next window opens
            return []
        events = []
        new_inside: set[int] = set()
        present: set[int] = set()
        for tr in tracks:
            present.add(tr.id)
            in_poly = point_in_polygon(ground_point(tr), self.polygon)
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
