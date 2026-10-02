from pydantic import BaseModel, Field, field_validator, model_validator

VALID_TYPES = {"free", "restricted", "absensi", "behavior", "attendance"}
VALID_BEHAVIOR_KINDS = {"intrusion", "loitering", "running", "attendance", "idle_zone", "crowd"}
VALID_DIRECTIONS = {"entry", "exit"}
VALID_DAYS = set(range(1, 8))


def _validate_behaviors(v: list | None) -> list | None:
    """behaviors = [{"kind", "trigger_seconds", [speed_limit_mps], [snapshot], [clip], [telegram]}]."""
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
        for flag in ("snapshot", "clip", "telegram"):
            if flag in b and not isinstance(b[flag], bool):
                raise ValueError(f"{flag} must be a boolean")
        # event = bukti visual: tanpa media event langsung jadi card kosong (dan terhapus retensi).
        # attendance tidak merekam clip → snapshot wajib. Flag absen = ikut zona (data lama).
        if b.get("kind") == "attendance" and b.get("snapshot") is False:
            raise ValueError("behavior attendance needs snapshot")
        if b.get("snapshot") is False and b.get("clip") is False:
            raise ValueError(f"behavior {b.get('kind')} needs snapshot or clip")
        min_count = b.get("min_count")
        if b.get("kind") == "crowd" and min_count is None:
            raise ValueError("crowd requires min_count")
        if min_count is not None and (not isinstance(min_count, int) or isinstance(min_count, bool) or min_count < 1):
            raise ValueError("min_count must be an int >= 1")
        reminder = b.get("reminder_minutes")
        if reminder is not None and (not isinstance(reminder, int) or isinstance(reminder, bool) or reminder < 0):
            raise ValueError("reminder_minutes must be an int >= 0")
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
    if isinstance(v, dict) and set(v) == {"shift_id"}:
        sid = v["shift_id"]
        if not isinstance(sid, int) or isinstance(sid, bool) or sid < 1:
            raise ValueError("schedule.shift_id must be a positive int")
        return v
    if (not isinstance(v, dict) or set(v) != {"days", "start", "end"}
            or not isinstance(v["days"], list)
            or not all(isinstance(d, int) and d in VALID_DAYS for d in v["days"])
            or not isinstance(v["start"], str) or not isinstance(v["end"], str)):
        raise ValueError('schedule must be {"days": [1-7], "start": "HH:MM", "end": "HH:MM"} or {"shift_id": N}')
    for t in (v["start"], v["end"]):
        parts = t.split(":")
        if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2 \
                or not parts[0].isdigit() or not parts[1].isdigit() \
                or not (0 <= int(parts[0]) <= 23) or not (0 <= int(parts[1]) <= 59):
            raise ValueError('schedule must be {"days": [1-7], "start": "HH:MM", "end": "HH:MM"}')
    return v


def _clean_ai_prompt(v: str | None) -> str | None:
    """Normalize the optional caption instruction before storing a zone."""
    if v is None:
        return None
    v = v.strip()
    if len(v) > 600:
        raise ValueError("ai_prompt must be at most 600 characters")
    return v or None


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
    ai_caption: bool = False
    ai_prompt: str | None = None
    _clean_ai_prompt = field_validator("ai_prompt")(_clean_ai_prompt)

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
    ai_caption: bool | None = None
    ai_prompt: str | None = None
    _clean_ai_prompt = field_validator("ai_prompt")(_clean_ai_prompt)

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
    ai_caption: bool
    ai_prompt: str | None
    _clean_ai_prompt = field_validator("ai_prompt")(_clean_ai_prompt)
    camera_name: str | None = None
    model_config = {"from_attributes": True}
