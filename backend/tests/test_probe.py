import base64
import subprocess
from unittest.mock import patch

from app.services.probe import (
    build_rtsp_candidates,
    probe_camera,
    probe_exact,
    probe_url,
    snapshot_jpeg_b64,
)
from app.services.stream_endpoint import EffectiveStream

def test_candidates_hikvision():
    c = build_rtsp_candidates("192.168.1.108")
    assert c["main"][0].endswith("192.168.1.108/Streaming/Channels/101")
    assert c["sub"][0].endswith("/Streaming/Channels/102")
    assert any("realmonitor" in u for u in c["main"])  # dahua juga masuk daftar

FFPROBE_JSON = '{"streams":[{"width":2560,"height":1440,"r_frame_rate":"25/1","codec_name":"h264"}]}'

def test_probe_url_parses():
    with patch("app.services.probe.subprocess.run") as m:
        m.return_value.returncode = 0
        m.return_value.stdout = FFPROBE_JSON
        r = probe_url("rtsp://x")
    assert r == {"res": "2560x1440", "fps": 25.0, "codec": "h264"}

def test_probe_url_fail_returns_none():
    with patch("app.services.probe.subprocess.run") as m:
        m.return_value.returncode = 1
        m.return_value.stdout = ""
        assert probe_url("rtsp://x") is None

def test_probe_camera_stops_at_first_hit():
    with patch("app.services.probe.probe_url") as p:
        p.side_effect = [None, {"res": "2560x1440", "fps": 25.0, "codec": "h264"},
                         {"res": "640x360", "fps": 15.0, "codec": "h264"}]
        r = probe_camera("1.2.3.4")
    assert r["main"]["res"] == "2560x1440" and r["sub"]["res"] == "640x360"

def test_probe_camera_paths_credential_free():
    with patch("app.services.probe.probe_url") as p:
        p.side_effect = [{"res": "2560x1440", "fps": 25.0, "codec": "h264"}] * 10
        r = probe_camera("1.2.3.4")
    assert r["main_path"] == "/Streaming/Channels/101"
    assert r["sub_path"] == "/Streaming/Channels/102"
    for path in (r["main_path"], r["sub_path"]):
        assert "@" not in path and "://" not in path


def test_probe_camera_path_dahua_keeps_query():
    with patch("app.services.probe.build_rtsp_candidates") as bc, patch("app.services.probe.probe_url") as p:
        cands = build_rtsp_candidates("1.2.3.4")
        cands["main"] = ["rtsp://admin:secret@1.2.3.4/cam/realmonitor?channel=1&subtype=0"]
        cands["sub"] = cands["main"]
        bc.return_value = cands
        p.return_value = {"res": "1x1", "fps": 1.0, "codec": "h264"}
        r = probe_camera("1.2.3.4")
    assert r["main_path"] == "/cam/realmonitor?channel=1&subtype=0"


OK = {"res": "640x480", "fps": 25.0, "codec": "h264"}


def test_snapshot_returns_base64_jpeg():
    with patch("app.services.probe.subprocess.run") as m:
        m.return_value.returncode = 0
        m.return_value.stdout = b"\xff\xd8jpeg"
        assert snapshot_jpeg_b64("rtsp://x") == base64.b64encode(b"\xff\xd8jpeg").decode()
    cmd = m.call_args[0][0]
    assert cmd[0] == "ffmpeg" and cmd[cmd.index("-frames:v") + 1] == "1"


def test_snapshot_failure_returns_none():
    with patch("app.services.probe.subprocess.run") as m:
        m.return_value.returncode = 1
        m.return_value.stdout = b""
        assert snapshot_jpeg_b64("rtsp://x") is None
    with patch("app.services.probe.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 6)):
        assert snapshot_jpeg_b64("rtsp://x") is None


def test_probe_exact_snapshot_uses_sub_then_main():
    stream = EffectiveStream(host="10.0.0.5", port=554, username="u", password="p",
                             main_path="/main", sub_path="/sub")
    with patch("app.services.probe.probe_url", return_value=OK), \
         patch("app.services.probe.snapshot_jpeg_b64", return_value="QUJD") as snap:
        r = probe_exact(stream, snapshot=True)
    assert r["snapshot_jpeg_b64"] == "QUJD"
    assert snap.call_args[0][0] == "rtsp://u:p@10.0.0.5/sub"

    main_only = EffectiveStream(host="10.0.0.5", port=554, username=None, password=None,
                                main_path="/main", sub_path=None)
    with patch("app.services.probe.probe_url", return_value=OK), \
         patch("app.services.probe.snapshot_jpeg_b64", return_value="QUJD") as snap:
        probe_exact(main_only, snapshot=True)
    assert snap.call_args[0][0] == "rtsp://10.0.0.5/main"


def test_probe_exact_without_snapshot_or_unreadable_stream():
    stream = EffectiveStream(host="10.0.0.5", port=554, username=None, password=None,
                             main_path="/main", sub_path="/sub")
    with patch("app.services.probe.probe_url", return_value=OK):
        assert "snapshot_jpeg_b64" not in probe_exact(stream)
    with patch("app.services.probe.probe_url", return_value=None), \
         patch("app.services.probe.snapshot_jpeg_b64") as snap:
        assert probe_exact(stream, snapshot=True)["snapshot_jpeg_b64"] is None
    snap.assert_not_called()
