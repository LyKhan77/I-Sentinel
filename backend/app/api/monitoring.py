"""Router Monitoring: current condition, history, health rules and alerts."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user, require_admin
from app.core.db import get_db
from app.schemas.monitoring import HealthAlertsOut, HealthRuleOut, HealthRulePatch, MonitoringHistoryOut, MonitoringOut
from app.services import health_alerts, health_rules, monitoring, monitoring_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


@router.get("", response_model=MonitoringOut)
def get_monitoring(user=Depends(get_current_user), db=Depends(get_db)):
    """Kesehatan kamera, node, layanan, server saat ini (semua user login; read-only)."""
    return monitoring.snapshot(db)


MAX_WINDOW = timedelta(hours=6)


@router.get("/history", response_model=MonitoringHistoryOut)
def get_history(range_: Literal["1h", "6h", "24h", "7d"] | None = Query(None, alias="range"),
                from_: datetime | None = Query(None, alias="from"),
                to: datetime | None = Query(None),
                node_id: int | None = None,
                user=Depends(get_current_user), db=Depends(get_db)):
    """Deret tren Monitoring (riwayat 7 hari, downsample per rentang). Semua user login; read-only.

    Dua mode: `range` relatif terhadap sekarang (default `6h`), atau jendela eksplisit
    `from`/`to` (ISO, naive = UTC, ≤ 6 jam) untuk panel Bukti event system. Keduanya eksklusif.
    """
    if (from_ is None) != (to is None):
        raise HTTPException(422, "from dan to harus dipakai bersama")
    if from_ is not None and to is not None:
        if range_ is not None:
            raise HTTPException(422, "range tidak bisa digabung dengan from/to")
        start, end = monitoring_history._utc(from_), monitoring_history._utc(to)
        if end <= start:
            raise HTTPException(422, "to harus lebih besar dari from")
        if end - start > MAX_WINDOW:
            raise HTTPException(422, f"jendela maksimum {MAX_WINDOW.total_seconds() / 3600:.0f} jam")
        return monitoring_history.query_window(db, start, end, node_id)
    return monitoring_history.query(db, range_ or "6h")


@router.get("/rules", response_model=list[HealthRuleOut])
def get_rules(user=Depends(get_current_user), db=Depends(get_db)):
    """Return effective health rules for any authenticated user."""
    return health_rules.as_list(health_rules.get(db))


@router.put("/rules", response_model=list[HealthRuleOut])
def put_rules(body: dict[str, HealthRulePatch], admin=Depends(require_admin), db=Depends(get_db)):
    """Validate the entire partial rule update before persisting it; admin only."""
    patch = {rule: p.model_dump(exclude_unset=True) for rule, p in body.items()}
    try:
        rules = health_rules.put(db, patch)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    logger.info("health rules updated by %s: %s", admin.username, patch)
    return health_rules.as_list(rules)


@router.get("/alerts", response_model=HealthAlertsOut)
def get_alerts(user=Depends(get_current_user), db=Depends(get_db)):
    """Return active health alerts and the latest resolved history for any authenticated user."""
    return health_alerts.list_alerts(db)
