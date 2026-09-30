"""Router Monitoring: current condition, history, health rules and alerts."""
from __future__ import annotations

import logging
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


@router.get("/history", response_model=MonitoringHistoryOut)
def get_history(range_: Literal["1h", "6h", "24h", "7d"] = Query("6h", alias="range"),
                user=Depends(get_current_user), db=Depends(get_db)):
    """Deret tren Monitoring (riwayat 7 hari, downsample per rentang). Semua user login; read-only."""
    return monitoring_history.query(db, range_)


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
