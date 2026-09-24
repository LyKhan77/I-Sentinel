"""Per-camera mainstream clip ring: ffmpeg copies the go2rtc RTSP stream into short
MPEG-TS segments on tmpfs; an incident clip is the concat of the segments covering it.

Stdlib only. Segment file name = wall-clock epoch when ffmpeg opened it (strftime %s);
segments always start on a keyframe.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

log = logging.getLogger(__name__)

SEGMENT_S = 2
MAX_SEG_S = 6.0      # longest believable segment (GOP <= 6 s); beyond that = gap
STALL_S = 10.0       # no new segment for this long = ffmpeg stalled
BACKOFF_MAX_S = 30.0

# module-level for test monkeypatching
_popen = subprocess.Popen
_run = subprocess.run
_which = shutil.which


def select(segments: list[tuple[int, str]], t0: float, t1: float) -> list[str]:
    """Paths of sorted (start, path) segments overlapping [t0, t1).

    Segment i spans [start_i, min(start_{i+1}, start_i + MAX_SEG_S)), so a restart gap
    is never counted as covered.
    """
    out = []
    for i, (start, path) in enumerate(segments):
        nxt = segments[i + 1][0] if i + 1 < len(segments) else start + MAX_SEG_S
        end = min(nxt, start + MAX_SEG_S)
        if start < t1 and end > t0:
            out.append(path)
    return out


class ClipRing:
    """ffmpeg segment ring for one camera's mainstream, with a restart watchdog."""

    def __init__(self, camera_id: int, src_url: str, ring_dir: str, *, clock=time.time):
        self.camera_id = camera_id
        self.src_url = src_url
        self.dir = os.path.join(os.path.expanduser(ring_dir), f"cam{camera_id}")
        self._clock = clock
        self._proc = None
        self._started_at = 0.0
        self._backoff = 1.0
        self._next_restart = 0.0
        shutil.rmtree(self.dir, ignore_errors=True)  # leftovers from a crashed run
        self.available = _which("ffmpeg") is not None
        if not self.available:
            log.error("clip ring cam%s: ffmpeg not found, clips fall back to live pull",
                      camera_id)

    def command(self) -> list[str]:
        return ["ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp",
                "-i", self.src_url, "-map", "0:v:0", "-c", "copy", "-an",
                "-f", "segment", "-segment_time", str(SEGMENT_S),
                "-segment_format", "mpegts", "-strftime", "1",
                os.path.join(self.dir, "%s.ts")]

    def start(self) -> None:
        if not self.available:
            return
        try:
            os.makedirs(self.dir, exist_ok=True)
            self._proc = _popen(self.command(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log.warning("clip ring cam%s: ffmpeg start failed: %s", self.camera_id, e)
            self._proc = None
            return
        self._started_at = self._clock()

    def segments(self) -> list[tuple[int, str]]:
        try:
            names = os.listdir(self.dir)
        except OSError:
            return []
        out = []
        for name in names:
            stem, ext = os.path.splitext(name)
            if ext == ".ts" and stem.isdigit():
                out.append((int(stem), os.path.join(self.dir, name)))
        return sorted(out)

    def healthy(self) -> bool:
        if self._proc is None or self._proc.poll() is not None:
            return False
        segs = self.segments()
        progress = max(segs[-1][0] if segs else 0, self._started_at)
        return self._clock() - progress <= STALL_S

    def check(self) -> None:
        """Watchdog step: restart a dead or stalled ffmpeg with exponential backoff."""
        if not self.available:
            return
        if self.healthy():
            segs = self.segments()
            if segs and segs[-1][0] >= int(self._started_at):
                self._backoff = 1.0  # produced output since the last (re)start
            return
        now = self._clock()
        if now < self._next_restart:
            return
        log.warning("clip ring cam%s: ffmpeg dead or stalled, restarting (backoff %.0fs)",
                    self.camera_id, self._backoff)
        self.stop()
        self.start()
        self._next_restart = now + self._backoff
        self._backoff = min(self._backoff * 2, BACKOFF_MAX_S)

    def prune(self, keep_from: float) -> None:
        """Delete segments older than the one covering keep_from."""
        segs = self.segments()
        keep_idx = max((i for i, (s, _) in enumerate(segs) if s <= keep_from), default=0)
        for _, path in segs[:keep_idx]:
            try:
                os.remove(path)
            except OSError:
                pass

    def cut(self, t0: float, t1: float, out_path: str, *, must_cover: float,
            include_open: bool = False) -> str | None:
        """Concat segments covering [t0, t1] into out_path (mp4, faststart).

        None when no segment covers must_cover (the event moment) or ffmpeg fails.
        The newest segment is still being written unless include_open (ffmpeg stopped).
        """
        segs = self.segments()
        paths = select(segs, t0, t1)
        if not include_open and segs and paths and paths[-1] == segs[-1][1]:
            paths.pop()
        hit = select(segs, must_cover, must_cover + 0.001)
        if not paths or not hit or hit[0] not in paths:
            log.warning("clip ring cam%s: no segment covers %.1f", self.camera_id, must_cover)
            return None
        cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
               "-i", "concat:" + "|".join(paths),
               "-c", "copy", "-movflags", "+faststart", out_path]
        try:
            r = _run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("clip ring cam%s: concat failed: %s", self.camera_id, e)
            return None
        if r.returncode != 0 or not os.path.exists(out_path):
            log.warning("clip ring cam%s: concat rc=%s %s", self.camera_id, r.returncode,
                        (r.stderr or b"")[-300:])
            return None
        return out_path

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                log.warning("clip ring cam%s: ffmpeg did not die", self.camera_id)

    def close(self) -> None:
        self.stop()
        shutil.rmtree(self.dir, ignore_errors=True)
