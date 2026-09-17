import re

from pydantic import BaseModel, Field, field_validator


_SECRET_REF = re.compile(r"^env:[A-Z][A-Z0-9_]*$")


def validate_secret_ref(value: str) -> str:
    value = value.strip()
    if not _SECRET_REF.fullmatch(value):
        raise ValueError("secret_ref must use env:NAME")
    return value


class CredentialProfileOut(BaseModel):
    id: int
    name: str
    username: str
    secret_ref: str
    enabled: bool

    model_config = {"from_attributes": True}


class CredentialProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    username: str = Field(default="", max_length=128)
    secret_ref: str = Field(min_length=6, max_length=128)
    enabled: bool = True

    _validate_secret_ref = field_validator("secret_ref")(validate_secret_ref)


class CredentialProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    username: str | None = Field(default=None, max_length=128)
    secret_ref: str | None = Field(default=None, min_length=6, max_length=128)
    enabled: bool | None = None

    _validate_secret_ref = field_validator("secret_ref")(validate_secret_ref)
