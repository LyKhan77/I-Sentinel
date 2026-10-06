"""Authenticated synchronous endpoints for advisory event AI features."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.models import Event, EventAi
from app.schemas.ai import AiStatusOut, AskIn, AskOut, EventAiListOut
from app.services import ai_prompts, ask_ai

router = APIRouter()
EventId = Annotated[int, Path(ge=1, le=2_147_483_647)]


@router.get("/api/v1/ai/status", response_model=AiStatusOut)
def status(user=Depends(get_current_user)):
    """Expose availability and public instructions, never provider configuration."""
    return {"enabled": settings.llm_enabled,
            "presets": {kind: ai_prompts.preset_keys(kind) for kind in sorted(ai_prompts.AI_TYPES)},
            "caption_prompts": ai_prompts.CAPTION_PROMPTS}


@router.get("/api/v1/events/{event_id}/ai", response_model=EventAiListOut)
def event_ai(event_id: EventId, user=Depends(get_current_user), db=Depends(get_db)):
    """Return one caption and at most twenty newest question attempts."""
    if db.get(Event, event_id) is None:
        raise HTTPException(404, "event_not_found")
    caption = db.query(EventAi).filter_by(event_id=event_id, kind="caption").order_by(EventAi.id.desc()).first()
    history = db.query(EventAi).filter_by(event_id=event_id, kind="ask").order_by(EventAi.created_at.desc(), EventAi.id.desc()).limit(20).all()
    return {"caption": caption, "history": history}


@router.post("/api/v1/events/{event_id}/ask", response_model=AskOut)
def ask_event(event_id: EventId, body: AskIn, user=Depends(get_current_user), db=Depends(get_db)):
    """Delegate all mutation and inference to the question service; viewers may ask."""
    ev = db.get(Event, event_id)
    if ev is None:
        raise HTTPException(404, "event_not_found")
    try:
        return ask_ai.ask(db, ev, user_id=user.id, question=body.question, preset=body.preset,
                          history=[(turn.q, turn.a) for turn in body.history])
    except ask_ai.AskError as exc:
        raise HTTPException(exc.status, detail=exc.code) from None
