"""Lightweight ByteTrack-spirit tracker: greedy nearest-centroid matching, EMA velocity.

Pure numpy/math — no cv2, no GPU. Bboxes are xyxy normalized 0-1.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def _centroid(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


@dataclass
class Track:
    id: int
    bbox: tuple[float, float, float, float]
    centroid: tuple[float, float]
    age: int
    velocity: tuple[float, float]
    misses: int = 0


@dataclass
class ByteTracker:
    max_age: int = 15
    min_conf: float = 0.3
    dist_threshold: float = 0.15
    _tracks: list[Track] = field(default_factory=list, init=False, repr=False)
    _next_id: int = field(default=1, init=False, repr=False)
    lost_ids: set[int] = field(default_factory=set, init=False, repr=False)

    def update(self, detections: list, ts: float) -> list[Track]:
        """Match detections to tracks greedily by centroid distance; returns active tracks."""
        self.lost_ids = set()
        dets = [d for d in detections if d.conf >= self.min_conf]
        det_cents = np.array([_centroid(d.bbox) for d in dets], dtype=float).reshape(-1, 2)
        unmatched_dets = set(range(len(dets)))

        # greedy: repeatedly take closest (track, det) pair within threshold
        pairs: list[tuple[int, int, float]] = []
        for ti, tr in enumerate(self._tracks):
            dc = det_cents - _centroid(tr.bbox)
            dists = np.hypot(dc[:, 0], dc[:, 1])
            for di in unmatched_dets:
                if dists[di] <= self.dist_threshold:
                    pairs.append((dists[di], ti, di))
        pairs.sort()
        used_t: set[int] = set()
        for dist, ti, di in pairs:
            if ti in used_t or di not in unmatched_dets:
                continue
            tr = self._tracks[ti]
            new_c = tuple(det_cents[di])
            vel = ((new_c[0] - tr.centroid[0]), (new_c[1] - tr.centroid[1]))
            tr.bbox = dets[di].bbox
            tr.centroid = new_c
            tr.age += 1
            tr.misses = 0
            tr.velocity = vel
            used_t.add(ti)
            unmatched_dets.discard(di)

        # unmatched detections -> new tracks
        n_prior = len(self._tracks)
        for di in sorted(unmatched_dets):
            c = tuple(det_cents[di])
            self._tracks.append(
                Track(id=self._next_id, bbox=dets[di].bbox, centroid=c, age=1, velocity=(0.0, 0.0))
            )
            self._next_id += 1

        # unmatched prior tracks -> misses+1; drop after max_age
        active: list[Track] = []
        for ti, tr in enumerate(self._tracks):
            if ti < n_prior and ti not in used_t:
                tr.misses += 1
                if tr.misses > self.max_age:
                    self.lost_ids.add(tr.id)
                    continue
            active.append(tr)
        self._tracks = active
        return active
