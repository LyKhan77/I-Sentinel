"""Aturan kesehatan Monitoring (S3): katalog tetap + nilai yang bisa diatur (tabel setting, key "health_rules").

Satu sumber ambang untuk halaman "Kondisi saat ini" (S1) dan evaluator alert. Nilai tersimpan yang rusak diganti
default saat dibaca, jadi data buruk di DB tidak mematikan evaluasi atau halaman.
"""
from __future__ import annotations

import logging
import math

from app.models.setting import Setting

logger = logging.getLogger(__name__)

KEY = "health_rules"
SEVERITIES = ("warning", "critical")
DURATION_RANGE = (1, 60)
FIELDS = ("enabled", "threshold", "duration_min", "severity", "telegram")


def _rule(target, unit, lo, hi, threshold, duration, severity, telegram):
    return {"target": target, "unit": unit, "min": lo, "max": hi,
            "default": {"enabled": True, "threshold": threshold, "duration_min": duration,
                        "severity": severity, "telegram": telegram}}


CATALOG: dict[str, dict] = {
    "camera_no_frames": _rule("camera", "s", 10, 600, 30, 2, "critical", True),
    "camera_low_fps": _rule("camera", "%", 10, 100, 50, 10, "warning", False),
    "gpu_temp": _rule("gpu", "°C", 50, 110, 85, 5, "critical", True),
    "gpu_vram": _rule("gpu", "%", 50, 100, 90, 10, "warning", False),
    "node_ram": _rule("node", "%", 50, 100, 90, 10, "warning", False),
    "node_cpu": _rule("node", "%", 50, 100, 90, 10, "warning", False),
    "infer_latency": _rule("node", "ms", 5, 2000, 50, 5, "warning", False),
    "mqtt_backlog": _rule("node", "", 0, 10000, 0, 5, "warning", True),
}


def get_defaults() -> dict[str, dict]:
    return {k: dict(c["default"]) for k, c in CATALOG.items()}


def _check(rule: str, field: str, value):
    """Nilai field valid → dikembalikan (dinormalkan); tidak valid → ValueError."""
    c = CATALOG[rule]
    if field in ("enabled", "telegram"):
        if not isinstance(value, bool):
            raise ValueError(f"{rule}.{field} must be a boolean")
        return value
    if field == "severity":
        if value not in SEVERITIES:
            raise ValueError(f"{rule}.severity must be one of {SEVERITIES}")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{rule}.{field} must be a number")
    lo, hi = (c["min"], c["max"]) if field == "threshold" else DURATION_RANGE
    if not math.isfinite(value):
        raise ValueError(f"{rule}.{field} must be finite")
    if field == "duration_min" and value != int(value):
        raise ValueError(f"{rule}.duration_min must be an integer")
    if not lo <= value <= hi:
        raise ValueError(f"{rule}.{field} must be within {lo}-{hi}")
    return int(value) if field == "duration_min" else value


def _stored(db) -> dict:
    row = db.get(Setting, KEY)
    return dict(row.value or {}) if row is not None and isinstance(row.value, dict) else {}


def get(db) -> dict[str, dict]:
    out = get_defaults()
    for rule, fields in _stored(db).items():
        if rule not in CATALOG or not isinstance(fields, dict):
            continue
        for field, value in fields.items():
            if field not in FIELDS:
                continue
            try:
                out[rule][field] = _check(rule, field, value)
            except ValueError:
                logger.warning("health rule %s.%s rusak — memakai default", rule, field)
    return out


def put(db, patch: dict) -> dict[str, dict]:
    if not isinstance(patch, dict):
        raise ValueError("body must be an object")
    stored = _stored(db)
    for rule, fields in patch.items():
        if rule not in CATALOG:
            raise ValueError(f"unknown rule {rule!r}")
        if not isinstance(fields, dict):
            raise ValueError(f"{rule} must be an object")
        for field, value in fields.items():
            if field not in FIELDS:
                raise ValueError(f"unknown field {rule}.{field}")
            _check(rule, field, value)
    for rule, fields in patch.items():  # validasi dulu semua, baru tulis (PUT gagal tidak mengubah apa pun)
        stored[rule] = {**(stored.get(rule) if isinstance(stored.get(rule), dict) else {}), **fields}
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=stored))
    else:
        row.value = stored
    db.commit()
    return get(db)


def as_list(rules: dict[str, dict]) -> list[dict]:
    return [{"rule": k, **rules[k], "unit": c["unit"], "min": c["min"], "max": c["max"], "target": c["target"]}
            for k, c in CATALOG.items()]
