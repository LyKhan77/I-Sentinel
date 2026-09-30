"""Router Monitoring: kondisi saat ini (S1) + riwayat tren (S2)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.db import get_db
from app.schemas.monitoring import MonitoringHistoryOut, MonitoringOut
from app.services import monitoring, monitoring_history

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
