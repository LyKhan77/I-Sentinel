from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DetectorSettingsIn(BaseModel):
    default_ai_fps: float = Field(ge=0.5, le=25)
    default_confidence: float = Field(ge=0.05, le=0.95)
    motion_enabled: bool
    motion_threshold: float = Field(ge=0)
    motion_min_area: float = Field(ge=0, le=1)
    motion_force_interval_s: float = Field(gt=0)
    face_min_width_px: float = Field(ge=16, le=1000)
    face_min_det_score: float = Field(ge=0.1, le=0.99)
    face_max_yaw: float = Field(gt=0, le=1)
    face_blur_min: float = Field(ge=0)
    face_min_frames: int = Field(ge=1, le=20)


class DetectorSettingsOut(DetectorSettingsIn):
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
