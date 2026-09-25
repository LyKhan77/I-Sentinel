import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.telegram_chat import TelegramChat
from app.services import secret_store, telegram

TOKEN = "123456:" + "A" * 35
WIB = timezone(timedelta(hours=7), "WIB")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def urlopen(monkeypatch):
    calls = []
    replies = []

    def fake(req, timeout=None):
        calls.append(req)
        reply = replies.pop(0) if replies else {"ok": True, "result": True}
        if isinstance(reply, Exception):
            raise reply
        return _Resp(json.dumps(reply).encode())

    monkeypatch.setattr(telegram, "_urlopen", fake)
    return SimpleNamespace(calls=calls, replies=replies)


def _event(**over):
    base = dict(id=1234, type="intrusion", severity="warning", payload={},
                ts_event=datetime(2026, 9, 25, 4, 42, 7, tzinfo=timezone.utc))
    base.update(over)
    return SimpleNamespace(**base)


def test_token_prefers_secret_store_then_env(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "env-token")
    assert telegram.get_token() == "env-token"
    telegram.set_token(TOKEN)
    assert telegram.get_token() == TOKEN
    assert secret_store.get(telegram.TOKEN_KEY) == TOKEN


def test_set_chat_keeps_one_active_row(db):
    telegram.set_chat(db, "-1001", "Satpam")
    db.commit()
    telegram.set_chat(db, "-1002", "Supervisor")
    db.commit()
    assert telegram.active_chat(db).chat_id == "-1002"
    assert db.query(TelegramChat).filter_by(active=True).count() == 1
    telegram.set_chat(db, "-1001", "Satpam Baru")
    db.commit()
    assert (telegram.active_chat(db).chat_id, telegram.active_chat(db).label) == ("-1001", "Satpam Baru")


def test_app_url_roundtrip_strips_slash(db):
    assert telegram.app_url(db) is None
    telegram.set_app_url(db, "http://192.168.2.133:5173/")
    db.commit()
    assert telegram.app_url(db) == "http://192.168.2.133:5173"


def test_caption_behavior_layout():
    text = telegram.format_caption(_event(), "Lorong Server", "Lorong-15", "http://10.0.0.1:5173", tz=WIB)
    assert text.splitlines() == [
        "🚨 <b>INTRUSION</b>",
        "",
        "<b>Kamera</b>: Lorong Server",
        "<b>Zona</b>: Lorong-15",
        "<b>Waktu</b>: 25 Sep 2026 11:42:07 WIB",
        "<b>Level</b>: WARNING",
        "",
        "🎥 Lihat klip: http://10.0.0.1:5173/events?event=1234",
    ]


def test_caption_attendance_check_in_out_and_unknown():
    matched = _event(type="attendance", severity="info", payload={
        "match_reason": "matched", "direction": "exit", "employee_name": "Budi Santoso"})
    lines = telegram.format_caption(matched, "Receptionist", "Gerbang Lobi", None, tz=WIB).splitlines()
    assert lines[:4] == ["✅ <b>ATTENDANCE — CHECK OUT</b>", "", "<b>Nama</b>: Budi Santoso",
                         "<b>Kamera</b>: Receptionist"]
    assert not any(line.startswith("<b>Level</b>") for line in lines)
    unknown = _event(type="attendance", severity="info", payload={"match_reason": "no_match"})
    lines = telegram.format_caption(unknown, "Receptionist", "Gerbang Lobi", None, tz=WIB).splitlines()
    assert lines[0] == "⚠️ <b>UNKNOWN FACE</b>" and "<b>Zona</b>: Gerbang Lobi" in lines
    assert not any("Lihat klip" in line for line in lines)


def test_caption_new_type_uppercased_and_no_zone():
    text = telegram.format_caption(_event(type="fall_detect"), "Lobi", None, None, tz=WIB)
    assert text.splitlines()[0] == "🚨 <b>FALL_DETECT</b>"
    assert "<b>Zona</b>" not in text


def test_caption_escapes_html():
    ev = _event(type="attendance", severity="info", payload={
        "match_reason": "matched", "direction": "entry", "employee_name": "A&B <x>"})
    text = telegram.format_caption(ev, "Cam <1>", "Z & Z", None, tz=WIB)
    assert "A&amp;B &lt;x&gt;" in text and "Cam &lt;1&gt;" in text and "Z &amp; Z" in text
    assert "<x>" not in text


def test_caption_bounded_length_naive_utc():
    naive = _event(ts_event=datetime(2026, 9, 25, 4, 42, 7), type="x" * 2000)
    text = telegram.format_caption(naive, "C" * 500, "Z" * 500, "http://h", tz=WIB)
    assert "11:42:07" in text and len(text) <= telegram.CAPTION_MAX


def test_get_updates_lists_unique_groups(urlopen):
    urlopen.replies.append({"ok": True, "result": [
        {"message": {"chat": {"id": -1001, "type": "supergroup", "title": "Satpam"}}},
        {"my_chat_member": {"chat": {"id": -1001, "type": "supergroup", "title": "Satpam"}}},
        {"message": {"chat": {"id": 55, "type": "private", "first_name": "Budi"}}},
        {"my_chat_member": {"chat": {"id": -2002, "type": "group", "title": "Supervisor"}}},
    ]})
    assert telegram.get_updates(TOKEN) == [
        {"chat_id": "-1001", "title": "Satpam", "type": "supergroup"},
        {"chat_id": "-2002", "title": "Supervisor", "type": "group"},
    ]
    assert urlopen.calls[0].full_url.endswith("/getUpdates")


def test_deliver_photo_uses_multipart(urlopen):
    assert telegram.deliver(TOKEN, "-1001", "cap", b"\xff\xd8jpg") == ("sent", None)
    req = urlopen.calls[0]
    assert req.full_url.endswith("/sendPhoto")
    assert req.headers["Content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="chat_id"' in req.data and b"\xff\xd8jpg" in req.data and b'name="caption"' in req.data
    assert b'name="parse_mode"' in req.data and b"HTML" in req.data


def test_deliver_text_without_photo(urlopen):
    assert telegram.deliver(TOKEN, "-1001", "halo") == ("sent", None)
    assert urlopen.calls[0].full_url.endswith("/sendMessage")
    assert json.loads(urlopen.calls[0].data) == {"chat_id": "-1001", "text": "halo", "parse_mode": "HTML"}


def test_deliver_retries_then_failed_without_token_in_error(urlopen):
    sleeps = []
    urlopen.replies.extend([
        urllib.error.URLError(f"boom https://api.telegram.org/bot{TOKEN}/sendMessage"),
        {"ok": False, "description": "Bad Request: chat not found"},
        {"ok": False, "description": "Bad Request: chat not found"},
    ])
    status, err = telegram.deliver(TOKEN, "-1001", "x", sleep=sleeps.append)
    assert status == "failed" and err == "Bad Request: chat not found"
    assert sleeps == [1, 2] and len(urlopen.calls) == 3
    urlopen.replies.append(urllib.error.URLError(f"boom {TOKEN}"))
    status, err = telegram.deliver(TOKEN, "-1001", "x", retries=1)
    assert TOKEN not in err and "***" in err


def test_http_error_body_description_is_used(urlopen):
    body = io.BytesIO(json.dumps({"ok": False, "description": "Unauthorized"}).encode())
    urlopen.replies.append(urllib.error.HTTPError("u", 401, "Unauthorized", {}, body))
    with pytest.raises(telegram.TelegramError, match="Unauthorized"):
        telegram.get_me(TOKEN)
