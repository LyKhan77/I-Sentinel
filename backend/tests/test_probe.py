from unittest.mock import patch
from app.services.probe import build_rtsp_candidates, probe_url, probe_camera

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
