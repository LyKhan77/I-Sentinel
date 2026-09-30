"""Riwayat Monitoring (S2): heartbeat → bucket menit di memori → baris monitoring_sample → deret tren.

Heartbeat 10 s membawa nilai per jendela 10 s; menyimpan nilai terakhir per menit akan membuang lonjakan, jadi tiap
metrik diagregasi (avg/max/min) selama semenit. Bucket menit berjalan hilang saat API restart (≤ 1 menit).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

STATE_RANK = {"streaming": 0, "starting": 1, "stalled": 2, "reconnecting": 3}
# kunci terakhir path metrik → agregasi yang disimpan
AGG = {"cpu_pct": ("avg", "max"), "ram_pct": ("avg", "max"), "util_pct": ("avg", "max"),
       "vram_pct": ("max",), "temp_c": ("max",), "ms_avg": ("avg",), "ms_max": ("max",),
       "infer_fps": ("avg",), "mqtt_backlog": ("max",), "fps": ("min", "avg"), "frame_age_s": ("max",)}


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _minute(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)


class _Acc:
    """Akumulator satu metrik dalam satu bucket."""
    __slots__ = ("sum", "n", "max", "min")

    def __init__(self):
        self.sum, self.n, self.max, self.min = 0.0, 0, None, None

    def add(self, v: float) -> None:
        self.sum += v
        self.n += 1
        self.max = v if self.max is None else max(self.max, v)
        self.min = v if self.min is None else min(self.min, v)

    def value(self, kind: str) -> float:
        return round(self.sum / self.n if kind == "avg" else getattr(self, kind), 1)


_lock = threading.Lock()
_buckets: dict[tuple[int, datetime], dict] = {}  # (node_id, awal menit UTC) → {"acc": {path: _Acc}, "cams": {id: meta}}


def reset() -> None:
    with _lock:
        _buckets.clear()


def _extract(hw, modules) -> tuple[list[tuple[str, float]], dict[int, dict]]:
    """Heartbeat → [(path, nilai)] + meta kamera (target_fps, state). Tipe ngawur dilewati."""
    hw, mods = _dict(hw), _dict(modules)
    out: list[tuple[str, float]] = []

    def add(path, v):
        v = _num(v)
        if v is not None:
            out.append((path, v))

    host = _dict(hw.get("host"))
    add("cpu_pct", host.get("cpu_pct"))
    used, total = _num(host.get("ram_used_mb")), _num(host.get("ram_total_mb"))
    if used is not None and total:
        add("ram_pct", used / total * 100)
    for g in _list(hw.get("gpus")):
        idx = _num(_dict(g).get("idx"))
        if idx is None:
            continue
        i = int(idx)
        add(f"gpus.{i}.util_pct", g.get("util_pct"))
        vu, vt = _num(g.get("vram_used_mb")), _num(g.get("vram_total_mb"))
        if vu is not None and vt:
            add(f"gpus.{i}.vram_pct", vu / vt * 100)
        add(f"gpus.{i}.temp_c", g.get("temp_c"))
    det = _dict(mods.get("detector"))
    add("ms_avg", det.get("ms_avg"))
    add("ms_max", det.get("ms_max"))
    add("infer_fps", det.get("infer_fps"))
    add("mqtt_backlog", mods.get("mqtt_backlog"))
    cams: dict[int, dict] = {}
    for c in _list(mods.get("cameras")):
        if not isinstance(c, dict) or not isinstance(c.get("id"), int) or isinstance(c.get("id"), bool):
            continue
        m = cams.setdefault(c["id"], {"fps": None, "age": None, "target_fps": None, "state": None})
        fps, age, target = _num(c.get("fps")), _num(c.get("last_frame_age_s")), _num(c.get("target_fps"))
        if fps is not None:  # detect + face satu kamera → fps terendah
            m["fps"] = fps if m["fps"] is None else min(m["fps"], fps)
        if age is not None:
            m["age"] = age if m["age"] is None else max(m["age"], age)
        if target is not None:
            m["target_fps"] = target
        st = c.get("state")
        if st in STATE_RANK and (m["state"] is None or STATE_RANK[st] > STATE_RANK[m["state"]]):
            m["state"] = st
    for cid, m in cams.items():
        add(f"cameras.{cid}.fps", m["fps"])
        add(f"cameras.{cid}.frame_age_s", m["age"])
    return out, {cid: {"target_fps": m["target_fps"], "state": m["state"]} for cid, m in cams.items()}


def record(node_id: int, hw, modules, now: datetime | None = None) -> None:
    """Tambah satu heartbeat ke bucket menit node. Tidak pernah raise (dipanggil handler MQTT)."""
    try:
        values, cams = _extract(hw, modules)
        key = (node_id, _minute(now or datetime.now(timezone.utc)))
        with _lock:
            b = _buckets.setdefault(key, {"acc": {}, "cams": {}})
            for path, v in values:
                b["acc"].setdefault(path, _Acc()).add(v)
            for cid, meta in cams.items():
                cur = b["cams"].setdefault(cid, {"target_fps": None, "state": None})
                if meta["target_fps"] is not None:
                    cur["target_fps"] = meta["target_fps"]
                st = meta["state"]
                if st is not None and (cur["state"] is None or STATE_RANK[st] > STATE_RANK[cur["state"]]):
                    cur["state"] = st
    except Exception:
        logger.warning("monitoring history record failed", exc_info=True)


def _summarize(bucket: dict) -> dict:
    data: dict = {}
    for path, acc in bucket["acc"].items():
        parts = path.split(".")
        node = data
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = {k: acc.value(k) for k in AGG[parts[-1]]}
    for cid, meta in bucket["cams"].items():
        cam = data.setdefault("cameras", {}).setdefault(str(cid), {})
        if meta["target_fps"] is not None:
            cam["target_fps"] = meta["target_fps"]
        if meta["state"] is not None:
            cam["state"] = meta["state"]
    return data


def flush(now: datetime | None = None) -> list[tuple[int, datetime, dict]]:
    """Keluarkan bucket yang sudah selesai (menit < menit berjalan), urut (node, ts)."""
    current = _minute(now or datetime.now(timezone.utc))
    with _lock:
        done = sorted(k for k in _buckets if k[1] < current)
        items = [(k, _buckets.pop(k)) for k in done]
    return [(node_id, ts, _summarize(b)) for (node_id, ts), b in items]
