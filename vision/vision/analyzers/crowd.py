"""Alert when the crowd threshold persists, tolerating short tracking gaps."""
from __future__ import annotations

from .base import Analyzer, persons_in_zone, schedule_active

# > 2x motion-gate force interval (2 s): one missed detection on a still crowd must not reset.
GRACE_S = 5.0


class CrowdAnalyzer(Analyzer):
    """Track sustained person counts within a scheduled zone."""

    def __init__(self, zone: dict):
        self.zone_id = zone["id"]
        self.zone_name = zone.get("name", "")
        self.severity = zone.get("severity", "warning")
        self.schedule = zone.get("schedule")
        self.polygon = [list(p) for p in zone["polygon"]]
        self.min_count = max(1, int(zone.get("min_count", 5) or 5))
        self.trigger = float(zone.get("trigger_seconds", 30) or 0)
        self.reminder_s = float(zone.get("reminder_minutes", 15) or 0) * 60
        self._reset()

    def _reset(self) -> None:
        """Rearm after schedule ends or count stays low beyond the grace period."""
        self._since: float | None = None
        self._below_since: float | None = None
        self._sent = 0

    def on_frame(self, ts: float, tracks: list, frame_w: int, frame_h: int) -> list[dict]:
        """Emit the first threshold event and indexed reminders while crowded."""
        if not schedule_active(self.schedule, ts):
            self._reset()
            return []
        people = persons_in_zone(tracks, self.polygon)
        if len(people) < self.min_count:
            if self._since is not None:
                self._below_since = self._below_since if self._below_since is not None else ts
                if ts - self._below_since > GRACE_S:
                    self._reset()
            return []
        # Recheck on recovery: the next low-count frame may never arrive.
        if self._below_since is not None and ts - self._below_since > GRACE_S:
            self._reset()
        self._below_since = None
        if self._since is None:
            self._since = ts
        if self._sent and not self.reminder_s:
            return []
        duration = ts - self._since
        if duration < self.trigger + self._sent * self.reminder_s:
            return []
        self._sent += 1
        return [{
            "zone_id": self.zone_id, "type": "crowd", "severity": self.severity,
            "payload": {"zone_name": self.zone_name, "track_id": None, "bbox_norm": None,
                        "count": len(people), "min_count": self.min_count,
                        "duration_s": int(duration), "reminder": self._sent - 1,
                        "bboxes": [list(t.bbox) for t in people]},
        }]
