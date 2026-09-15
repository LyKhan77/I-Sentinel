"""Running analyzer: calibrated per-track speed (m/s) inside a zone polygon.

Speed from analyzer-frame centroid deltas. `meters_per_pixel` is measured on the
raw frame pixels, so each normalized axis must first go back to pixels through
its own frame dimension (x by frame_w, y by frame_h) before applying
meters_per_pixel: meters = hypot(Δx_norm*frame_w, Δy_norm*frame_h) * mpp.
"""
from __future__ import annotations

import math

from .base import Analyzer
from .intrusion import point_in_polygon

EMA_ALPHA = 0.4
COOLDOWN_S = 5.0


class RunningAnalyzer(Analyzer):
    """Emits one running event per track per cooldown while inside the zone."""

    def __init__(self, zone: dict, meters_per_pixel: float):
        self.zone_id = zone["id"]
        self.zone_name = zone.get("name", "")
        self.severity = zone.get("severity", "warning")
        self.speed_limit_mps = zone.get("speed_limit_mps", 0)
        self.polygon = [tuple(p) for p in zone["polygon"]]
        self.mpp = meters_per_pixel
        self._last: dict[int, tuple[float, tuple[float, float]]] = {}
        self._speed: dict[int, float] = {}
        self._last_emit: dict[int, float] = {}

    def on_frame(self, ts: float, tracks: list, frame_w: int, frame_h: int) -> list[dict]:
        if self.speed_limit_mps <= 0:
            return []
        events = []
        present: set[int] = set()
        for tr in tracks:
            present.add(tr.id)
            prev = self._last.get(tr.id)
            self._last[tr.id] = (ts, tr.centroid)
            if prev is None:
                continue  # first sighting: no delta yet
            dt = ts - prev[0]
            if dt <= 0:
                continue
            dx = (tr.centroid[0] - prev[1][0]) * frame_w
            dy = (tr.centroid[1] - prev[1][1]) * frame_h
            meters = math.hypot(dx, dy) * self.mpp
            new_s = meters / dt
            prev_s = self._speed.get(tr.id)
            s = new_s if prev_s is None else (1 - EMA_ALPHA) * prev_s + EMA_ALPHA * new_s
            self._speed[tr.id] = s
            if s <= self.speed_limit_mps:
                continue
            if not point_in_polygon(tr.centroid, self.polygon):
                continue
            last_emit = self._last_emit.get(tr.id)
            if last_emit is not None and ts - last_emit < COOLDOWN_S:
                continue
            self._last_emit[tr.id] = ts
            events.append({
                "zone_id": self.zone_id,
                "type": "running",
                "severity": self.severity,
                "payload": {
                    "zone_name": self.zone_name,
                    "track_id": tr.id,
                    "speed_mps": round(s, 2),
                    "confidence": None,
                    "bbox_norm": list(tr.bbox),
                },
            })
        # drop state for tracks no longer reported
        for tid in [t for t in self._last if t not in present]:
            self._last.pop(tid, None)
            self._speed.pop(tid, None)
            self._last_emit.pop(tid, None)
        return events
