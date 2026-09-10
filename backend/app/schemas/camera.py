from pydantic import BaseModel

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
