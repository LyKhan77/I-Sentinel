"""Klien bot Telegram (stdlib urllib) + setelan notifikasi.

Token di secret_store (fallback env TELEGRAM_BOT_TOKEN), grup terpilih = satu baris aktif
telegram_chat, URL aplikasi di setting "telegram". Token tidak pernah masuk log/pesan error.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import timezone

from app.core.config import settings
from app.models.setting import Setting
from app.models.telegram_chat import TelegramChat
from app.services import secret_store

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
TOKEN_KEY = "telegram_bot_token"
SETTING_KEY = "telegram"
TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")
CAPTION_MAX = 1024  # batas caption sendPhoto
ERROR_MAX = 250  # maksimum panjang pesan TelegramError (kolom alert.error String(255))
CHAT_LABEL_MAX = 64  # maksimum TelegramChat.label (kolom String(64))
TEST_TEXT = "✅ Tes I-Sentinel — bot terhubung ke grup ini."
TYPE_TITLE = {"intrusion": "INTRUSION", "loitering": "LOITERING", "running": "RUNNING",
              "idle_zone": "IDLE ZONE", "crowd": "CROWD"}
FIELD_MAX = 120  # nilai per baris dibatasi sebelum escape → caption selalu < CAPTION_MAX

_urlopen = urllib.request.urlopen  # hook tes


class TelegramError(Exception):
    """Panggilan Telegram gagal; pesan sudah bebas token dan ≤ 250 karakter."""


def get_token() -> str:
    """Token tersimpan di secret_store; fallback ke env TELEGRAM_BOT_TOKEN."""
    try:
        stored = secret_store.get(TOKEN_KEY)
    except secret_store.SecretStoreError:
        stored = None
    return stored or settings.telegram_bot_token


def set_token(token: str) -> None:
    """Simpan token ke secret_store. Validasi format/getMe terjadi di API (bukan di sini)."""
    secret_store.put(TOKEN_KEY, token)


def active_chat(db) -> TelegramChat | None:
    """Satu-satunya grup aktif (id terkecil bila ada lebih dari satu)."""
    return db.query(TelegramChat).filter_by(active=True).order_by(TelegramChat.id).first()


def set_chat(db, chat_id: str, title: str) -> None:
    """Satu grup aktif: nonaktifkan yang lain, upsert yang dipilih (tanpa commit)."""
    for row in db.query(TelegramChat).filter_by(active=True):
        row.active = False
    row = db.query(TelegramChat).filter_by(chat_id=chat_id).first()
    if row is None:
        row = TelegramChat(chat_id=chat_id, label=title[:CHAT_LABEL_MAX])
        db.add(row)
    row.label = title[:CHAT_LABEL_MAX]
    row.active = True


def app_url(db) -> str | None:
    """URL aplikasi di setting "telegram" (untuk tautan event di caption); None bila belum diatur."""
    row = db.get(Setting, SETTING_KEY)
    return (row.value or {}).get("app_url") if row is not None else None


def set_app_url(db, url: str | None) -> None:
    """Simpan URL aplikasi (slash akhir dibuang, string kosong → None). Tidak commit."""
    row = db.get(Setting, SETTING_KEY)
    value = dict(row.value or {}) if row is not None else {}
    stripped = url.strip().rstrip("/") if url and url.strip() else None
    value["app_url"] = stripped or None
    if row is None:
        db.add(Setting(key=SETTING_KEY, value=value))
    else:
        row.value = value


def _clean(message: str, token: str) -> str:
    """Ganti token dengan *** SEBELUM dipotong, supaya potongan token tidak tertinggal."""
    return (message.replace(token, "***") if token else message)[:ERROR_MAX]


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """Rakit body multipart/form-data; boundary acak per panggilan."""
    boundary = uuid.uuid4().hex
    out = []
    for name, value in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (filename, content, ctype) in files.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                   f"Content-Type: {ctype}\r\n\r\n".encode())
        out.append(content)
        out.append(b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def _call(token: str, method: str, data: dict | None = None, files: dict | None = None, timeout: float = 15):
    """Panggil satu method Bot API. Hanya TelegramError yang bisa naik (pesan bebas token)."""
    if files:
        body, ctype = _multipart(data or {}, files)
    else:
        body, ctype = json.dumps(data or {}).encode(), "application/json"
    try:
        req = urllib.request.Request(API.format(token=token, method=method), data=body,
                                     headers={"Content-Type": ctype})
        with _urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:  # Telegram mengirim JSON di 4xx
        try:
            payload = json.loads(exc.read() or b"{}")
        except (ValueError, OSError):  # body bukan JSON / stream tak terbaca → pakai kode HTTP
            raise TelegramError(f"HTTP {exc.code}") from None
    except Exception as exc:  # jaringan / timeout / JSON rusak
        raise TelegramError(_clean(str(exc), token)) from None
    if not isinstance(payload, dict) or not payload.get("ok"):
        desc = payload.get("description") if isinstance(payload, dict) else None
        raise TelegramError(_clean(str(desc or "telegram error"), token))
    return payload.get("result")


def get_me(token: str) -> dict:
    """Info bot (getMe) — dipakai untuk validasi token; raise TelegramError bila ditolak."""
    return _call(token, "getMe") or {}


def get_updates(token: str) -> list[dict]:
    """Daftar grup unik {chat_id, title, type} dari pesan/keanggotaan bot (private diabaikan)."""
    seen: dict[str, dict] = {}
    for upd in _call(token, "getUpdates", {"allowed_updates": ["message", "my_chat_member"]}) or []:
        for key in ("message", "my_chat_member"):
            chat = (upd.get(key) or {}).get("chat") or {}
            if chat.get("type") in ("group", "supergroup") and chat.get("id") is not None:
                cid = str(chat["id"])
                seen[cid] = {"chat_id": cid, "title": chat.get("title") or cid, "type": chat["type"]}
    return list(seen.values())


class Delivery(tuple):
    """Two-value delivery result, compatible with existing tuple callers."""

    message_id: int | None
    photo: bool

    def __new__(cls, status: str, error: str | None, message_id: int | None = None,
                photo: bool = False) -> "Delivery":
        result = tuple.__new__(cls, (status, error))
        result.message_id, result.photo = message_id, photo
        return result


def deliver(token: str, chat_id: str, caption: str, photo: bytes | None = None, *,
            retries: int = 3, sleep=time.sleep) -> Delivery:
    """Kirim foto (sendPhoto multipart) atau teks (sendMessage); retry backoff 2^n di antaranya.

    Mengembalikan ("sent", None) atau ("failed", pesan Bebas-token). Tidak pernah raise.
    """
    last = None
    for attempt in range(retries):
        try:
            if photo:
                result = _call(token, "sendPhoto", {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                               {"photo": ("snapshot.jpg", photo, "image/jpeg")})
            else:
                result = _call(token, "sendMessage", {"chat_id": chat_id, "text": caption, "parse_mode": "HTML"})
            message_id = result.get("message_id") if isinstance(result, dict) else None
            return Delivery("sent", None, message_id, bool(photo))
        except TelegramError as exc:
            last = str(exc)
        if attempt < retries - 1:
            sleep(2 ** attempt)
    return Delivery("failed", last)


def edit_caption(token: str, chat_id: str, message_id: int, caption: str, *,
                 retries: int = 2, sleep=time.sleep) -> tuple[str, str | None]:
    """Edit a photo caption; retries count additional attempts, never raise.

    Telegram rejects identical captions with HTTP 400; that is already synchronized.
    All returned errors pass through the same token redaction as delivery.
    """
    last = None
    for attempt in range(retries + 1):
        try:
            _call(token, "editMessageCaption", {"chat_id": chat_id, "message_id": message_id,
                                               "caption": caption, "parse_mode": "HTML"})
            return "edited", None
        except TelegramError as exc:
            last = str(exc)
            if "message is not modified" in last.lower():
                return "edited", None
        if attempt < retries:
            sleep(2 ** attempt)
    return "failed", last


def send_text(db, text: str) -> bool:
    """Teks ke grup aktif. Tanpa token/grup → False tanpa mengirim. Tidak pernah raise; tanpa token di log."""
    token = get_token()
    chat = active_chat(db)
    if not token or chat is None:
        return False
    status, error = deliver(token, chat.chat_id, text, retries=1)
    if status != "sent":
        logger.warning("telegram system message failed: %s", error)
    return status == "sent"


def _u16(text: str) -> int:
    """Length in UTF-16 code units, which is how Telegram counts caption characters."""
    return len(text.encode("utf-16-le")) // 2


def format_caption(event, camera_name: str, zone_name: str | None, app_url: str | None, tz=None, *,
                   ai_text: str | None = None) -> str:
    """Caption HTML Telegram: judul tebal (Inggris), satu data per baris (label Indonesia).

    Setiap nilai dibatasi `FIELD_MAX` sebelum di-escape sehingga total pasti < CAPTION_MAX;
    caption tidak dipotong mentah-mentah (memotong string HTML bisa merusak tag → Telegram 400).
    """
    def val(v) -> str:
        return html.escape(str(v)[:FIELD_MAX])

    ts = event.ts_event if event.ts_event.tzinfo else event.ts_event.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(tz)
    payload = event.payload or {}
    rows: list[tuple[str, str]] = []
    if event.type == "attendance" and payload.get("match_reason") == "matched":
        arah = "CHECK IN" if payload.get("direction") == "entry" else "CHECK OUT"
        title = f"✅ <b>ATTENDANCE — {arah}</b>"
        rows.append(("Nama", payload.get("employee_name") or "-"))
    elif event.type == "attendance":
        title = "⚠️ <b>UNKNOWN FACE</b>"
    else:
        title = f"🚨 <b>{val(TYPE_TITLE.get(event.type, str(event.type).upper()))}</b>"
        if payload.get("reminder"):
            title += f" (pengingat ke-{int(payload['reminder'])})"
    rows.append(("Kamera", camera_name))
    if zone_name:
        rows.append(("Zona", zone_name))
    if event.type == "idle_zone" and payload.get("idle_s") is not None:
        secs = int(payload["idle_s"])
        rows.append(("Kosong", f"{secs // 60} menit" if secs >= 60 else f"{secs} detik"))
    if event.type == "crowd" and payload.get("count") is not None:
        rows.append(("Jumlah", f"{int(payload['count'])} orang (min {int(payload.get('min_count', 0))})"))
    rows.append(("Waktu", ts.strftime("%d %b %Y %H:%M:%S %Z").strip()))
    if event.type != "attendance":
        rows.append(("Level", str(event.severity or "").upper()))
    lines = [title, ""] + [f"<b>{k}</b>: {val(v)}" for k, v in rows]
    if app_url:
        lines += ["", f"🎥 Lihat klip: {val(app_url)}/events?event={event.id}"]
    base = "\n".join(lines)
    raw = " ".join((ai_text or "").split())
    # Telegram menghitung emoji astral (judul, tautan, nama) sebagai dua unit UTF-16; semua dihitung dalam unit itu.
    budget = CAPTION_MAX - _u16(base) - 1 - 8  # newline + margin keselamatan
    if raw and budget >= 40:
        prefix = "🤖 <b>AI</b>: "
        room = budget - _u16(prefix)
        size = min(len(raw), room)
        while size > 0:
            escaped = html.escape(raw[:size]) + ("…" if size < len(raw) else "")
            # never split an HTML entity: escape first, then shrink until the escaped text fits
            if _u16(escaped) <= room:
                lines.insert(len(lines) - 2 if app_url else len(lines), prefix + escaped)
                break
            size -= 1
    return "\n".join(lines)
