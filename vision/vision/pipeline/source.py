"""Frame source: RTSP/file capture with fps sampling and reconnect backoff."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import numpy as np


log = logging.getLogger(__name__)
RECONNECT_START_S = 1.0


@dataclass
class Frame:
    ts: float
    data: np.ndarray | None  # data may be None (tests track on bboxes only)


class FrameSource:
    """Yields Frame sampled at target_fps.

    Two modes:
    - from_frames(frames, fps): in-memory frames, ts spaced 1/fps, stops at end.
    - FrameSource(url, target_fps): cv2.VideoCapture, wall-clock monotonic ts,
      reconnect with exponential backoff (1s, 2s, 4s... max 30s). A reader thread
      drains the stream at its native fps and keeps only the latest frame: reading
      one frame per 1/target_fps from a faster stream serves an ever-older buffer
      (measured: +0.67 s lag per second at 5 of 15 fps).
    """

    def __init__(self, url: str, target_fps: float = 5.0, open_capture=None):
        self.url = url
        self.target_fps = target_fps
        self._interval = 1.0 / target_fps
        self._cap = None
        self._closed = False
        self._open_capture = open_capture  # None -> cv2.VideoCapture (tes menyuntik palsu)
        self._cond = threading.Condition()
        self._latest = None      # (seq, ts, data) frame terbaru dari reader thread
        self._last_seq = 0       # seq terakhir yang sudah dikembalikan __next__
        self._reader = None
        self._ended = False

    @classmethod
    def from_frames(cls, frames: list, fps: float) -> "FrameSource":
        src = cls("<memory>", fps)
        src._frames = list(frames)
        src._index = 0
        src._t0 = None
        return src

    def _open(self):
        if self._open_capture is not None:
            return self._open_capture(self.url)
        import cv2  # lazy: tests never need cv2

        return cv2.VideoCapture(self.url)

    def start(self) -> None:
        self._cap = self._open()
        if not self._cap.isOpened():
            log.warning("cannot open video source %s, retrying", self.url)
        self._next_due = time.monotonic()
        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name=f"src-{self.url.rsplit('/', 1)[-1]}")
        self._reader.start()

    def _read_loop(self) -> None:
        """Baca secepat stream aslinya; simpan hanya frame terbaru (buang yang basi)."""
        delay = RECONNECT_START_S
        seq = 0
        while not self._closed:
            ok, data = self._cap.read()
            if ok:
                delay = RECONNECT_START_S
                seq += 1
                with self._cond:
                    self._latest = (seq, time.monotonic(), data)
                    self._cond.notify_all()
                continue
            # read failure: reconnect with exponential backoff, max 30s
            if self._closed:
                break
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
            self._reconnect()
        self._cap.release()  # reader pemilik cap: jangan release dari thread lain saat read()
        with self._cond:
            self._ended = True
            self._cond.notify_all()

    def _reconnect(self) -> bool:
        self._cap.release()
        self._cap = self._open()
        return self._cap.isOpened()

    def __iter__(self) -> "FrameSource":
        return self

    def __next__(self) -> Frame:
        frame = self.next_frame()
        assert frame is not None  # unbounded iterator never returns an idle timeout
        return frame

    def next_frame(self, timeout: float | None = None) -> Frame | None:
        """Get latest sampled frame, or None when no frame arrives before timeout."""
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

        # real mode: idle timeout must not terminate source (reconnect may still succeed)
        deadline = None if timeout is None else time.monotonic() + timeout
        if self._reader is None:
            self.start()
        wait = self._next_due - time.monotonic()
        if wait > 0:
            if deadline is not None and wait >= deadline - time.monotonic():
                time.sleep(max(0, deadline - time.monotonic()))
                return None
            time.sleep(wait)
        with self._cond:
            while not (self._closed or self._ended) and (
                    self._latest is None or self._latest[0] == self._last_seq):
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._cond.wait(timeout=remaining)
            if self._closed or self._latest is None or self._latest[0] == self._last_seq:
                raise StopIteration
            seq, ts, data = self._latest
        self._last_seq = seq
        self._next_due = max(self._next_due + self._interval, time.monotonic())
        return Frame(ts=ts, data=data)

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        if self._reader is None and self._cap is not None:
            self._cap.release()  # reader belum jalan; kalau jalan, reader yang release
            self._cap = None
