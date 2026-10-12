"""Tujuan event per behavior (`delivery`) di node: padanan murni `zone_delivery` di API.

Modul netral tanpa impor `node.py` (siklus): dipakai `node.py` untuk analyzer alert dan
`face_worker.py` untuk penekanan event absensi. Semua fungsi di sini murni supaya aturan
kedaluwarsa Mode uji bisa diuji langsung, dengan jam dinding node (`time.time()`).
"""
from __future__ import annotations

from datetime import datetime, timezone

# Lama label overlay Mode uji bertahan pada track pemicu (detik).
FLASH_S = 6.0


def wall_of(value) -> float | None:
    """ISO-8601 (UTC beraksi zona atau tanpa offset) → epoch; `None` bila hilang/tak terbaca."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def delivery_mode(cfg: dict | None, now_wall: float) -> str:
    """Tujuan efektif satu behavior menurut jam dinding node: `test` | `all` | `inbox`.

    Padanan `effective_delivery` di API (node tidak mengimpor paket backend): Mode uji yang
    sudah lewat `test_until` kembali ke `revert_to` tanpa restart. `cfg` = `analyzer.delivery_cfg`.
    """
    if not isinstance(cfg, dict):
        return "all"
    if cfg.get("delivery") == "test":
        until = wall_of(cfg.get("test_until"))
        if until is not None and now_wall < until:
            return "test"
        return cfg.get("revert_to") if cfg.get("revert_to") in ("all", "inbox") else "all"
    if cfg.get("delivery") in ("all", "inbox"):
        return cfg["delivery"]
    return "all" if cfg.get("telegram") else "inbox"


def delivery_cfg_for(behavior: dict, zone_telegram: bool) -> dict:
    """Konfigurasi tujuan event satu behavior untuk analyzer; item tanpa key → flag zona."""
    return {
        "delivery": behavior.get("delivery"),
        "test_until": behavior.get("test_until"),
        "revert_to": behavior.get("revert_to"),
        "telegram": behavior.get("telegram", zone_telegram),
    }


def zone_attendance_cfg(zone: dict) -> dict | None:
    """Item behavior `attendance` pada dict zona; `None` bila tidak ada.

    Zona legacy (config pra-R5, `behaviors is None`) dan item non-dict dilewati: tanpa
    konfigurasi, Mode uji tidak berlaku dan absensi berperilaku seperti sebelumnya.
    """
    if not isinstance(zone, dict):
        return None
    for b in zone.get("behaviors") or []:
        if isinstance(b, dict) and b.get("kind") == "attendance":
            return b
    return None
