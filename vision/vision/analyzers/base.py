"""Analyzer base: turns (ts, tracks) into partial event dicts merged by the node."""
from __future__ import annotations


class Analyzer:
    def on_frame(self, ts: float, tracks: list, frame_w: int, frame_h: int) -> list[dict]:
        """Return partial event dicts: {"zone_id", "type", "severity", "payload"}."""
        raise NotImplementedError
