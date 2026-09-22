"""Face gate analyzer: attendance event when a track enters an absensi zone.

Emits one event per visit (state until the track leaves the polygon), with a
10s per-track cooldown so a jittery tracker does not double-emit. When the zone
sets ``dwell_seconds`` > 0 the emit is held until the track has stayed inside
the polygon that long — the person is still in frame when the node crops, so
the attendance crop is not an empty wall/floor. The node crops the upper body
from the frame and uploads it as the attendance best-shot.
"""
from __future__ import annotations

from .base import Analyzer
from .intrusion import point_in_polygon

VALID_DIRECTIONS = {"entry", "exit", "in", "out"}
COOLDOWN_S = 10.0
CROP_PAD = 0.20     # expand bbox by 20% of its size on each side
CROP_UPPER = 0.60   # keep top 60% of the expanded box (head + torso)


def crop_upper_body(frame, bbox_norm) -> "object | None":
    """Return frame[y1:y2, x1:x2] for bbox_norm expanded 20%, top 60% height.

    bbox_norm is normalized xyxy. Returns None when frame is None or the
    resulting slice is empty.
    """
    if frame is None:
        return None
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox_norm
    bw, bh = x2 - x1, y2 - y1
    ex1 = max(0.0, x1 - bw * CROP_PAD)
    ey1 = max(0.0, y1 - bh * CROP_PAD)
    ex2 = min(1.0, x2 + bw * CROP_PAD)
    ey2 = min(1.0, y2 + bh * CROP_PAD)
    upper_y2 = ey1 + (ey2 - ey1) * CROP_UPPER
    px1, py1 = int(ex1 * w), int(ey1 * h)
    px2, py2 = int(ex2 * w), int(upper_y2 * h)
    crop = frame[py1:py2, px1:px2]
    return crop if crop.size else None


class FaceGateAnalyzer(Analyzer):
    """Emits one attendance event per track visit to a face-gate (absensi) zone."""

    def __init__(self, zone: dict):
        self.zone_id = zone["id"]
        self.direction = zone.get("direction")
        self.polygon = [tuple(p) for p in zone["polygon"]]
        self.dwell = float(zone.get("dwell_seconds", 0) or 0)  # 0 = emit langsung
        self._inside: set[int] = set()            # ids currently inside (from prev frame)
        self._last_emit: dict[int, float] = {}    # id -> last emit ts (cooldown)
        self._first_seen: dict[int, float] = {}   # id -> masuk zona pertama kali (visit ini)
        self._done: set[int] = set()              # visit ini sudah emit / tersedot cooldown

    def on_frame(self, ts: float, tracks: list, frame_w: int, frame_h: int) -> list[dict]:
        if self.direction not in VALID_DIRECTIONS:
            return []
        events = []
        present_inside: set[int] = set()
        for tr in tracks:
            if not point_in_polygon(tr.centroid, self.polygon):
                continue
            present_inside.add(tr.id)
            if tr.id not in self._inside:
                self._first_seen[tr.id] = ts
                if ts - self._last_emit.get(tr.id, float("-inf")) < COOLDOWN_S:
                    self._done.add(tr.id)   # kunjungan tersedot cooldown: tidak emit sama sekali
                else:
                    self._done.discard(tr.id)
            if tr.id in self._done:
                continue
            if ts - self._first_seen[tr.id] < self.dwell:
                continue                    # belum cukup lama di zona — tahan emit
            self._done.add(tr.id)
            self._last_emit[tr.id] = ts
            events.append({
                "zone_id": self.zone_id,
                "type": "attendance",
                "severity": "info",
                "payload": {
                    "direction": self.direction,
                    "track_id": tr.id,
                    "bbox_norm": list(tr.bbox),
                    "needs_crop": True,
                },
            })
        # visit is consumed whether or not an emit happened: a cooldown-suppressed
        # re-entry stays inside and will not emit later; only a true outside->inside
        # transition (not cooled down) re-emits.
        self._inside = present_inside
        for tid in [t for t in self._first_seen if t not in present_inside]:
            del self._first_seen[tid]
            self._done.discard(tid)
        keep_after = max(COOLDOWN_S * 6, 60.0)
        for tid in [t for t, last in self._last_emit.items()
                    if t not in present_inside and ts - last > keep_after]:
            del self._last_emit[tid]
        return events
