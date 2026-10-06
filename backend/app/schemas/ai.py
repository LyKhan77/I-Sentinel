"""Public AI status, bounded question input, and audit output contracts."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AiStatusOut(BaseModel):
    enabled: bool
    presets: dict[str, list[str]]
    caption_prompts: dict[str, str]


class HistoryTurn(BaseModel):
    q: str = Field(max_length=2000)
    a: str = Field(max_length=2000)


class AskIn(BaseModel):
    question: str | None = Field(default=None, max_length=500)
    preset: str | None = None
    history: list[HistoryTurn] = Field(default_factory=list, max_length=6)


class AskOut(BaseModel):
    answer: str
    frames_used: int
    cached: bool
    latency_ms: int
    model: str


class EventAiOut(BaseModel):
    id: int
    kind: Literal["caption", "ask"]
    preset: str | None
    question: str | None
    answer: str | None
    status: Literal["pending", "ok", "failed"]
    error: str | None
    model: str | None
    channel: str
    actor: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class EventAiListOut(BaseModel):
    caption: EventAiOut | None
    history: list[EventAiOut]
