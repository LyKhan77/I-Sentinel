"""Loitering analyzer: accumulates dwell time for tracks inside a zone polygon."""
from __future__ import annotations

from .base import Analyzer
from .intrusion import point_in_polygon

# Frame-to-frame gaps above this are treated as a tracking gap, not dwell time.
MAX_DELTA_S = 10.0


class LoiteringAnalyzer(Analyzer):
    """Emits one loitering event per stay once dwell inside the zone reaches loiter_seconds."""

    def __init__(self, zone: dict):
        self.zone_id = zone["id"]
        self.zone_name = zone.get("name", "")
        self.severity = zone.get("severity", "warning")
        self.loiter_seconds = zone.get("loiter_seconds", 0)
        self.polygon = [tuple(p) for p in zone["polygon"]]
        self._dwell: dict[int, float] = {}
        self._emitted: set[int] = set()
        self._last_ts: dict[int, float] = {}

    def on_frame(self, ts: float, tracks: list, frame_w: int, frame_h: int) -> list[dict]:
        if self.loiter_seconds <= 0:
            return []
        events = []
        present: set[int] = set()
        for tr in tracks:
            present.add(tr.id)
            if point_in_polygon(tr.centroid, self.polygon):
                delta = 0.0
                last = self._last_ts.get(tr.id)
                if last is not None:
                    d = ts - last
                    if d > MAX_DELTA_S:
                        self._dwell[tr.id] = 0.0  # gap -> restart accumulation
                    elif d > 0:
                        delta = d
                dwell = self._dwell.get(tr.id, 0.0) + delta
                self._dwell[tr.id] = dwell
                if dwell >= self.loiter_seconds and tr.id not in self._emitted:
                    self._emitted.add(tr.id)
                    events.append({
                        "zone_id": self.zone_id,
                        "type": "loitering",
                        "severity": self.severity,
                        "payload": {
                            "zone_name": self.zone_name,
                            "track_id": tr.id,
                            "dwell_s": round(dwell, 1),
                            "confidence": None,
                            "bbox_norm": list(tr.bbox),
                        },
                    })
            else:
                # left polygon: reset so a re-entry builds a fresh stay
                self._dwell.pop(tr.id, None)
                self._emitted.discard(tr.id)
            self._last_ts[tr.id] = ts
        # drop state for tracks no longer reported
        for tid in list(self._last_ts):
            if tid not in present:
                self._last_ts.pop(tid, None)
                self._dwell.pop(tid, None)
                self._emitted.discard(tid)
        return events
