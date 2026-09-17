from pydantic import BaseModel, Field


class LocationGroupOut(BaseModel):
    id: int
    name: str
    sort_order: int
    enabled: bool

    model_config = {"from_attributes": True}


class LocationGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    sort_order: int = 0
    enabled: bool = True


class LocationGroupPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    sort_order: int | None = None
    enabled: bool | None = None
