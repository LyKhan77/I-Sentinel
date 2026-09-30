"""Riwayat Monitoring (S2): heartbeat → bucket menit di memori → baris monitoring_sample → deret tren.

Heartbeat 10 s membawa nilai per jendela 10 s; menyimpan nilai terakhir per menit akan membuang lonjakan, jadi tiap
metrik diagregasi (avg/max/min) selama semenit. Bucket menit berjalan hilang saat API restart (≤ 1 menit).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from app.core.db import SessionLocal
from app.models.camera import Camera
from app.models.event import Event
from app.models.monitoring_sample import MonitoringSample
from app.models.node import Node

logger = logging.getLogger(__name__)

STATE_RANK = {"streaming": 0, "starting": 1, "stalled": 2, "reconnecting": 3}
SAMPLE_INTERVAL_S = 60
RETENTION_DAYS = 7
PRUNE_EVERY_S = 3600
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
    # naive dibaca sebagai UTC (konsisten dengan _utc), bukan zona lokal mesin
    dt = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
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


def write(db, rows: list[tuple[int, datetime, dict]]) -> int:
    """Simpan bucket selesai; node tak dikenal / data kosong / duplikat (node, ts) dilewati."""
    rows = [r for r in rows if r[2]]
    if not rows:
        return 0
    known = {nid for (nid,) in db.query(Node.id).filter(Node.id.in_({r[0] for r in rows}))}
    added = 0
    for node_id, ts, data in rows:
        if node_id not in known:
            continue
        if db.query(MonitoringSample.id).filter_by(node_id=node_id, ts=ts).first() is not None:
            continue
        db.add(MonitoringSample(node_id=node_id, ts=ts, data=data))
        added += 1
    db.commit()
    return added


def prune(db, now: datetime) -> int:
    n = db.query(MonitoringSample).filter(MonitoringSample.ts < now - timedelta(days=RETENTION_DAYS)).delete(
        synchronize_session=False)
    db.commit()
    return n


class HistorySampler:
    """Thread latar: tiap interval_s tulis bucket selesai; pangkas > RETENTION_DAYS sekali per jam."""

    def __init__(self, interval_s: float = SAMPLE_INTERVAL_S, session_factory=SessionLocal):
        self.interval_s = interval_s
        self._session_factory = session_factory
        self._last_prune: datetime | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        rows = flush(now)  # dikeluarkan dulu: bila DB gagal, bucket dibuang (memori tidak menumpuk)
        db = self._session_factory()
        try:
            try:
                added = write(db, rows)
            except Exception:
                db.rollback()
                raise
            from app.services import health_alerts  # local import avoids the history/evaluator cycle
            try:
                health_alerts.evaluate(db, now)
            except Exception:
                db.rollback()
                logger.warning("health alert evaluation failed", exc_info=True)
            if self._last_prune is None or (now - self._last_prune).total_seconds() >= PRUNE_EVERY_S:
                prune(db, now)
                try:
                    health_alerts.prune(db, now)
                except Exception:
                    db.rollback()
                    logger.warning("health alert prune failed", exc_info=True)
                self._last_prune = now
            return added
        finally:
            db.close()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="monitoring-history")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.run_once()
            except Exception:
                logger.warning("monitoring history sample failed", exc_info=True)


sampler = HistorySampler()

RANGES = {"1h": (timedelta(hours=1), 60), "6h": (timedelta(hours=6), 60),
          "24h": (timedelta(hours=24), 300), "7d": (timedelta(days=7), 1800)}
NODE_KEYS = ("cpu_pct", "ram_pct", "ms_avg", "ms_max", "infer_fps", "mqtt_backlog")
GPU_KEYS = ("util_pct", "vram_pct", "temp_c")


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _z(dt: datetime) -> str:
    return _utc(dt).isoformat().replace("+00:00", "Z")


def _floor(dt: datetime, bucket_s: int) -> datetime:
    ts = int(_utc(dt).timestamp())
    return datetime.fromtimestamp(ts - ts % bucket_s, tz=timezone.utc)


def _merge(parts: list) -> dict | None:
    """Gabung agregat beberapa menit: avg → rata-rata, max → maks, min → min."""
    parts = [p for p in parts if isinstance(p, dict)]
    out = {}
    for kind, fn in (("avg", lambda v: sum(v) / len(v)), ("max", max), ("min", min)):
        vals = [_num(p.get(kind)) for p in parts if _num(p.get(kind)) is not None]
        if vals:
            out[kind] = round(fn(vals), 1)
    return out or None


def _offline(db, node: Node, start: datetime, now: datetime) -> list[dict]:
    """Periode offline dari event system node: offline → online berikutnya; tanpa pasangan → to None."""
    base = db.query(Event).filter(Event.type == "system", Event.node_id == node.id,
                                  Event.payload["reason"].as_string().in_(("lwt", "timeout", "online")))
    before = base.filter(Event.ts_event < start).order_by(Event.ts_event.desc()).first()
    within = base.filter(Event.ts_event >= start, Event.ts_event <= now).order_by(Event.ts_event).all()
    is_off = lambda e: _dict(e.payload).get("reason") in ("lwt", "timeout")  # whitelist: hanya dua alasan offline resmi
    periods, cur = [], (start if before is not None and is_off(before) else None)
    for e in within:
        ts = _utc(e.ts_event)
        if is_off(e) and cur is None:
            cur = ts
        elif _dict(e.payload).get("reason") == "online" and cur is not None:
            periods.append({"from": _z(cur), "to": _z(ts)})
            cur = None
    if cur is not None:
        periods.append({"from": _z(cur), "to": None})
    return periods


def query(db, range_key: str, now: datetime | None = None) -> dict:
    """Deret tren per node untuk satu rentang (downsample ke bucket_s; bucket kosong tidak dikirim)."""
    span, bucket_s = RANGES[range_key]
    now = _utc(now or datetime.now(timezone.utc))
    start = now - span
    nodes = db.query(Node).order_by(Node.name).all()
    names = {cid: name for cid, name in db.query(Camera.id, Camera.name)}
    grouped: dict[int, dict[datetime, list[dict]]] = {}
    for r in db.query(MonitoringSample).filter(MonitoringSample.ts >= start).order_by(MonitoringSample.ts):
        grouped.setdefault(r.node_id, {}).setdefault(_floor(r.ts, bucket_s), []).append(_dict(r.data))
    out = []
    for n in nodes:
        series = {k: [] for k in NODE_KEYS}
        gpus: dict[str, dict] = {}
        cams: dict[str, dict] = {}
        for b, datas in sorted(grouped.get(n.id, {}).items()):
            t = _z(b)
            for k in NODE_KEYS:
                if (pt := _merge([d.get(k) for d in datas])) is not None:
                    series[k].append({"t": t, **pt})
            for gi in sorted({g for d in datas for g in _dict(d.get("gpus"))}):
                for k in GPU_KEYS:
                    pt = _merge([_dict(_dict(d.get("gpus")).get(gi)).get(k) for d in datas])
                    if pt is not None:
                        gpus.setdefault(gi, {key: [] for key in GPU_KEYS})[k].append({"t": t, **pt})
            for ci in {c for d in datas for c in _dict(d.get("cameras")) if str(c).isdigit()}:
                entries = [_dict(_dict(d.get("cameras")).get(ci)) for d in datas]
                cam = cams.setdefault(ci, {"fps": [], "frame_age_s": [], "target_fps": None})
                for k in ("fps", "frame_age_s"):
                    if (pt := _merge([e.get(k) for e in entries])) is not None:
                        cam[k].append({"t": t, **pt})
                targets = [_num(e.get("target_fps")) for e in entries if _num(e.get("target_fps")) is not None]
                if targets:
                    cam["target_fps"] = targets[-1]
        cam_rows = [{"id": int(ci), "name": names.get(int(ci), f"#{ci}"), **c} for ci, c in cams.items()]
        cam_rows.sort(key=lambda c: c["name"])
        out.append({"id": n.id, "name": n.name, "series": {**series, "gpus": gpus}, "cameras": cam_rows,
                    "offline": _offline(db, n, start, now)})
    return {"range": range_key, "bucket_s": bucket_s, "from": _z(start), "to": _z(now), "nodes": out}
