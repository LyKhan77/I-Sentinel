"""Alert kesehatan Monitoring (S3): evaluasi aturan dari sampel menit S2 → baris health_alert + event + Telegram.

Stateless terhadap jendela data: menyala bila setiap menit dalam jendela durasi melanggar; pulih bila RESOLVE_MIN
menit terakhir normal. Karena tidak ada counter, evaluasi ulang di menit yang sama tidak mengubah hasil (idempoten).
Node offline / tanpa sampel di jendela → ditahan (restart API tidak menutup alert).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from app.models.camera import Camera
from app.models.health_alert import HealthAlert
from app.models.monitoring_sample import MonitoringSample
from app.models.node import Node
from app.schemas.event import EventOut
from app.services import health_rules, telegram
from app.services.ingest import ingest_event
from app.services.monitoring import analyzed_camera_ids
from app.services.monitoring_history import _dict, _minute, _num, _utc, minute_samples
from app.ws.hub import hub

logger = logging.getLogger(__name__)

RESOLVE_MIN = 2
RETENTION_DAYS = 7
TITLES = {"camera_no_frames": "Kamera tanpa frame", "camera_low_fps": "FPS kamera rendah", "gpu_temp": "GPU panas",
          "gpu_vram": "VRAM GPU tinggi", "node_ram": "RAM node tinggi", "node_cpu": "CPU node tinggi",
          "infer_latency": "Latensi inferensi tinggi", "mqtt_backlog": "Event tertahan di node"}
OPS = {"camera_no_frames": ">", "camera_low_fps": "<", "mqtt_backlog": ">"}  # lainnya "≥"


def _check(rule: str, data: dict | None, key: str, threshold: float) -> tuple[bool | None, float | None]:
    """(melanggar?, nilai) untuk satu menit; (None, None) = menit tanpa data (bukan pelanggaran, bukan normal)."""
    if data is None:
        return None, None
    if rule == "camera_no_frames":
        cam = _dict(_dict(data.get("cameras")).get(key))
        if not cam:
            return True, None  # sampel node ada, kamera tidak ada di heartbeat
        age = _num(_dict(cam.get("frame_age_s")).get("max"))
        return (None if age is None else age > threshold), age
    if rule == "camera_low_fps":
        cam = _dict(_dict(data.get("cameras")).get(key))
        fps, target = _num(_dict(cam.get("fps")).get("min")), _num(cam.get("target_fps"))
        if fps is None or target is None or target <= 0 or cam.get("state") == "starting":
            return None, None
        pct = round(fps / target * 100, 1)
        return fps < threshold / 100 * target, pct
    if rule in ("gpu_temp", "gpu_vram"):
        field = "temp_c" if rule == "gpu_temp" else "vram_pct"
        v = _num(_dict(_dict(_dict(data.get("gpus")).get(key)).get(field)).get("max"))
    elif rule in ("node_ram", "node_cpu"):
        v = _num(_dict(data.get("ram_pct" if rule == "node_ram" else "cpu_pct")).get("avg"))
    elif rule == "infer_latency":
        v = _num(_dict(data.get("ms_avg")).get("avg"))
    else:  # mqtt_backlog
        v = _num(_dict(data.get("mqtt_backlog")).get("max"))
    if v is None:
        return None, None
    return (v > threshold if rule == "mqtt_backlog" else v >= threshold), v


def _evidence(db, node_id: int, rule: str, key: str, threshold: float,
              start: datetime, end: datetime) -> dict:
    """Build one stored health metric series from per-minute samples."""
    start, end = _minute(start), _minute(end)
    count = max(0, int((end - start).total_seconds() // 60))
    if count > 360:
        start = end - timedelta(minutes=360)
        count = 360
    samples = minute_samples(db, node_id, start, end)
    values = []
    for offset in range(count):
        minute = start + timedelta(minutes=offset)
        value = _check(rule, samples.get(minute), key, threshold)[1]
        values.append(round(value, 1) if value is not None else None)
    return {"v": 1, "from": start.isoformat().replace("+00:00", "Z"), "step_s": 60,
            "series": {"value": values}}


def _targets(node: Node, by_min: dict, cams: list[Camera]) -> list[tuple[str, str, str, int | None, str]]:
    """[(rule, target, label, camera_id, key)] untuk satu node. key = id kamera / idx GPU / '' (node)."""
    out = []
    for rule in ("node_ram", "node_cpu", "infer_latency", "mqtt_backlog"):
        out.append((rule, f"node:{node.id}", node.name, None, ""))
    gpu_idx = sorted(_dict(by_min[max(by_min)].get("gpus")), key=lambda s: (len(s), s))
    for idx in gpu_idx:
        for rule in ("gpu_temp", "gpu_vram"):
            out.append((rule, f"gpu:{node.id}:{idx}", f"GPU {idx} · {node.name}", None, idx))
    for cam in cams:
        for rule in ("camera_no_frames", "camera_low_fps"):
            out.append((rule, f"cam:{cam.id}", cam.name, cam.id, str(cam.id)))
    return out


def _emit(db, node: Node, camera_id, severity: str, payload: dict, now: datetime) -> None:
    # ingest_event commits the pending health transition and its web event together.
    try:
        camera_id = camera_id if camera_id is not None and db.get(Camera, camera_id) is not None else None
        status, ev = ingest_event(db, {"event_id": str(uuid.uuid4()), "type": "system", "node_id": node.id,
                                       "camera_id": camera_id, "severity": severity, "ts_event": now.isoformat(),
                                       "payload": payload})
    except Exception:
        db.rollback()
        raise
    if status == "created" and ev is not None:
        try:
            asyncio.run(hub.broadcast(EventOut.model_validate(ev).model_dump(mode="json")))
        except Exception:
            logger.exception("health event broadcast failed")


def _fmt(v) -> str:
    return "—" if v is None else (f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}")


def _send(send, db, text: str) -> None:
    """Telegram failure must not stop evaluation or expose token-bearing exceptions."""
    try:
        send(db, text)
    except Exception:
        logger.warning("health Telegram delivery failed")


def evaluate(db, now: datetime | None = None, send=None) -> dict:
    """Evaluate completed minute windows and persist each winning transition once."""
    now = _utc(now or datetime.now(timezone.utc))
    cur = _minute(now)
    send = send or telegram.send_text
    rules = health_rules.get(db)
    enabled = {k: r for k, r in rules.items() if r["enabled"]}
    lookback = cur - timedelta(minutes=max([r["duration_min"] for r in rules.values()] + [RESOLVE_MIN]) + RESOLVE_MIN)
    samples: dict[int, dict[datetime, dict]] = {}
    for s in db.query(MonitoringSample).filter(MonitoringSample.ts >= lookback, MonitoringSample.ts < cur):
        samples.setdefault(s.node_id, {})[_utc(s.ts)] = _dict(s.data)
    analyzed = analyzed_camera_ids(db)
    cams_by_node: dict[int, list[Camera]] = {}
    for c in db.query(Camera).filter(Camera.enabled.is_(True), Camera.node_id.isnot(None)).order_by(Camera.id):
        if c.id in analyzed:
            cams_by_node.setdefault(c.node_id, []).append(c)
    active = {(a.rule, a.target): a for a in db.query(HealthAlert).filter(HealthAlert.resolved_at.is_(None))}
    result = {"fired": [], "resolved": [], "closed": []}
    keep: set[tuple[str, str]] = set()
    nodes = db.query(Node).order_by(Node.id).all()

    def payload(a_rule, target, label, value, threshold, state, extra=None):
        unit = health_rules.CATALOG[a_rule]["unit"]
        return {"kind": "health", "rule": a_rule, "target": target, "label": label, "value": value,
                "threshold": threshold, "unit": unit, "duration_min": rules[a_rule]["duration_min"],
                "state": state, **(extra or {})}

    for node in nodes:
        by_min = samples.get(node.id, {})
        if node.status == "offline" or not by_min:
            keep |= {k for k, a in active.items() if a.node_id == node.id}  # ditahan
            continue
        for rule, target, label, cam_id, key in _targets(node, by_min, cams_by_node.get(node.id, [])):
            r = enabled.get(rule)
            if r is None:
                continue
            keep.add((rule, target))
            th = r["threshold"]
            window = [cur - i * timedelta(minutes=1) for i in range(r["duration_min"], 0, -1)]
            checks = [_check(rule, by_min.get(m), key, th) for m in window]
            last_val = checks[-1][1]
            # Serialize each transition on Postgres; SQLite also has the minute-unique insert fence.
            db.query(Node.id).filter(Node.id == node.id).with_for_update().first()
            a = db.query(HealthAlert).filter_by(rule=rule, target=target, resolved_at=None).first()
            if a is None:
                if all(v is True for v, _ in checks):
                    try:
                        evidence = _evidence(
                            db, node.id, rule, key, th,
                            cur - timedelta(minutes=r["duration_min"] + 30), cur,
                        )
                    except Exception:
                        logger.exception("health evidence build failed")
                        db.rollback()
                        evidence = None

                    a = HealthAlert(rule=rule, target=target, node_id=node.id, camera_id=cam_id, label=label,
                                    severity=r["severity"], value=last_val, threshold=th, started_at=cur)
                    db.add(a)
                    try:
                        db.flush()
                    except IntegrityError:
                        db.rollback()
                        if db.query(HealthAlert.id).filter_by(rule=rule, target=target, started_at=cur).first():
                            continue
                        raise
                    _emit(db, node, cam_id, r["severity"],
                          payload(rule, target, label, last_val, th, "firing",
                                  {"evidence": evidence} if evidence is not None else None), now)
                    unit = health_rules.CATALOG[rule]["unit"]
                    if r["telegram"]:
                        _send(send, db, f"⚠️ {TITLES[rule]}: {label} — {_fmt(last_val)}{unit} "
                                 f"({OPS.get(rule, '≥')} {_fmt(th)}{unit} selama {r['duration_min']} menit)")
                    result["fired"].append((rule, target))
                continue
            recent = [_check(rule, by_min.get(cur - i * timedelta(minutes=1)), key, th)
                      for i in range(RESOLVE_MIN, 0, -1)]
            if recent[-1][0] is True and last_val is not None:
                a.value = last_val
                db.commit()
            if all(v is False for v, _ in recent):
                started_at = _utc(a.started_at)
                alert_id = a.id
                alert_camera_id, alert_label = a.camera_id, a.label
                alert_threshold = a.threshold
                evidence_start = max(
                    started_at - timedelta(minutes=15),
                    cur - timedelta(minutes=360),
                )
                try:
                    evidence = _evidence(
                        db, node.id, rule, key, alert_threshold, evidence_start, cur,
                    )
                except Exception:
                    logger.exception("health evidence build failed")
                    db.rollback()
                    evidence = None
                changed = db.query(HealthAlert).filter(
                    HealthAlert.id == alert_id, HealthAlert.resolved_at.is_(None),
                ).update({"resolved_at": now}, synchronize_session="fetch")
                if not changed:
                    db.rollback()
                    continue
                lasted = max(1, round((now - started_at).total_seconds() / 60))
                extra = {"lasted_min": lasted}
                if evidence is not None:
                    extra["evidence"] = evidence
                _emit(db, node, alert_camera_id, "info",
                      payload(rule, target, alert_label, recent[-1][1], alert_threshold,
                              "resolved", extra), now)
                if r["telegram"]:
                    _send(send, db, f"✅ {TITLES[rule]} normal: {alert_label} — {lasted} menit")
                result["resolved"].append((rule, target))

    node_by_id = {n.id: n for n in nodes}
    for k, a in active.items():
        if k in keep or a.resolved_at is not None:
            continue
        changed = db.query(HealthAlert).filter(HealthAlert.id == a.id, HealthAlert.resolved_at.is_(None)).update(
            {"resolved_at": now}, synchronize_session="fetch")
        if not changed:
            db.rollback()
            continue
        node = node_by_id.get(a.node_id)
        if node is not None:
            _emit(db, node, a.camera_id, "info",
                  payload(a.rule, a.target, a.label, a.value, a.threshold, "resolved", {"closed": True}), now)
        else:
            db.commit()
        result["closed"].append(k)
    return result


def prune(db, now: datetime) -> int:
    """Delete only resolved alerts older than seven days."""
    now = _utc(now)
    n = db.query(HealthAlert).filter(HealthAlert.resolved_at.isnot(None),
                                     HealthAlert.resolved_at < now - timedelta(days=RETENTION_DAYS)).delete(
        synchronize_session=False)
    db.commit()
    return n


def list_alerts(db) -> dict:
    """Return severity-ordered active alerts and the latest 50 resolved alerts, with UTC timestamps."""
    def item(a: HealthAlert) -> dict:
        out = {key: getattr(a, key) for key in ("id", "rule", "target", "label", "node_id", "camera_id",
                                               "severity", "value", "threshold")}
        return {**out, "unit": health_rules.CATALOG.get(a.rule, {}).get("unit", ""),
                "started_at": _utc(a.started_at),
                "resolved_at": _utc(a.resolved_at) if a.resolved_at is not None else None}

    active = db.query(HealthAlert).filter(HealthAlert.resolved_at.is_(None)).all()
    ranks = {"critical": 0, "warning": 1}
    active.sort(key=lambda a: (ranks.get(a.severity, 2), _utc(a.started_at), a.id))
    recent = (db.query(HealthAlert).filter(HealthAlert.resolved_at.isnot(None))
              .order_by(HealthAlert.resolved_at.desc(), HealthAlert.id.desc()).limit(50).all())
    return {"active": [item(a) for a in active], "recent": [item(a) for a in recent]}
