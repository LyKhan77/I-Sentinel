"""Snapshot kesehatan untuk halaman Monitoring: kamera, node, layanan, server (kondisi saat ini, S1).

Aturan & ambang tetap (S3 akan membuatnya bisa diatur). Data node dari heartbeat terakhir di node.hw /
node.modules; tipe JSON divalidasi defensif karena berasal dari node.
"""
from __future__ import annotations

import time as _time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.config import settings
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.node import Node
from app.models.setting import Setting
from app.services import events_consumer, go2rtc, host_stats, retention, storage_settings, telegram
from app.services.node_health import _aware

FRAME_STALE_S = 30
LOW_FPS_RATIO = 0.8
RECONNECT_WARN = 3
GPU_TEMP_WARN_C = 85
VRAM_WARN_PCT = RAM_WARN_PCT = CPU_WARN_PCT = 90
HEARTBEAT_LATE_S = 20
SWEEP_STALE_H = 26
SERVICE_CACHE_S = 10

RANK = {"ok": 0, "unknown": 0, "warning": 1, "critical": 2}
STATE_RANK = {"streaming": 0, "starting": 1, None: 1, "stalled": 2, "reconnecting": 3}

_cache: dict = {"at": None, "services": None}


def reset_cache() -> None:
    _cache.update(at=None, services=None)


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _worst(*levels: str) -> str:
    return max(levels, key=lambda h: RANK[h]) if levels else "ok"


def _merge_workers(entries: list[dict]) -> dict | None:
    """Gabung entri detect/face satu kamera: kondisi terburuk. None bila tanpa statistik (heartbeat lama)."""
    stats = [e for e in entries if "state" in e]
    if not stats:
        return None
    worst = max(stats, key=lambda e: STATE_RANK.get(e.get("state"), 1))

    def ratio(e):
        fps, target = _num(e.get("fps")), _num(e.get("target_fps"))
        return fps / target if fps is not None and target else None

    ratios = [(ratio(e), e) for e in stats if ratio(e) is not None]
    slowest = min(ratios, key=lambda p: p[0])[1] if ratios else worst
    ages = [_num(e.get("last_frame_age_s")) for e in stats if _num(e.get("last_frame_age_s")) is not None]
    recon = [_num(e.get("reconnects_1h")) or 0 for e in stats]
    skips = [_num(e.get("motion_skip_pct")) for e in stats if _num(e.get("motion_skip_pct")) is not None]
    return {"state": worst.get("state"), "fps": _num(slowest.get("fps")),
            "target_fps": _num(slowest.get("target_fps")),
            "last_frame_age_s": max(ages) if ages else None, "reconnects_1h": max(recon) if recon else 0,
            "motion_skip_pct": skips[0] if skips else None}


def _camera_row(cam: Camera, node: Node | None, entries: list[dict] | None, streams: set[str] | None) -> dict:
    row = {"id": cam.id, "name": cam.name, "location": cam.location, "node_id": cam.node_id,
           "node_name": node.name if node else None, "enabled": bool(cam.enabled), "issues": [],
           "ai": None, "stream": {"registered": None if streams is None else f"cam_{cam.id}" in streams}}
    if not cam.enabled:
        row["health"] = "disabled"
        return row
    crit, warn = [], []
    if streams is not None and f"cam_{cam.id}" not in streams:
        warn.append("stream_missing")
    if cam.node_id is not None:
        if node is None or node.status == "offline":
            crit.append("node_offline")
        elif entries is None or not entries:
            crit.append("not_running")
        else:
            ai = _merge_workers(entries)
            row["ai"] = ai
            if ai is None:
                warn.append("no_data")
            else:
                age = ai["last_frame_age_s"]
                if ai["state"] in ("reconnecting", "stalled") or (age is not None and age > FRAME_STALE_S):
                    crit.append("no_frames")
                elif (ai["state"] != "starting" and ai["fps"] is not None and ai["target_fps"]
                        and ai["fps"] < LOW_FPS_RATIO * ai["target_fps"]):
                    warn.append("low_fps")
                if ai["reconnects_1h"] >= RECONNECT_WARN:
                    warn.append("reconnects")
    row["issues"] = crit + warn
    row["health"] = "critical" if crit else "warning" if warn else "ok"
    return row


def _node_row(node: Node, now: datetime) -> dict:
    hw, mods = _dict(node.hw), _dict(node.modules)
    host = _dict(hw.get("host"))
    gpus = [g for g in _list(hw.get("gpus")) if isinstance(g, dict)]
    seen = _aware(node.last_seen)
    age = round((now - seen).total_seconds(), 1) if seen else None
    det, face = _dict(mods.get("detector")), _dict(mods.get("face"))
    backlog = _num(mods.get("mqtt_backlog"))
    issues, crit = [], False
    if node.status == "offline":
        issues.append("offline")
        crit = True
    else:
        if age is not None and age > HEARTBEAT_LATE_S:
            issues.append("heartbeat_late")
        if any((_num(g.get("temp_c")) or 0) >= GPU_TEMP_WARN_C for g in gpus):
            issues.append("gpu_hot")
        if any(_num(g.get("vram_total_mb")) and (_num(g.get("vram_used_mb")) or 0) / g["vram_total_mb"] * 100
               >= VRAM_WARN_PCT for g in gpus):
            issues.append("vram_high")
        used, total = _num(host.get("ram_used_mb")), _num(host.get("ram_total_mb"))
        if used is not None and total and used / total * 100 >= RAM_WARN_PCT:
            issues.append("ram_high")
        if (_num(host.get("cpu_pct")) or 0) >= CPU_WARN_PCT:
            issues.append("cpu_high")
        if backlog:
            issues.append("mqtt_backlog")
    host_keys = ("cpu_pct", "ram_used_mb", "ram_total_mb", "disk_used_pct", "disk_free_gb")
    return {"id": node.id, "name": node.name, "status": node.status,
            "last_seen": seen.isoformat() if seen else None, "age_s": age,
            "health": "critical" if crit else "warning" if issues else "ok", "issues": issues,
            "host": {k: _num(host.get(k)) for k in host_keys},
            "gpus": [{"idx": _num(g.get("idx")), "name": g.get("name") if isinstance(g.get("name"), str) else None,
                      **{k: _num(g.get(k)) for k in ("util_pct", "vram_used_mb", "vram_total_mb", "temp_c", "power_w")}}
                     for g in gpus],
            "inference": {
                "detector": {"model": det.get("model") if isinstance(det.get("model"), str) else None,
                             "device": det.get("device") if isinstance(det.get("device"), str) else None,
                             **{k: _num(det.get(k)) for k in ("ms_avg", "ms_max", "infer_fps")}},
                "face": {"loaded": face.get("loaded") if isinstance(face.get("loaded"), bool) else None,
                         "queue": _num(face.get("queue"))},
                "mqtt_backlog": backlog}}


def _disk(root: str) -> dict | None:
    """disk_usage tahan storage root hilang (uji/instalasi belum mount) → None."""
    try:
        return retention.disk_usage(root)
    except OSError:
        return None


def _services(db, now: datetime) -> tuple[list[dict], set[str] | None]:
    if _cache["at"] is not None and now - _cache["at"] < timedelta(seconds=SERVICE_CACHE_S):
        return _cache["services"]
    out = []
    t0 = _time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        out.append({"key": "database", "health": "ok", "detail": None,
                    "latency_ms": round((_time.perf_counter() - t0) * 1000, 1)})
    except Exception as e:
        out.append({"key": "database", "health": "critical", "detail": type(e).__name__, "latency_ms": None})
    streams, ms = go2rtc.probe()
    out.append({"key": "go2rtc", "health": "ok" if streams is not None else "critical",
                "detail": f"{len(streams)} stream" if streams is not None else "unreachable", "latency_ms": ms})
    out.append({"key": "mqtt", "health": "ok" if events_consumer.connected.is_set() else "critical",
                "detail": None, "latency_ms": None})
    sweep = db.get(Setting, "retention_last_sweep")
    at = _dict(sweep.value if sweep else None).get("at")
    try:
        at_dt = _aware(datetime.fromisoformat(at)) if isinstance(at, str) else None
    except ValueError:
        at_dt = None
    stale = at_dt is None or now - at_dt > timedelta(hours=SWEEP_STALE_H)
    out.append({"key": "retention", "health": "warning" if stale else "ok",
                "detail": at_dt.isoformat() if at_dt else None, "latency_ms": None})
    if not telegram.get_token() or telegram.active_chat(db) is None:
        out.append({"key": "telegram", "health": "unknown", "detail": "not_configured", "latency_ms": None})
    else:
        last = db.query(Alert).filter(Alert.status.in_(("sent", "failed"))).order_by(Alert.id.desc()).first()
        queued = db.query(Alert).filter_by(status="queued").count()
        out.append({"key": "telegram", "health": "warning" if last is not None and last.status == "failed" else "ok",
                    "detail": f"{last.status if last else '—'} · queued {queued}", "latency_ms": None})
    usage = _disk(settings.storage_root)
    if usage is None:
        out.append({"key": "disk", "health": "warning", "detail": "unavailable", "latency_ms": None})
    else:
        over = usage["percent"] >= storage_settings.get(db)["disk_alert_percent"]
        out.append({"key": "disk", "health": "warning" if over else "ok", "detail": f"{usage['percent']}%",
                    "latency_ms": None})
    _cache.update(at=now, services=(out, streams))
    return out, streams


def snapshot(db, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    services, streams = _services(db, now)
    nodes = db.query(Node).order_by(Node.name).all()
    by_id = {n.id: n for n in nodes}
    per_node: dict[int, dict[int, list[dict]]] = {}
    for n in nodes:
        entries: dict[int, list[dict]] = {}
        for c in _list(_dict(n.modules).get("cameras")):
            if isinstance(c, dict) and isinstance(c.get("id"), int):
                entries.setdefault(c["id"], []).append(c)
        per_node[n.id] = entries
    cams = []
    for cam in db.query(Camera).order_by(Camera.name).all():
        node = by_id.get(cam.node_id) if cam.node_id is not None else None
        entries = per_node.get(cam.node_id, {}).get(cam.id) if node is not None else None
        cams.append(_camera_row(cam, node, entries, streams))
    node_rows = [_node_row(n, now) for n in nodes]
    used, total = host_stats.ram_mb()
    disk = _disk(settings.storage_root)

    def count(rows, keys=("ok", "warning", "critical")):
        return {k: sum(1 for r in rows if r["health"] == k) for k in keys}

    summary = {"cameras": count(cams, ("ok", "warning", "critical", "disabled")),
               "nodes": count(node_rows), "services": count([s for s in services if s["health"] != "unknown"])}
    summary["health"] = _worst(*[r["health"] for r in cams if r["health"] != "disabled"],
                               *[r["health"] for r in node_rows],
                               *[s["health"] for s in services if s["health"] != "unknown"])
    return {"generated_at": now.isoformat(), "summary": summary,
            "server": {"cpu_pct": host_stats.cpu_pct(), "ram_used_mb": used, "ram_total_mb": total,
                       "disk_used_pct": disk["percent"] if disk else None,
                       "disk_free_gb": round(disk["free"] / 1024 ** 3, 1) if disk else None},
            "nodes": node_rows, "cameras": cams, "services": services}
