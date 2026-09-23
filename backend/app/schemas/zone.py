from pydantic import BaseModel, Field, field_validator, model_validator

VALID_TYPES = {"free", "restricted", "absensi", "behavior", "attendance"}
VALID_BEHAVIOR_KINDS = {"intrusion", "loitering", "running", "attendance"}
VALID_DIRECTIONS = {"entry", "exit"}
VALID_DAYS = set(range(1, 8))


def _validate_behaviors(v: list | None) -> list | None:
    """behaviors = [{"kind": ..., "trigger_seconds": int, [speed_limit_mps]}]."""
    if v is None:
        return v
    if not isinstance(v, list):
        raise ValueError("behaviors must be a list")
    for b in v:
        if not isinstance(b, dict) or b.get("kind") not in VALID_BEHAVIOR_KINDS:
            raise ValueError(f"behavior kind must be one of {sorted(VALID_BEHAVIOR_KINDS)}")
        trig = b.get("trigger_seconds", 0)
        if not isinstance(trig, int) or isinstance(trig, bool) or trig < 0:
            raise ValueError("trigger_seconds must be an int >= 0")
        speed = b.get("speed_limit_mps")
        if speed is not None and (not isinstance(speed, (int, float)) or isinstance(speed, bool) or speed < 0):
            raise ValueError("speed_limit_mps must be a number >= 0")
    return v


def _validate_polygon(v: list) -> list:
    if not isinstance(v, list) or len(v) < 3:
        raise ValueError("polygon needs at least 3 points")
    for p in v:
        if (not isinstance(p, (list, tuple)) or len(p) != 2
                or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in p)
                or not (0 <= p[0] <= 1) or not (0 <= p[1] <= 1)):
            raise ValueError("each point must be [x, y] with 0 <= x,y <= 1")
    return v


def _validate_schedule(v: dict | None) -> dict | None:
    if v is None:
        return v
    if (not isinstance(v, dict) or set(v) != {"days", "start", "end"}
            or not isinstance(v["days"], list)
            or not all(isinstance(d, int) and d in VALID_DAYS for d in v["days"])
            or not isinstance(v["start"], str) or not isinstance(v["end"], str)):
        raise ValueError('schedule must be {"days": [1-7], "start": "HH:MM", "end": "HH:MM"}')
    for t in (v["start"], v["end"]):
        parts = t.split(":")
        if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2 \
                or not parts[0].isdigit() or not parts[1].isdigit() \
                or not (0 <= int(parts[0]) <= 23) or not (0 <= int(parts[1]) <= 59):
            raise ValueError('schedule must be {"days": [1-7], "start": "HH:MM", "end": "HH:MM"}')
    return v


class ZoneIn(BaseModel):
    camera_id: int
    name: str
    type: str
    direction: str | None = None
    polygon: list
    schedule: dict | None = None
    severity: str = "warning"
    rate_limit_min: int = 5
    loiter_seconds: int = Field(default=0, ge=0)
    dwell_seconds: int = Field(default=0, ge=0)
    trigger_seconds: int = Field(default=0, ge=0)
    behaviors: list = Field(default_factory=list)
    speed_limit_mps: float = Field(default=0, ge=0)
    snapshot: bool = True
    clip: bool = True
    telegram: bool = False
    active: bool = True

    _validate_polygon = field_validator("polygon")(_validate_polygon)
    _validate_schedule = field_validator("schedule")(_validate_schedule)
    _validate_behaviors = field_validator("behaviors")(_validate_behaviors)

    @field_validator("type")
    @classmethod
    def type_valid(cls, v: str) -> str:
        if v not in VALID_TYPES:
            raise ValueError(f"type must be one of {sorted(VALID_TYPES)}")
        return v

    @field_validator("direction")
    @classmethod
    def direction_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_DIRECTIONS:
            raise ValueError(f"direction must be one of {sorted(VALID_DIRECTIONS)}")
        return v

    @model_validator(mode="after")
    def direction_iff_absensi(self):
        if self.type in ("absensi", "attendance") and self.direction is None:
            raise ValueError("direction is required when type is absensi")
        return self


class ZonePatch(BaseModel):
    camera_id: int | None = None
    name: str | None = None
    type: str | None = None
    direction: str | None = None
    polygon: list | None = None
    schedule: dict | None = None
    severity: str | None = None
    rate_limit_min: int | None = None
    loiter_seconds: int | None = Field(default=None, ge=0)
    dwell_seconds: int | None = Field(default=None, ge=0)
    trigger_seconds: int | None = Field(default=None, ge=0)
    behaviors: list | None = None
    speed_limit_mps: float | None = Field(default=None, ge=0)
    snapshot: bool | None = None
    clip: bool | None = None
    telegram: bool | None = None
    active: bool | None = None

    _validate_polygon = field_validator("polygon")(_validate_polygon)
    _validate_schedule = field_validator("schedule")(_validate_schedule)
    _validate_behaviors = field_validator("behaviors")(_validate_behaviors)

    @field_validator("type")
    @classmethod
    def type_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_TYPES:
            raise ValueError(f"type must be one of {sorted(VALID_TYPES)}")
        return v

    @field_validator("direction")
    @classmethod
    def direction_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_DIRECTIONS:
            raise ValueError(f"direction must be one of {sorted(VALID_DIRECTIONS)}")
        return v


class ZoneOut(BaseModel):
    id: int
    camera_id: int
    name: str
    type: str
    direction: str | None
    polygon: list
    schedule: dict | None
    severity: str
    rate_limit_min: int
    loiter_seconds: int
    dwell_seconds: int
    trigger_seconds: int
    behaviors: list
    speed_limit_mps: float
    snapshot: bool
    clip: bool
    telegram: bool
    active: bool
    camera_name: str | None = None
    model_config = {"from_attributes": True}
