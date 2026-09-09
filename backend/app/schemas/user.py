from pydantic import BaseModel, field_validator

class UserOut(BaseModel):
    id: int
    username: str
    role: str
    locale: str
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
    role: str = "viewer"
    locale: str = "id"

    @field_validator("password")
    @classmethod
    def pw_valid(cls, v: str) -> str:
        if not v: raise ValueError("password must not be empty")
        if len(v.encode()) > 72: raise ValueError("password too long (max 72 bytes, bcrypt limit)")
        return v
