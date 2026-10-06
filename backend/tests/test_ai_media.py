"""Synthetic media only; no local footage or credentials."""
from io import BytesIO
import shutil
import subprocess

from PIL import Image
import pytest


def test_keyframe_times():
    from app.services import ai_media as m
    assert m.keyframe_times(20) == pytest.approx([0, 20/6, 40/6, 10, 80/6, 100/6])
    assert len(m.keyframe_times(30)) == 6
    assert len(m.keyframe_times(30.1)) == 12
    assert m.keyframe_times(46)[1] == pytest.approx(46/12)
    for invalid in (0, -1, float("nan"), float("inf")):
        with pytest.raises(m.AiMediaError):
            m.keyframe_times(invalid)


def test_snapshot_jpeg_downscales(tmp_path, monkeypatch):
    from app.services import ai_media as m
    monkeypatch.setattr(m.settings, "storage_root", str(tmp_path))
    Image.new("RGB", (1920, 1080)).save(tmp_path / "test.jpg")
    assert Image.open(BytesIO(m.snapshot_jpeg("test.jpg"))).size == (960, 540)
    Image.new("RGB", (540, 1920)).save(tmp_path / "portrait.png")
    assert max(Image.open(BytesIO(m.snapshot_jpeg("portrait.png"))).size) == 960
    for rel in ("missing.jpg", "../etc/passwd", "/etc/passwd"):
        with pytest.raises(m.AiMediaError):
            m.snapshot_jpeg(rel)
    outside = tmp_path.parent / "outside.jpg"
    Image.new("RGB", (10, 10)).save(outside)
    (tmp_path / "link.jpg").symlink_to(outside)
    with pytest.raises(m.AiMediaError):
        m.snapshot_jpeg("link.jpg")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_ffmpeg_duration_and_frames(tmp_path, monkeypatch):
    from app.services import ai_media as m
    monkeypatch.setattr(m.settings, "storage_root", str(tmp_path))
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=5", "-t", "3", "-pix_fmt", "yuv420p",
                    str(tmp_path / "synthetic.mp4")], check=True, capture_output=True)
    assert m.clip_duration("synthetic.mp4") == pytest.approx(3, abs=0.2)
    frames = m.extract_keyframes("synthetic.mp4", [0.0, 1.5])
    assert [t for t, _ in frames] == [0.0, 1.5]
    assert all(jpeg.startswith(b"\xff\xd8") and max(Image.open(BytesIO(jpeg)).size) <= 960 for _, jpeg in frames)


def test_subprocess_timeout(tmp_path, monkeypatch):
    from app.services import ai_media as m
    monkeypatch.setattr(m.settings, "storage_root", str(tmp_path))
    (tmp_path / "clip.mp4").write_bytes(b"synthetic")
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] > 0 and not kwargs.get("shell", False)
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(m.subprocess, "run", timeout)
    with pytest.raises(m.AiMediaError):
        m.extract_keyframes("clip.mp4", [0, 1])
    with pytest.raises(m.AiMediaError):
        m.clip_duration("clip.mp4")
