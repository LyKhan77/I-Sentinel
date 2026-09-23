import time

import numpy as np
import pytest

from vision.pipeline.source import FrameSource


def frames(n: int) -> list[np.ndarray]:
    return [np.zeros((4, 4, 3), dtype=np.uint8) for _ in range(n)]


def test_from_frames_yields_all_with_ts_spacing():
    src = FrameSource.from_frames(frames(5), fps=2.0)
    out = list(src)
    assert len(out) == 5
    for i in range(1, 5):
        assert out[i].ts - out[i - 1].ts == pytest.approx(0.5)
    src.close()


def test_from_frames_stops_at_end():
    src = FrameSource.from_frames(frames(3), fps=5.0)
    consumed = sum(1 for _ in src)
    assert consumed == 3


def test_target_fps_sampling_from_timestamps():
    # ts spacing = 1/target_fps for a source built at that fps
    src5 = FrameSource.from_frames(frames(10), fps=5.0)
    out = list(src5)
    dts = [out[i].ts - out[i - 1].ts for i in range(1, 10)]
    for dt in dts:
        assert dt == pytest.approx(0.2)
    assert len(out) == 10



class BufferedLiveCapture:
    """Kamera palsu 100 fps yang berperilaku seperti RTSP ber-buffer: read() mengembalikan
    frame berikutnya di antrean (bisa sudah basi), data = nomor frame."""

    FPS = 100.0

    def __init__(self, url):
        self.t0 = time.monotonic()
        self.n = 0

    def isOpened(self):
        return True

    def read(self):
        self.n += 1
        wait = self.t0 + self.n / self.FPS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        return True, np.array([self.n])

    def live_index(self):
        return (time.monotonic() - self.t0) * self.FPS

    def release(self):
        pass


def test_live_source_returns_latest_frame_not_stale_buffer():
    """Terbukti di server: baca 5 fps dari stream 15 fps -> lag +0,67 s tiap detik."""
    caps = []
    src = FrameSource("fake://cam", target_fps=10.0,
                      open_capture=lambda url: caps.append(BufferedLiveCapture(url)) or caps[-1])
    lags = []
    for _ in range(5):
        frame = next(src)
        lags.append(caps[0].live_index() - int(frame.data[0]))
    src.close()
    # antrean basi: frame ke-5 = frame #5 saat live ~#50 (lag ~45 frame = 450 ms dan terus naik)
    assert max(lags[1:]) <= 10, lags


class OpensOnSecondTry:
    """go2rtc stream becomes available after worker starts."""

    attempts = 0

    def __init__(self, url):
        OpensOnSecondTry.attempts += 1
        self.ok = OpensOnSecondTry.attempts >= 2
        self.n = 0

    def isOpened(self):
        return self.ok

    def read(self):
        if not self.ok:
            return False, None
        time.sleep(0.01)
        self.n += 1
        return True, np.array([self.n])

    def release(self):
        pass


def test_source_unavailable_at_start_retries_instead_of_raising(monkeypatch):
    import vision.pipeline.source as source_mod

    monkeypatch.setattr(source_mod, "RECONNECT_START_S", 0.01, raising=False)
    OpensOnSecondTry.attempts = 0
    src = FrameSource("fake://cam", target_fps=10.0, open_capture=OpensOnSecondTry)
    try:
        frame = next(src)
        assert int(frame.data[0]) >= 1
        assert OpensOnSecondTry.attempts >= 2
    finally:
        src.close()


def test_closed_live_source_stops_iteration():
    src = FrameSource("fake://cam", target_fps=10.0, open_capture=BufferedLiveCapture)
    next(src)
    src.close()
    with pytest.raises(StopIteration):
        next(src)
