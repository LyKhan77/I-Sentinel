from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import settings
from app.core.db import get_db
from app.models.detector_setting import DetectorSetting
from app.schemas.detector_setting import DetectorSettingsIn, DetectorSettingsOut
from app.services import config_push

router = APIRouter(prefix="/api/v1/detector-settings", tags=["detector-settings"])


def _effective(db: Session) -> DetectorSetting:
    return db.get(DetectorSetting, 1) or DetectorSetting(
        id=1, default_ai_fps=settings.default_ai_fps,
        default_confidence=settings.detector_conf, motion_enabled=settings.motion_enabled,
        motion_threshold=settings.motion_threshold, motion_min_area=settings.motion_min_area,
        motion_force_interval_s=settings.motion_force_interval_s,
    )


@router.get("", response_model=DetectorSettingsOut)
def get_detector_settings(db: Session = Depends(get_db), admin=Depends(require_admin)):
    return _effective(db)


@router.put("", response_model=DetectorSettingsOut)
def put_detector_settings(values: DetectorSettingsIn, db: Session = Depends(get_db), admin=Depends(require_admin)):
    row = db.get(DetectorSetting, 1)
    if row is None:
        row = DetectorSetting(id=1, **values.model_dump())
        db.add(row)
    else:
        for key, value in values.model_dump().items():
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    config_push.republish_all(db)
    return row
