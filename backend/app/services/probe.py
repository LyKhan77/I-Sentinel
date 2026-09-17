import os
import subprocess
from urllib.parse import quote

from app.services.stream_endpoint import EffectiveStream, build_rtsp_url

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

def probe_exact(stream: EffectiveStream):
    """Probe only the selected paths; never infer a vendor path."""
    def probe_path(path):
        url = build_rtsp_url(stream, path)
        return probe_url(url) if url else None

    return {
        "main": probe_path(stream.main_path),
        "sub": probe_path(stream.sub_path),
        "main_path": stream.main_path,
        "sub_path": stream.sub_path,
    }


def _path_only(url):
    """Strip scheme://userinfo@host — return path (and query) only (zero-secret)."""
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def probe_camera(host, user=None, password=None):
    """Try main candidates then sub candidates until first hit each."""
    cands = build_rtsp_candidates(host, user, password)
    main = sub = None
    main_path = sub_path = None
    for url in cands["main"]:
        main = probe_url(url)
        if main:
            main_path = _path_only(url)
            break
    for url in cands["sub"]:
        sub = probe_url(url)
        if sub:
            sub_path = _path_only(url)
            break
    return {"main": main, "sub": sub, "main_path": main_path, "sub_path": sub_path}


def _probe_channel(base, ch, timeout):
    def probe(num):
        return probe_url(f"{base}/Streaming/Channels/{num}", timeout=timeout)

    main = probe(ch * 100 + 1)
    sub = probe(ch * 100 + 2)
    return {
        "channel": ch,
        "main": main,
        "sub": sub,
        "main_path": f"/Streaming/Channels/{ch * 100 + 1}" if main else None,
        "sub_path": f"/Streaming/Channels/{ch * 100 + 2}" if sub else None,
    }


def scan_camera_channels(host, user=None, password=None, max_channel=32, timeout=5.0):
    """Scan NVR channels 1..max (Hikvision main=odd/sub=even) in parallel waves.
    ponytail: hanya pola path Hikvision /Streaming/Channels/<ch>; kamera Dahua/other
    tetap pakai probe_camera (kandidat vendor). Berhenti setelah 2 wave berturut kosong."""
    u, p = _creds(user, password)
    auth = f"{u}:{p}@" if p else (f"{u}@" if u else "")
    base = f"rtsp://{auth}{host}"
    from concurrent.futures import ThreadPoolExecutor

    found = []
    misses = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for start in range(1, max_channel + 1, 4):
            channels = range(start, min(start + 4, max_channel + 1))
            wave = [pool.submit(_probe_channel, base, ch, timeout) for ch in channels]
            hit = False
            for fut in wave:
                result = fut.result()
                if result["main"] or result["sub"]:
                    hit = True
                    found.append(result)
            misses = 0 if hit else misses + 4
            if misses >= 8:
                break
    return found
