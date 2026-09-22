"""Motion gate: inferensi YOLO hanya dijalankan ketika frame bergerak.

Pola ini diambil dari Frigate (`ImprovedMotionDetector` + periodic re-detect):
koridor yang kosong tidak perlu inferensi 5x/detik. Dua knob:

- ``threshold``: selisih intensitas piksel (0-255) yang dianggap "berubah".
- ``min_area``: luas minimum blob gerak terbesar sebagai rasio frame; dipakai
  supaya noise kecil (hujan, kompresi) tidak memicu inferensi.

Objek yang diam tetap terdeteksi karena ``force_interval_s`` memaksa satu
inferensi berkala — sekaligus menjaga id ByteTrack tidak hilang (jarak frame
di bawah `max_age` tracker).
"""
from __future__ import annotations

DOWN_W, DOWN_H = 64, 36


class FrameMotionGate:
    def __init__(self, threshold: float = 25.0, min_area: float = 0.01,
                 force_interval_s: float = 2.0):
        self.threshold = float(threshold)
        self.min_area = float(min_area)
        self.force_interval_s = float(force_interval_s)
        self._prev = None
        self._last_detect_ts: float | None = None

    def update(self, frame, ts: float) -> bool:
        """True = boleh inferensi (ada gerak ATAU interval paksa lewat)."""
        if frame is None:
            return True
        import cv2
        import numpy as np

        small = cv2.resize(frame, (DOWN_W, DOWN_H), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
        prev, self._prev = self._prev, gray

        motion = 0.0
        if prev is not None:
            diff = cv2.absdiff(gray, prev)
            _, mask = cv2.threshold(diff, self.threshold, 255, cv2.THRESH_BINARY)
            num, _, stats, _ = cv2.connectedComponentsWithStats(mask)
            largest = max((int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, num)), default=0)
            motion = largest / float(mask.size)

        forced = (self._last_detect_ts is None
                  or (ts - self._last_detect_ts) >= self.force_interval_s)
        if motion >= self.min_area or forced:
            self._last_detect_ts = ts
            return True
        return False
