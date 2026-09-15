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

