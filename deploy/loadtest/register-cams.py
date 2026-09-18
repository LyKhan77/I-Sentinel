"""Daftarkan kamera sintetis ke I-Sentinel lewat API.

    python register-cams.py add 32
    python register-cams.py remove

Kamera dibuat dengan pola nama SYNTH-01..N (mudah dihapus massal).
Auth: cookie login admin (ISENTINEL_PASS env).
"""
import json
import os
import sys
import urllib.request

API = os.environ.get("ISENTINEL_API", "http://127.0.0.1:8000")
USER = os.environ.get("ISENTINEL_USER", "admin")
PASS = os.environ.get("ISENTINEL_PASS")
PREFIX = "SYNTH-"


def _req(path, method="GET", body=None, cookie=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req) as res:
        raw = res.read()
        return res.headers.get("Set-Cookie"), (json.loads(raw) if raw else None)


def _login():
    cookie, _ = _req("/api/v1/auth/login", "POST", {"username": USER, "password": PASS})
    return cookie.split(";")[0]


def _cameras(cookie):
    _, rows = _req("/api/v1/cameras", cookie=cookie)
    return rows


def add(n):
    cookie = _login()
    node_id = next((n_["id"] for n_ in _req("/api/v1/nodes", cookie=cookie)[1]
                    if n_["type"] == "server"), None)
    created = 0
    for i in range(1, n + 1):
        name = f"{PREFIX}{i:02d}"
        if any(c["name"] == name for c in _cameras(cookie)):
            continue
        _req("/api/v1/cameras", "POST", {
            "name": name,
            "location": "LOADTEST",
            "host": "127.0.0.1:8554",  # port wajib: pull kembali dari go2rtc sendiri
            "rtsp_sub": f"/synth_{i}",
            "node_id": node_id,
        }, cookie=cookie)
        created += 1
    print(f"dibuat: {created}")


def remove():
    cookie = _login()
    removed = 0
    for c in _cameras(cookie):
        if str(c["name"]).startswith(PREFIX):
            _req(f"/api/v1/cameras/{c['id']}", "DELETE", cookie=cookie)
            removed += 1
    print(f"dihapus: {removed}")


if __name__ == "__main__":
    if not PASS:
        sys.exit("ISENTINEL_PASS belum diset")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "add":
        add(int(sys.argv[2]) if len(sys.argv) > 2 else 32)
    elif cmd == "remove":
        remove()
    else:
        print(__doc__)
        sys.exit(2)
