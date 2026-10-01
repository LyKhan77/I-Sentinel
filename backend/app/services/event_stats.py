"""Agregat statistik event hari ini untuk GET /api/v1/events/stats/today.

Router tetap tipis (AGENTS.md §6): endpoint hanya memanggil `today(db)`.
"""
from datetime import date, datetime, time, timezone

from sqlalchemy.orm import Session

from app.models.event import Event

SEVERITY_KEYS = ("critical", "warning", "info")


def _local_hour(ts: datetime) -> int:
    """Jam (0-23) ts dalam zona waktu sistem.

    SQLite uji mengembalikan timestamp naive yang tersimpan dalam UTC, jadi
    nilai naive diperlakukan UTC dulu sebelum dikonversi; Postgres mengembalikan
    nilai aware dan jalur keduanya sama.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone().hour


def today(db: Session) -> dict:
    """Jumlah event sejak tengah malam lokal, tanpa tipe `attendance` (D1).

    Kembalikan dict dengan kunci total, by_type, by_severity (selalu tiga kunci),
    by_hour dan critical_by_hour (24 angka, indeks = jam lokal 0-23).
    """
    # ponytail: fetch O(event hari ini); pindah ke GROUP BY date_trunc bila volume > puluhan ribu/hari
    midnight = datetime.combine(date.today(), time.min).astimezone()
    rows = (
        db.query(Event.type, Event.severity, Event.ts_event)
        # Batas instan yang sama dengan `midnight`; dinormalisasi UTC supaya
        # perbandingan string di SQLite juga benar (SQLite uji simpan wall UTC).
        .filter(Event.ts_event >= midnight.astimezone(timezone.utc), Event.type != "attendance")
        .all()
    )
    total = 0
    by_type: dict[str, int] = {}
    by_severity = dict.fromkeys(SEVERITY_KEYS, 0)
    by_hour = [0] * 24
    critical_by_hour = [0] * 24
    for ev_type, severity, ts in rows:
        total += 1
        by_type[ev_type] = by_type.get(ev_type, 0) + 1
        if severity in by_severity:
            by_severity[severity] += 1
        hour = _local_hour(ts)
        by_hour[hour] += 1
        if severity == "critical":
            critical_by_hour[hour] += 1
    return {
        "total": total,
        "by_type": by_type,
        "by_severity": by_severity,
        "by_hour": by_hour,
        "critical_by_hour": critical_by_hour,
    }
