import os
import subprocess
from urllib.parse import quote


def _creds(user, password):
    u = user or os.environ.get("CAM_USERNAME", "admin")
    p = password or os.environ.get("CAM_PASSWORD", "")
    return quote(u, safe=""), quote(p, safe="")


def build_rtsp_candidates(host, user=None, password=None):
    """Ordered RTSP candidates: Hikvision, Dahua, generic."""
    u, p = _creds(user, password)
    auth = f"{u}:{p}@" if p else (f"{u}@" if u else "")
    base = f"rtsp://{auth}{host}"

    def paths(ch_main, ch_sub):
        return {
            "main": [f"{base}/Streaming/Channels/{ch_main}", f"{base}/cam/realmonitor?channel=1&subtype=0", f"{base}/stream1", f"{base}/live/ch00_0", f"{base}/"],
            "sub": [f"{base}/Streaming/Channels/{ch_sub}", f"{base}/cam/realmonitor?channel=1&subtype=1", f"{base}/stream1", f"{base}/live/ch00_0", f"{base}/"],
        }

    return paths(101, 102)


def probe_url(url, timeout=6.0):
    """ffprobe one RTSP URL; {"res","fps","codec"} or None."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate,codec_name",
             "-of", "json", url],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    import json
    try:
        s = json.loads(r.stdout)["streams"][0]
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    try:
        num, den = s["r_frame_rate"].split("/")
        fps = round(float(num) / float(den), 2)
    except (KeyError, ValueError, ZeroDivisionError):
        return None
    return {"res": f"{s['width']}x{s['height']}", "fps": fps, "codec": s["codec_name"]}


def probe_camera(host):
    """Try main candidates then sub candidates until first hit each."""
    cands = build_rtsp_candidates(host)
    main = sub = None
    main_path = sub_path = None
    for url in cands["main"]:
        main = probe_url(url)
        if main:
            main_path = url
            break
    for url in cands["sub"]:
        sub = probe_url(url)
        if sub:
            sub_path = url
            break
    return {"main": main, "sub": sub, "main_path": main_path, "sub_path": sub_path}
