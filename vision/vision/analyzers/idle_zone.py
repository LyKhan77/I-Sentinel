"""Alert on an empty zone after a threshold, then remind while it remains empty."""
from __future__ import annotations

from .base import Analyzer, persons_in_zone, schedule_active


class IdleZoneAnalyzer(Analyzer):
    """Track continuous emptiness inside an active zone schedule."""

    def __init__(self, zone: dict):
        self.zone_id = zone["id"]
        self.zone_name = zone.get("name", "")
        self.severity = zone.get("severity", "warning")
        self.schedule = zone.get("schedule")
        self.polygon = [list(p) for p in zone["polygon"]]
        self.trigger = float(zone.get("trigger_seconds", 300) or 0)
        self.reminder_s = float(zone.get("reminder_minutes", 15) or 0) * 60
        self._empty_since: float | None = None
        self._sent = 0

    def on_frame(self, ts: float, tracks: list, frame_w: int, frame_h: int) -> list[dict]:
        """Emit initial alert and indexed reminders until the zone is occupied."""
        if not schedule_active(self.schedule, ts) or persons_in_zone(tracks, self.polygon):
            self._empty_since, self._sent = None, 0
            return []
        if self._empty_since is None:
            self._empty_since = ts
        if self._sent and not self.reminder_s:
            return []
        idle = ts - self._empty_since
        if idle < self.trigger + self._sent * self.reminder_s:
            return []
        self._sent += 1
        return [{
            "zone_id": self.zone_id, "type": "idle_zone", "severity": self.severity,
            "payload": {"zone_name": self.zone_name, "track_id": None, "bbox_norm": None,
                        "idle_s": int(idle), "reminder": self._sent - 1,
                        "zone_polygon": self.polygon},
        }]
