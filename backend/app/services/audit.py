"""Jejak audit: tulis satu baris audit_log per aksi, dengan rantai hash anti-tamper.

Dipanggil eksplisit dari router/service pada titik mutasi (bukan listener ORM/middleware)
agar presisi, ringan, dan konteks request (actor, ip) selalu tersedia. Semua tulis terjadi
dalam sesi transaksi aksi yang sama — jejak audit komit/rollback atomik bersama aksi.

Rantai hash: setiap baris menyimpan hash dari (prev_hash + field kanonik), sehingga
menghapus/mengubah satu baris memecahkan rantai dan terdeteksi oleh verify().
Penulisan rantai diserialize lewat pg_advisory_xact_lock agar insert konkuren tidak
membuat fork; di SQLite (test) lock dilewati.

Kategori (auth|config|attendance) di-derive dari entitas action lewat _ENTITY_CATEGORY,
bukan prefix mentah — spec §4/§7.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)

GENESIS = "0" * 64
_LOCK_KEY = 770013  # kunci pg_advisory_xact_lock khusus rantai audit (konstanta stabil)
_SECRET_KEY_RE = re.compile(r"password|token|secret|credential|api_key", re.IGNORECASE)

# entitas (prefix action) → kategori spec: auth | config | attendance
_ENTITY_CATEGORY = {
    "auth": "auth",
    "attendance": "attendance",
    "employee": "attendance",
    "enrollment": "attendance",
    "shift": "attendance",
    "camera": "config",
    "stream_source": "config",
    "credential_profile": "config",
    "location_group": "config",
    "node": "config",
    "zone": "config",
    "detector_setting": "config",
    "ai_settings": "config",
    "storage_settings": "config",
    "storage": "config",
    "telegram": "config",
}


def _category_for(action: str) -> str:
    entity = action.split(".", 1)[0]
    return _ENTITY_CATEGORY.get(entity, entity)


def _canon_ts(ts: datetime) -> str:
    """Normalisasi timestamp agar deterministik lintas dialect (naive vs aware)."""
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")


def _canon_changes(changes: dict | None) -> str:
    if not changes:
        return ""
    return json.dumps(changes, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _chain_hash(prev: str, *, ts: datetime, category: str, action: str,
                actor_label: str | None, target_type: str | None, target_id: str | None,
                changes: dict | None, status: str) -> str:
    payload = "|".join([
        prev, _canon_ts(ts), category, action, actor_label or "",
        target_type or "", target_id or "", _canon_changes(changes), status,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sanitize(changes: dict | None) -> dict | None:
    """Nilai field bernama mirip rahasia diganti '***' (nama field tetap tampil)."""
    if not changes:
        return None
    return {k: ("***" if _SECRET_KEY_RE.search(k) else v) for k, v in changes.items()}


def record(
    db: Session, *, action: str, actor: User | None = None, actor_label: str | None = None,
    target: tuple[str, object, str] | None = None, changes: dict | None = None,
    status: str = "ok", ip: str | None = None, user_agent: str | None = None,
) -> AuditLog:
    """Tambah satu entri audit ke sesi (belum commit — caller yang commit).

    CREATE umumnya dipanggil dengan changes=None (nilai lengkap ada di entitasnya sendiri);
    UPDATE memakai changes={field: nilai_baru}; nilai lama tidak pernah disimpan.
    """
    category = _category_for(action)
    if actor is not None:
        actor_id = actor.id
        actor_label = actor_label or actor.username
    else:
        actor_id = None
    actor_label = actor_label or "system"
    target_type = target_id = target_label = None
    if target is not None:
        target_type, raw_id, target_label = target
        target_id = None if raw_id is None else str(raw_id)
    # batasi ke ukuran kolom: input tak-terpercaya (username login, user-agent) tidak
    # boleh membuat insert gagal di PostgreSQL (VARCHAR menolak overflow)
    actor_label = actor_label[:64]
    if target_id is not None:
        target_id = target_id[:64]
    if target_label is not None:
        target_label = target_label[:128]
    if ip is not None:
        ip = ip[:45]
    if user_agent is not None:
        user_agent = user_agent[:255]
    changes = _sanitize(json.loads(json.dumps(changes, ensure_ascii=False, default=str))
                        if changes else None)
    if action in {"auth.login_failed", "auth.lockout"}:
        status = "failed"
    ts = datetime.now(timezone.utc)
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    db.flush()  # include preceding records even when Session autoflush is disabled
    last = db.query(AuditLog.hash).order_by(AuditLog.id.desc()).first()
    prev_hash = last[0] if last else GENESIS
    row = AuditLog(
        ts=ts, category=category, action=action, actor_id=actor_id, actor_label=actor_label,
        target_type=target_type, target_id=target_id, target_label=target_label,
        changes=changes, ip=ip, user_agent=user_agent, status=status,
        prev_hash=prev_hash,
    )
    row.hash = _chain_hash(prev_hash, ts=ts, category=category, action=action,
                           actor_label=actor_label, target_type=target_type,
                           target_id=target_id, changes=changes, status=status)
    db.add(row)
    db.flush()
    return row


def verify(db: Session) -> dict:
    """Hitung ulang rantai dari baris tertua di window retensi (genesis window)."""
    rows = db.query(AuditLog).order_by(AuditLog.id).all()
    if not rows:
        return {"ok": True, "checked": 0, "first_break_id": None}
    prev = rows[0].prev_hash  # baris tertua di window: prev_hash-nya tidak diverifikasi
    checked = 0
    for r in rows:
        expect = _chain_hash(prev, ts=r.ts, category=r.category, action=r.action,
                             actor_label=r.actor_label, target_type=r.target_type,
                             target_id=r.target_id, changes=r.changes, status=r.status)
        if r.prev_hash != prev or r.hash != expect:
            return {"ok": False, "checked": checked, "first_break_id": r.id}
        prev = r.hash
        checked += 1
    return {"ok": True, "checked": checked, "first_break_id": None}
