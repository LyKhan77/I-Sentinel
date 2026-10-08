"""Hasil identitas wajah intrusion critical: cocok ketat, simpan payload.face, fallback unverified.

Embedding di-pop consumer sebelum fungsi ini — tidak pernah masuk DB atau WS.
Spec: docs/superpowers/specs/2026-10-08-intrusion-face-id-design.md §5.3.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import Alert, Employee, Event, Zone
from app.schemas.intrusion_face import FaceResultIn
from app.services import alert_ai, face
from app.ws.hub import hub

logger = logging.getLogger(__name__)

FACE_TOPIC = "isentinel/events/face"
UNVERIFIED_AFTER_S = 20.0  # > jendela node (8 dtk) + unggah crop (<= ~6 dtk) + antrean MQTT
# ponytail: timer unverified hilang bila API restart (alert tetap tanpa baris identitas);
# upgrade ke sweeper periodik bila kasus itu terlihat sering di produksi.


def wants_identity(db: Session, ev: Event) -> bool:
    """Saklar zona: intrusion critical dengan face_id: true pada behavior zona."""
    if ev.type != "intrusion" or ev.severity != "critical":
        return False
    zone = db.get(Zone, ev.zone_id) if ev.zone_id else None  # tanpa FK: lookup eksplisit
    if zone is None or zone.severity != "critical":
        return False
    return zone.behavior_flag("intrusion", "face_id", default=False)


def _identify_with_name(db: Session, vector: list[float], quality: float | None) -> dict:
    """match_strict + nama karyawan; pemetaan status recognized|unknown|not_visible."""
    if quality is not None and quality < face.settings.face_min_quality:
        f = {"status": "not_visible", "reason": "low_quality"}
        return f
    res = face.match_strict(vector, quality=None)
    if res.reason == "matched":
        name = None
        if res.employee_id is not None:
            emp = db.get(Employee, res.employee_id)
            name = emp.name if emp is not None else None
        out = {"status": "recognized", "reason": "matched", "employee_id": res.employee_id,
               "name": name or f"karyawan #{res.employee_id}", "score": res.score,
               "margin": res.margin}
    elif res.reason in ("no_match", "ambiguous"):
        out = {"status": "unknown", "reason": res.reason, "score": res.score,
               "margin": res.margin}
    else:  # low_quality di match_strict tanpa quality param tidak terjadi; jaga konsistensi
        out = {"status": "not_visible", "reason": res.reason}
    return {k: v for k, v in out.items() if v is not None}


_RANK = {"unverified": 0, "not_visible": 1, "unknown": 2, "recognized": 3}


def _improves(existing: dict | None, new: dict) -> bool:
    """Pembaruan progresif tidak pernah menurunkan hasil: status lebih tinggi, atau status sama dengan skor lebih tinggi."""
    if not isinstance(existing, dict) or existing.get("status") not in _RANK:
        return True
    old_rank, new_rank = _RANK[existing["status"]], _RANK.get(new["status"], 0)
    if new_rank != old_rank:
        return new_rank > old_rank
    return (new.get("score") or 0.0) > (existing.get("score") or 0.0) + 1e-6


def _caption_changes(existing: dict | None, new: dict) -> bool:
    """Teks caption berubah hanya bila status atau karyawan berbeda (skor saja tidak mengedit Telegram)."""
    if not isinstance(existing, dict):
        return True
    return existing.get("status") != new.get("status") or existing.get("employee_id") != new.get("employee_id")


def _safe_crop_path(path) -> bool:
    return (isinstance(path, str) and path.startswith("crops/")
            and ".." not in path and not path.startswith("/"))


def handle_face_result(db: Session, data: dict) -> None:
    """Terapkan satu pesan hasil wajah. Tidak pernah melempar (consumer MQTT satu thread)."""
    try:
        vector = data.pop("embedding", None)  # biometrik tidak pernah masuk DB / WS
        try:
            msg = FaceResultIn.model_validate(data)
        except Exception:
            logger.warning("invalid face result payload")
            return
        ev = db.query(Event).filter_by(event_id=msg.event_id).first()
        if ev is None:
            logger.warning("face result for unknown event %r", msg.event_id)
            return
        stats = msg.stats or {}
        rejects = stats.get("rejects") or {}
        if vector is not None:
            face_dict = _identify_with_name(db, vector, msg.quality)
        elif stats.get("faces", 0) == 0:
            face_dict = {"status": "not_visible", "reason": "no_face"}
        else:
            reason = max(rejects, key=rejects.get) if rejects else "no_face"
            face_dict = {"status": "not_visible", "reason": reason}
        existing = (ev.payload or {}).get("face")
        if not _improves(existing, face_dict):
            return  # duplikat atau hasil yang tidak lebih baik: abaikan
        changes_caption = _caption_changes(existing, face_dict)
        payload = {**(ev.payload or {}), "face": face_dict}
        if _safe_crop_path(msg.crop_path):
            payload["crop_path"] = msg.crop_path  # crop mengikuti hasil terbaik
        ev.payload = payload  # dict baru → perubahan JSON terdeteksi
        if changes_caption:
            db.query(Alert).filter(Alert.event_id == ev.id).update(
                {"face_synced": False}, synchronize_session=False)
        db.commit()
        if not changes_caption:
            return  # skor/crop lebih baik, teks caption sama: tanpa siaran dan tanpa edit kedua
        try:
            import asyncio
            asyncio.run(hub.broadcast({"kind": "face", "event_id": ev.id,
                                       "status": face_dict["status"]}))
        except Exception:
            logger.warning("face broadcast failed for event %s", ev.id)
        try:
            alert_ai.sync_face_caption(db, ev.id)
        except Exception:
            logger.exception("face caption sync failed for event %s", ev.id)
    except Exception:
        db.rollback()
        logger.exception("face result handling failed")


def finalize_unverified(event_id: str, *, session_factory=None) -> bool:
    """Fallback: tandai `unverified` bila pesan susulan tidak pernah datang.

    Return True bila payload.face baru ditulis; False bila sudah ada hasil (atau event hilang).
    """
    db = (session_factory or SessionLocal)()
    try:
        ev = db.query(Event).filter_by(event_id=event_id).first()
        if ev is None or (ev.payload or {}).get("face"):
            return False
        ev.payload = {**(ev.payload or {}), "face": {"status": "unverified"}}
        db.query(Alert).filter(Alert.event_id == ev.id).update(
            {"face_synced": False}, synchronize_session=False)
        db.commit()
        try:
            import asyncio
            asyncio.run(hub.broadcast({"kind": "face", "event_id": ev.id,
                                       "status": "unverified"}))
        except Exception:
            logger.warning("face broadcast failed for event %s", ev.id)
        try:
            alert_ai.sync_face_caption(db, ev.id)
        except Exception:
            logger.exception("face caption sync failed for event %s", ev.id)
        return True
    except Exception:
        db.rollback()
        logger.exception("finalize_unverified failed for event %s", event_id)
        return False
    finally:
        db.close()


def schedule_unverified(event_id: str, *, delay: float = UNVERIFIED_AFTER_S,
                        session_factory=None) -> threading.Timer:
    """Jadwalkan fallback `unverified` di thread daemon dengan sesi DB sendiri."""
    timer = threading.Timer(delay, finalize_unverified, args=(event_id,),
                            kwargs={"session_factory": session_factory})
    timer.daemon = True
    timer.start()
    return timer
