"""Stateless event questions with preset caching, bounded admission, and audit rows."""
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
import threading
import time

from app.core.config import settings
from app.models import Camera, Event, EventAi, Zone
from app.services import ai_media, ai_prompts, llm_client


class AskError(Exception):
    """Stable HTTP status and public code without transport or credential details."""

    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AskResult:
    """Answer accounting, including whether a stored preset supplied the result."""

    answer: str
    frames_used: int
    cached: bool
    latency_ms: int
    model: str


_limits: dict[int, deque[float]] = {}
_limit_lock = threading.Lock()


def reset_rate_limits() -> None:
    """Clear in-process sliding windows, chiefly for isolated service tests."""
    with _limit_lock:
        _limits.clear()


def _admit(user_id: int) -> None:
    """Consume one uncached question attempt in a locked 60-second sliding window."""
    now = time.monotonic()
    with _limit_lock:
        window = _limits.setdefault(user_id, deque())
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= settings.llm_ask_rate_per_min:
            raise AskError(429, "rate_limited")
        window.append(now)


def ask(db, ev: Event, *, user_id: int, question: str | None = None, preset: str | None = None,
        history: Sequence[tuple[str, str]] = (), channel: str = "web") -> AskResult:
    """Validate in contract order, reuse preset results, or request snapshot plus clip.

    History is supplied by the client and bounded independently of persisted audit
    history. Media failures never expose paths; non-temporal requests fall back to
    snapshot-only answers. Only actual LLM attempts receive an audit row.
    """
    if not settings.llm_enabled:
        raise AskError(503, "disabled")
    if ev.type not in ai_prompts.AI_TYPES:
        raise AskError(422, "unsupported_type")
    if (question is None) == (preset is None):
        raise AskError(422, "invalid_request")
    if question is not None and (len(question) > 500 or not question.strip()):
        raise AskError(422, "invalid_request")
    if preset is not None and preset not in ai_prompts.preset_keys(ev.type):
        raise AskError(422, "invalid_preset")
    if len(history) > 6 or any(len(q) > 2000 or len(a) > 2000 for q, a in history):
        raise AskError(422, "invalid_request")
    if ev.media_expired:
        raise AskError(409, "media_expired")
    if not ev.snapshot_path:
        raise AskError(409, "snapshot_unavailable")
    if preset in ai_prompts.TEMPORAL_PRESETS and not ev.clip_path:
        raise AskError(409, "clip_unavailable")
    if preset is not None:
        cached = db.query(EventAi).filter_by(event_id=ev.id, kind="ask", preset=preset, status="ok").order_by(EventAi.id.desc()).first()
        # jawaban tanpa frame hanya valid bila event memang tanpa klip; selain itu ulangi (klip bisa pulih)
        if cached is not None and (cached.frames_used or not ev.clip_path):
            return AskResult(cached.answer or "", cached.frames_used, True, cached.latency_ms or 0, cached.model or "")
    _admit(user_id)
    started = time.monotonic()
    frames = []
    if ev.clip_path:
        try:
            frames = ai_media.extract_keyframes(ev.clip_path, ai_media.keyframe_times(ai_media.clip_duration(ev.clip_path)))
        except ai_media.AiMediaError:
            frames = []
    if preset in ai_prompts.TEMPORAL_PRESETS and not frames:
        raise AskError(409, "clip_unavailable")
    try:
        snapshot = ai_media.snapshot_jpeg(ev.snapshot_path)
    except ai_media.AiMediaError:
        raise AskError(409, "snapshot_unavailable") from None
    camera = db.get(Camera, ev.camera_id) if ev.camera_id else None
    zone = db.get(Zone, ev.zone_id) if ev.zone_id else None
    prompt = ai_prompts.event_metadata(ev, camera.name if camera else None, zone.name if zone else None)
    if history:
        prompt += "\nRiwayat percakapan:\n" + "\n".join(f"Pertanyaan sebelumnya: {q}\nJawaban sebelumnya: {a}" for q, a in history)
    prompt += "\nPertanyaan: " + (ai_prompts.preset_question(preset) if preset is not None else question.strip())
    content = [llm_client.text_part(prompt), llm_client.image_part(snapshot)]
    for at, jpeg in frames:
        content.extend([llm_client.text_part(f"Frame pada detik {at:.2f}:"), llm_client.image_part(jpeg)])
    row = EventAi(event_id=ev.id, kind="ask", preset=preset,
                  question=llm_client.clean_error(question) if question is not None else None,
                  channel=channel, actor=f"user:{user_id}", frames_used=len(frames))
    try:
        with llm_client.slot():
            result = llm_client.chat([{"role": "system", "content": ai_prompts.SYSTEM_PROMPT}, {"role": "user", "content": content}],
                                     timeout=settings.llm_timeout_ask_s)
        row.status, row.answer, row.model = "ok", llm_client.clean_error(result.text), llm_client.clean_error(result.model)[:64]
    except llm_client.LlmBusy:
        raise AskError(503, "busy") from None
    except llm_client.LlmError as exc:
        row.status, row.error = "failed", llm_client.clean_error(str(exc))[:255]
    row.latency_ms = int((time.monotonic() - started) * 1000)
    db.add(row)
    db.commit()
    if row.status == "failed":
        raise AskError(502, "llm_error")
    return AskResult(row.answer, row.frames_used, False, row.latency_ms, row.model)
