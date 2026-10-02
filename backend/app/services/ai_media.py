"""Read confined snapshots and bounded keyframes without shell commands or footage logs."""
from io import BytesIO
import math
from pathlib import Path
import subprocess
import time

from PIL import Image

from app.core.config import settings

MAX_PX = 960


class AiMediaError(Exception):
    """Missing, invalid, escaped, or undecodable event media."""


def media_path(rel: str) -> Path:
    """Resolve only relative paths confined to storage_root, including symlink targets."""
    root = Path(settings.storage_root).resolve()
    path = Path(rel)
    if path.is_absolute():
        raise AiMediaError("Path media tidak valid")
    full = (root / path).resolve()
    if not full.is_relative_to(root) or full == root:
        raise AiMediaError("Path media tidak valid")
    return full


def snapshot_jpeg(rel: str) -> bytes:
    """Convert a snapshot to RGB JPEG q80 with longest side at most 960 pixels."""
    try:
        with Image.open(media_path(rel)) as image:
            image = image.convert("RGB")
            image.thumbnail((MAX_PX, MAX_PX))
            buf = BytesIO()
            image.save(buf, format="JPEG", quality=80)
            return buf.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise AiMediaError("Snapshot tidak tersedia") from None


def keyframe_times(duration_s: float) -> list[float]:
    """Sample six frames through 30 seconds, otherwise twelve, excluding the endpoint."""
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise AiMediaError("Durasi klip tidak valid")
    n = 6 if duration_s <= 30 else 12
    return [i * duration_s / n for i in range(n)]


def clip_duration(rel: str, *, timeout_s: float = 10.0) -> float:
    """Probe a local clip duration with a finite subprocess deadline."""
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                                 str(media_path(rel))], check=True, capture_output=True, timeout=timeout_s)
        duration = float(result.stdout)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("duration")
        return duration
    except (OSError, ValueError, subprocess.SubprocessError):
        raise AiMediaError("Klip tidak dapat dibaca") from None


def extract_keyframes(rel: str, times: list[float], *, timeout_s: float = 15.0) -> list[tuple[float, bytes]]:
    """Extract ordered JPEGs under one total deadline; any failure discards all frames.

    The scale expression preserves aspect ratio and bounds portrait media too.
    """
    path = media_path(rel)
    deadline = time.monotonic() + timeout_s
    frames = []
    try:
        for at in times:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not math.isfinite(at) or at < 0:
                raise ValueError("deadline or sample")
            result = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", "-vf",
                                     "scale=960:960:force_original_aspect_ratio=decrease:force_divisible_by=2", "-q:v", "4",
                                     "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
                                    check=True, capture_output=True, timeout=remaining)
            if not result.stdout.startswith(b"\xff\xd8"):
                raise ValueError("empty frame")
            frames.append((at, result.stdout))
        return frames
    except (OSError, ValueError, subprocess.SubprocessError):
        raise AiMediaError("Keyframe klip tidak tersedia") from None
