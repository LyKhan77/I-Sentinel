import os

import pytest

import vision.clipring as cr
from vision.clipring import ClipRing, select


class FakeProc:
    def __init__(self, cmd, **kw):
        self.cmd = cmd
        self.rc = None
        self.terminated = False

    def poll(self):
        return self.rc

    def terminate(self):
        self.terminated = True
        self.rc = -15

    def wait(self, timeout=None):
        return self.rc

    def kill(self):
        self.rc = -9


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def procs(monkeypatch):
    made = []

    def popen(cmd, **kw):
        p = FakeProc(cmd, **kw)
        made.append(p)
        return p

    monkeypatch.setattr(cr, "_popen", popen)
    monkeypatch.setattr(cr, "_which", lambda name: "/usr/bin/ffmpeg")
    return made


def touch_segments(ring, starts):
    os.makedirs(ring.dir, exist_ok=True)
    for s in starts:
        with open(os.path.join(ring.dir, f"{s}.ts"), "wb") as f:
            f.write(b"ts")


SEGS = [(100, "a"), (102, "b"), (104, "c"), (106, "d")]


def test_select_covers_window():
    assert select(SEGS, 101, 105) == ["a", "b", "c"]
    assert select(SEGS, 100, 104) == ["a", "b"]  # t1 on a segment start excludes it
    assert select(SEGS, 106.5, 107) == ["d"]


def test_select_gap_not_covered():
    segs = [(100, "a"), (102, "b"), (130, "c")]
    assert select(segs, 115, 116) == []  # b ends at min(130, 102 + 6)


def test_segments_parses_and_sorts(tmp_path, procs):
    ring = ClipRing(1, "rtsp://h:8554/cam_1_main", str(tmp_path))
    touch_segments(ring, [104, 100])
    open(os.path.join(ring.dir, "junk.txt"), "w").close()
    open(os.path.join(ring.dir, "x.ts"), "w").close()
    assert [s for s, _ in ring.segments()] == [100, 104]


def test_command_copies_mainstream_into_segments(tmp_path, procs):
    ring = ClipRing(1, "rtsp://h:8554/cam_1_main", str(tmp_path))
    cmd = ring.command()
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-i") + 1] == "rtsp://h:8554/cam_1_main"
    assert cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[cmd.index("-f") + 1] == "segment"
    assert cmd[cmd.index("-segment_time") + 1] == "2"
    assert cmd[-1] == os.path.join(str(tmp_path), "cam1", "%s.ts")


def test_cut_concats_selected_segments(tmp_path, procs, monkeypatch):
    ring = ClipRing(1, "src", str(tmp_path))
    touch_segments(ring, [100, 102, 104, 106, 108])
    runs = []

    def run(cmd, **kw):
        runs.append(cmd)
        open(cmd[-1], "wb").close()
        return type("R", (), {"returncode": 0, "stderr": b""})()

    monkeypatch.setattr(cr, "_run", run)
    out = str(tmp_path / "o.mp4")
    assert ring.cut(101, 105, out, must_cover=103) == out
    src = runs[0][runs[0].index("-i") + 1]
    assert src == "concat:" + "|".join(os.path.join(ring.dir, f"{s}.ts") for s in (100, 102, 104))
    assert runs[0][runs[0].index("-c") + 1] == "copy"
    # the newest file is still being written: dropped unless include_open
    ring.cut(105, 111, out, must_cover=107)
    assert runs[1][runs[1].index("-i") + 1].endswith("104.ts|" + os.path.join(ring.dir, "106.ts"))
    ring.cut(105, 111, out, must_cover=107, include_open=True)
    assert runs[2][runs[2].index("-i") + 1].endswith("108.ts")


def test_cut_returns_none_when_event_not_covered(tmp_path, procs, monkeypatch):
    ring = ClipRing(1, "src", str(tmp_path))
    touch_segments(ring, [100, 102])
    runs = []
    monkeypatch.setattr(cr, "_run", lambda cmd, **kw: runs.append(cmd))
    assert ring.cut(120, 130, str(tmp_path / "o.mp4"), must_cover=125) is None
    assert runs == []


def test_cut_returns_none_on_ffmpeg_error(tmp_path, procs, monkeypatch):
    ring = ClipRing(1, "src", str(tmp_path))
    touch_segments(ring, [100, 102, 104])
    monkeypatch.setattr(cr, "_run", lambda cmd, **kw: type("R", (), {"returncode": 1, "stderr": b"boom"})())
    assert ring.cut(100, 103, str(tmp_path / "o.mp4"), must_cover=101) is None


def test_prune_keeps_segment_covering_keep_from(tmp_path, procs):
    ring = ClipRing(1, "src", str(tmp_path))
    touch_segments(ring, [100, 102, 104, 106, 108, 110])
    ring.prune(105)
    assert [s for s, _ in ring.segments()] == [104, 106, 108, 110]


def test_check_restarts_dead_process_with_backoff(tmp_path, procs):
    clock = Clock(1000.0)
    ring = ClipRing(1, "src", str(tmp_path), clock=clock)
    ring.start()
    assert len(procs) == 1
    procs[-1].rc = 1              # ffmpeg died
    ring.check()
    assert len(procs) == 2 and procs[0].terminated is False  # dead proc is not re-terminated
    procs[-1].rc = 1
    clock.t = 1000.5
    ring.check()
    assert len(procs) == 2        # backoff 1 s not elapsed
    clock.t = 1001.0
    ring.check()
    assert len(procs) == 3        # next backoff is 2 s
    procs[-1].rc = 1
    clock.t = 1002.9
    ring.check()
    assert len(procs) == 3
    clock.t = 1003.0
    ring.check()
    assert len(procs) == 4


def test_check_restarts_stalled_ffmpeg(tmp_path, procs):
    clock = Clock(1000.0)
    ring = ClipRing(1, "src", str(tmp_path), clock=clock)
    ring.start()
    clock.t = 1009.0
    ring.check()
    assert len(procs) == 1 and ring.healthy()
    clock.t = 1011.0              # no segment for > 10 s
    assert not ring.healthy()
    ring.check()
    assert len(procs) == 2 and procs[0].terminated


def test_unavailable_without_ffmpeg(tmp_path, monkeypatch):
    made = []
    monkeypatch.setattr(cr, "_which", lambda name: None)
    monkeypatch.setattr(cr, "_popen", lambda cmd, **kw: made.append(cmd))
    ring = ClipRing(1, "src", str(tmp_path))
    ring.start()
    ring.check()
    assert ring.available is False and not ring.healthy() and made == []


def test_close_stops_process_and_removes_dir(tmp_path, procs):
    ring = ClipRing(1, "src", str(tmp_path))
    ring.start()
    touch_segments(ring, [100])
    ring.close()
    assert procs[0].terminated and not os.path.exists(ring.dir)
