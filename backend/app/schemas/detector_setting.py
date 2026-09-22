from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DetectorSettingsIn(BaseModel):
    default_ai_fps: float = Field(ge=0.5, le=25)
    default_confidence: float = Field(ge=0.05, le=0.95)
    motion_enabled: bool
    motion_threshold: float = Field(ge=0)
    motion_min_area: float = Field(ge=0, le=1)
    motion_force_interval_s: float = Field(gt=0)


class DetectorSettingsOut(DetectorSettingsIn):
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
