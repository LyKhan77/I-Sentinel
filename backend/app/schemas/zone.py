from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.zone_delivery import DELIVERIES, DELIVERY_KINDS, UNKNOWN_DELIVERIES

VALID_TYPES = {"free", "restricted", "absensi", "behavior", "attendance"}
VALID_BEHAVIOR_KINDS = {"intrusion", "loitering", "running", "attendance", "idle_zone", "crowd"}
VALID_DIRECTIONS = {"entry", "exit"}
VALID_DAYS = set(range(1, 8))
BREAKS_MAX = 5  # batas istirahat per zona (UI satu baris; data siap multi-baris)


def _is_hhmm(t: str) -> bool:
    """HH:MM dengan jam 00-23 dan menit 00-59 (aturan sama untuk jam kerja dan istirahat)."""
    parts = t.split(":")
    return (len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) == 2
            and parts[0].isdigit() and parts[1].isdigit()
            and 0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59)


def _validate_breaks(breaks: object) -> None:
    """breaks = [{"start", "end"}], maks BREAKS_MAX, setengah terbuka via bandingan string HH:MM."""
    if not isinstance(breaks, list) or len(breaks) > BREAKS_MAX:
        raise ValueError(f"breaks must be a list of at most {BREAKS_MAX} items")
    for b in breaks:
        if not isinstance(b, dict) or set(b) != {"start", "end"}:
            raise ValueError('each break must be exactly {"start": "HH:MM", "end": "HH:MM"}')
        if not (isinstance(b["start"], str) and isinstance(b["end"], str)
                and _is_hhmm(b["start"]) and _is_hhmm(b["end"])):
            raise ValueError("break times must be HH:MM (00:00-23:59)")
        if not b["start"] < b["end"]:
            raise ValueError("break must satisfy start < end")


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
        for flag in ("snapshot", "clip", "telegram", "telegram_unknown", "record", "face_id"):
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
        # Tujuan event per behavior (Plan B): `delivery` untuk semua kind deteksi (termasuk
        # absensi, keputusan 2026-10-12); kunci uji (`test_until`/`revert_to`) hanya bermakna
        # saat `delivery == "test"` — sisanya dibuang supaya menyimpan "Inbox + Telegram"/
        # "Hanya Inbox" tidak menyisakan uji menggantung.
        delivery = b.get("delivery")
        if delivery is not None:
            if b.get("kind") not in DELIVERY_KINDS:
                raise ValueError(f"delivery is only valid for {sorted(DELIVERY_KINDS)} behaviors")
            if delivery not in DELIVERIES:
                raise ValueError(f"delivery must be one of {sorted(DELIVERIES)}")
        if "test_until" in b and not isinstance(b["test_until"], str):
            raise ValueError("test_until must be an ISO-8601 string")
        if b.get("revert_to") is not None and b.get("revert_to") not in ("all", "inbox"):
            raise ValueError("revert_to must be one of ['all', 'inbox']")
        # Tujuan wajah tidak dikenal (keputusan 2026-10-12): kunci khusus behavior absensi;
        # zona lama tanpa kunci tetap dibaca dari `telegram_unknown` (lihat `unknown_delivery`).
        unknown = b.get("unknown_delivery")
        if unknown is not None:
            if b.get("kind") != "attendance":
                raise ValueError("unknown_delivery is only valid for ['attendance'] behaviors")
            if unknown not in UNKNOWN_DELIVERIES:
                raise ValueError(f"unknown_delivery must be one of {sorted(UNKNOWN_DELIVERIES)}")
        if delivery != "test":
            b.pop("test_until", None)
            b.pop("revert_to", None)
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
    err = 'schedule must be {"days": [1-7], "start": "HH:MM", "end": "HH:MM"} or {"shift_id": N}'
    if not isinstance(v, dict):
        raise ValueError(err)
    keys = set(v)
    if keys in ({"shift_id"}, {"shift_id", "breaks"}):
        sid = v["shift_id"]
        if not isinstance(sid, int) or isinstance(sid, bool) or sid < 1:
            raise ValueError("schedule.shift_id must be a positive int")
    elif keys in ({"days", "start", "end"}, {"days", "start", "end", "breaks"}):
        if (not isinstance(v["days"], list)
                or not all(isinstance(d, int) and d in VALID_DAYS for d in v["days"])
                or not isinstance(v["start"], str) or not isinstance(v["end"], str)):
            raise ValueError(err)
        for t in (v["start"], v["end"]):
            if not _is_hhmm(t):
                raise ValueError(err)
    else:
        raise ValueError(err)
    if "breaks" in v:
        _validate_breaks(v["breaks"])
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

    @field_validator("ai_caption")
    @classmethod
    def _ai_caption_not_null(cls, v):
        """Kolom NOT NULL: null eksplisit harus 422, bukan IntegrityError saat commit."""
        if v is None:
            raise ValueError("ai_caption cannot be null")
        return v

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
    camera_name: str | None = None
    model_config = {"from_attributes": True}
