import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
Role = Literal["admin", "viewer"]


def check_password(v: str) -> str:
    if len(v) < 8: raise ValueError("password must be at least 8 characters")
    if len(v.encode()) > 72: raise ValueError("password too long (max 72 bytes, bcrypt limit)")
    return v

class UserOut(BaseModel):
    id: int
    username: str
    role: str
    locale: str
    is_active: bool = True
    created_at: datetime | None = None
    last_login_at: datetime | None = None
    model_config = {"from_attributes": True}

class LoginIn(BaseModel):
    username: str
    password: str

    @field_validator("password")
    @classmethod
    def pw_not_empty(cls, v: str) -> str:
        if not v: raise ValueError("password must not be empty")
        return v

class UserIn(BaseModel):
    username: str
    password: str
    role: Role = "viewer"
    locale: str = "id"

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        if not USERNAME_RE.fullmatch(v): raise ValueError("username must be 3-64 of A-Z a-z 0-9 . _ -")
        return v

    @field_validator("password")
    @classmethod
    def pw_valid(cls, v: str) -> str:
        return check_password(v)

class UserPatch(BaseModel):
    model_config = {"extra": "forbid"}
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = None
    locale: str | None = None

    @field_validator("password")
    @classmethod
    def pw_valid(cls, v: str | None) -> str | None:
        return None if v is None else check_password(v)

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def pw_valid(cls, v: str) -> str:
        return check_password(v)
