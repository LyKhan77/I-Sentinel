from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.db import get_db
from app.schemas.monitoring import MonitoringOut
from app.services import monitoring

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


@router.get("", response_model=MonitoringOut)
def get_monitoring(user=Depends(get_current_user), db=Depends(get_db)):
    """Kesehatan kamera, node, layanan, server saat ini (semua user login; read-only)."""
    return monitoring.snapshot(db)
