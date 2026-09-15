"""Frame source: RTSP/file capture with fps sampling and reconnect backoff."""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np


@dataclass
class Frame:
    ts: float
    data: np.ndarray | None  # data may be None (tests track on bboxes only)


class FrameSource:
    """Yields Frame sampled at target_fps.

    Two modes:
    - from_frames(frames, fps): in-memory frames, ts spaced 1/fps, stops at end.
    - FrameSource(url, target_fps): cv2.VideoCapture, wall-clock monotonic ts,
      reconnect with exponential backoff (1s, 2s, 4s... max 30s).
    """

    def __init__(self, url: str, target_fps: float = 5.0):
        self.url = url
        self.target_fps = target_fps
        self._interval = 1.0 / target_fps
        self._cap = None
        self._closed = False

    @classmethod
    def from_frames(cls, frames: list, fps: float) -> "FrameSource":
        src = cls.__new__(cls)
        src.url = "<memory>"
        src.target_fps = fps
        src._interval = 1.0 / fps
        src._cap = None
        src._closed = False
        src._frames = list(frames)
        src._index = 0
        src._t0 = None
        return src

    def start(self) -> None:
        import cv2  # lazy: tests never need cv2

        self._cap = cv2.VideoCapture(self.url)
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open video source: {self.url}")
        self._next_due = time.monotonic()

    def _reconnect(self) -> bool:
        import cv2

        self._cap.release()
        self._cap = cv2.VideoCapture(self.url)
        return self._cap.isOpened()

    def __iter__(self) -> "FrameSource":
        return self

    def __next__(self) -> Frame:
        if self._closed:
            raise StopIteration

        if getattr(self, "_frames", None) is not None:
            if self._index >= len(self._frames):
                raise StopIteration
            data = self._frames[self._index]
            if self._t0 is None:
                self._t0 = time.monotonic()
            ts = self._t0 + self._index * self._interval
            self._index += 1
            return Frame(ts=ts, data=data)

        # real mode
        delay = 1.0
        while True:
            if self._cap is None:
                self.start()
            ok, data = self._cap.read()
            if ok:
                now = time.monotonic()
                wait = self._next_due - now
                if wait > 0:
                    time.sleep(wait)
                self._next_due = max(self._next_due + self._interval, time.monotonic())
                return Frame(ts=time.monotonic(), data=data)
            # read failure: reconnect with exponential backoff, max 30s
            if self._closed or delay > 30.0:
                raise StopIteration
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
            self._reconnect()

    def close(self) -> None:
        self._closed = True
        if self._cap is not None:
            self._cap.release()
            self._cap = None
