import re

from pydantic import BaseModel, Field, field_validator

TIME_RE = re.compile(r"^\d{2}:\d{2}$")
VALID_DAYS = set(range(1, 8))


def _validate_time(v: str) -> str:
    if not isinstance(v, str) or not TIME_RE.match(v):
        raise ValueError("time must be HH:MM")
    hh, mm = int(v[:2]), int(v[3:])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("time must be HH:MM")
    return v


def _validate_workdays(v: list) -> list:
    if not isinstance(v, list) or not v:
        raise ValueError("workdays must be a non-empty list")
    if not all(isinstance(d, int) and not isinstance(d, bool) and d in VALID_DAYS for d in v):
        raise ValueError("workdays must be a subset of 1..7 (ISO weekdays)")
    return v


class ShiftIn(BaseModel):
    name: str
    start_time: str
    end_time: str
    tolerance_min: int = Field(default=15, ge=0, le=120)
    workdays: list = Field(default_factory=lambda: [1, 2, 3, 4, 5])

    _v_start = field_validator("start_time")(_validate_time)
    _v_end = field_validator("end_time")(_validate_time)
    _v_days = field_validator("workdays")(_validate_workdays)


class ShiftPatch(BaseModel):
    name: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    tolerance_min: int | None = Field(default=None, ge=0, le=120)
    workdays: list | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def time_valid(cls, v: str | None) -> str | None:
        return None if v is None else _validate_time(v)

    @field_validator("workdays")
    @classmethod
    def workdays_valid(cls, v: list | None) -> list | None:
        return None if v is None else _validate_workdays(v)


class ShiftOut(BaseModel):
    id: int
    name: str
    start_time: str
    end_time: str
    tolerance_min: int
    workdays: list
    model_config = {"from_attributes": True}


class EmployeeIn(BaseModel):
    name: str
    employee_code: str
    shift_id: int | None = None


class EmployeePatch(BaseModel):
    name: str | None = None
    employee_code: str | None = None
    shift_id: int | None = None
    active: bool | None = None


class EmployeeOut(BaseModel):
    id: int
    name: str
    employee_code: str
    active: bool
    shift_id: int | None
    shift_name: str | None = None
    model_config = {"from_attributes": True}
