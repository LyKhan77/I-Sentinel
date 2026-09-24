import re

from pydantic import BaseModel, Field, field_validator, model_validator


_SECRET_REF = re.compile(r"^env:[A-Z][A-Z0-9_]*$")


def validate_secret_ref(value: str | None) -> str | None:
    """Input klien hanya boleh env:NAMA; referensi store: dibuat server."""
    if value is None:
        return None
    value = value.strip()
    if not _SECRET_REF.fullmatch(value):
        raise ValueError("secret_ref must use env:NAME")
    return value


class CredentialProfileOut(BaseModel):
    id: int
    name: str
    username: str
    secret_ref: str  # referensi (env:/store:), bukan rahasia
    enabled: bool

    model_config = {"from_attributes": True}


class CredentialProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    username: str = Field(default="", max_length=128)
    secret_ref: str | None = Field(default=None, min_length=6, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=256)  # write-only
    enabled: bool = True

    _validate_secret_ref = field_validator("secret_ref")(validate_secret_ref)

    @model_validator(mode="after")
    def _exactly_one_secret(self):
        if (self.secret_ref is None) == (self.password is None):
            raise ValueError("provide exactly one of secret_ref or password")
        return self


class CredentialProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    username: str | None = Field(default=None, max_length=128)
    secret_ref: str | None = Field(default=None, min_length=6, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=256)  # write-only
    enabled: bool | None = None

    _validate_secret_ref = field_validator("secret_ref")(validate_secret_ref)

    @model_validator(mode="after")
    def _not_both_secrets(self):
        if self.secret_ref is not None and self.password is not None:
            raise ValueError("provide secret_ref or password, not both")
        return self
