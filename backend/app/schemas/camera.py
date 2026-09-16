from pydantic import BaseModel, Field

class NodeOut(BaseModel):
    id: int
    name: str
    type: str
    status: str
    model_config = {"from_attributes": True}

class CameraOut(BaseModel):
    id: int
    name: str
    location: str | None
    host: str
    rtsp_main: str | None
    rtsp_sub: str | None
    node_id: int | None
    enabled: bool
    status: str
    probe_main: dict | None
    probe_sub: dict | None
    meters_per_pixel: float | None
    model_config = {"from_attributes": True}

class CameraIn(BaseModel):
    name: str
    location: str | None = None
    host: str
    rtsp_main: str | None = None
    rtsp_sub: str | None = None
    node_id: int | None = None
    probe_main: dict | None = None
    probe_sub: dict | None = None
    status: str | None = None

class CameraPatch(BaseModel):
    name: str | None = None
    location: str | None = None
    host: str | None = None
    rtsp_main: str | None = None
    rtsp_sub: str | None = None
    node_id: int | None = None
    enabled: bool | None = None
    probe_main: dict | None = None
    probe_sub: dict | None = None
    status: str | None = None
    meters_per_pixel: float | None = Field(default=None, gt=0)

class CameraImportEntry(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    location: str | None = Field(default=None, max_length=128)
    host: str = Field(min_length=1, max_length=64)
    rtsp_main: str = Field(min_length=1, max_length=255)
    rtsp_sub: str | None = Field(default=None, max_length=255)

class CameraImportIn(BaseModel):
    entries: list[CameraImportEntry] = Field(min_length=1, max_length=100)
