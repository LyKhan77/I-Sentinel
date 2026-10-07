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
        "🎥 Lihat event: http://10.0.0.1:5173/events?event=1234",
    ]


def test_caption_idle_and_crowd_with_reminder():
    idle = _event(type="idle_zone", payload={"idle_s": 750, "reminder": 0})
    lines = telegram.format_caption(idle, "Pos Depan", "Pos-1", None, tz=WIB).splitlines()
    assert lines[0] == "🚨 <b>IDLE ZONE</b>"
    assert "<b>Kosong</b>: 12 menit" in lines
    crowd = _event(type="crowd", payload={"count": 7, "min_count": 5, "reminder": 2})
    lines = telegram.format_caption(crowd, "Kantin", "Antrean", None, tz=WIB).splitlines()
    assert lines[0] == "🚨 <b>CROWD</b> (pengingat ke-2)"
    assert "<b>Jumlah</b>: 7 orang (min 5)" in lines
    short = _event(type="idle_zone", payload={"idle_s": 45})
    assert "<b>Kosong</b>: 45 detik" in telegram.format_caption(short, "C", None, None, tz=WIB)


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
    assert not any("Lihat event" in line for line in lines)


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


@pytest.mark.parametrize("photo", [None, b"jpg"])
def test_delivery_unpacks_and_equals_plain_tuple_and_carries_message_id(urlopen, photo):
    urlopen.replies.append({"ok": True, "result": {"message_id": 77}})
    result = telegram.deliver(TOKEN, "-1001", "cap", photo)
    status, error = result
    assert (status, error) == result == ("sent", None)
    assert result.message_id == 77 and result.photo is bool(photo)


def test_delivery_non_dict_reply_and_failure_carry_metadata(urlopen):
    result = telegram.deliver(TOKEN, "-1001", "cap")
    assert result.message_id is None and result.photo is False
    urlopen.replies.append(urllib.error.URLError(f"boom {TOKEN}"))
    result = telegram.deliver(TOKEN, "-1001", "cap", b"jpg", retries=1)
    assert result[0] == "failed" and TOKEN not in result[1]
    assert result.message_id is None and result.photo is False


def test_edit_caption_posts_edit_message_caption(urlopen):
    assert telegram.edit_caption(TOKEN, "-1001", 77, "cap") == ("edited", None)
    req = urlopen.calls[0]
    assert req.full_url.endswith("/editMessageCaption")
    assert json.loads(req.data) == {"chat_id": "-1001", "message_id": 77,
                                    "caption": "cap", "parse_mode": "HTML"}


def test_edit_caption_not_modified_is_success(urlopen):
    body = io.BytesIO(json.dumps({"ok": False, "description":
        "Bad Request: MESSAGE IS NOT MODIFIED: same content"}).encode())
    urlopen.replies.append(urllib.error.HTTPError("u", 400, "Bad Request", {}, body))
    assert telegram.edit_caption(TOKEN, "-1001", 77, "cap") == ("edited", None)
    assert len(urlopen.calls) == 1


def test_edit_caption_failure_has_no_token(urlopen):
    urlopen.replies.extend([urllib.error.URLError(f"boom {TOKEN}")] * 3)
    sleeps = []
    status, error = telegram.edit_caption(TOKEN, "-1001", 77, "cap", sleep=sleeps.append)
    assert status == "failed" and TOKEN not in error and "***" in error
    assert len(urlopen.calls) == 3 and sleeps == [1, 2]


def test_caption_ai_line_between_rows_and_link():
    lines = telegram.format_caption(_event(), "Cam", "Zone", "http://app.test", tz=WIB,
                                    ai_text="Seseorang berjalan.").splitlines()
    assert lines[-4:] == ["<b>Level</b>: WARNING", "🤖 <b>AI</b>: Seseorang berjalan.",
                          "", "🎥 Lihat event: http://app.test/events?event=1234"]


def test_caption_ai_text_is_escaped_and_whitespace_folded():
    text = telegram.format_caption(_event(), "C", None, None, tz=WIB, ai_text=" a <b> & c\n d ")
    assert text.endswith("🤖 <b>AI</b>: a &lt;b&gt; &amp; c d")


@pytest.mark.parametrize("ai", ["x" * 2000, "<&\n😀 " * 400], ids=["long", "escaped-emoji"])
def test_caption_with_ai_stays_within_limit(ai):
    from html.parser import HTMLParser

    class ValidHtml(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.tags = []
        def handle_starttag(self, tag, attrs):
            assert tag == "b"
            self.tags.append(tag)
        def handle_endtag(self, tag):
            assert self.tags.pop() == tag

    text = telegram.format_caption(_event(type="x" * 120, severity="s" * 120),
        "C" * 120, "Z" * 120, "http://app.test/" + "p" * 200, tz=WIB, ai_text=ai)
    assert len(text) <= 1024
    assert len(text.encode("utf-16-le")) // 2 <= 1024
    assert next(l for l in text.splitlines() if l.startswith("🤖")).endswith("…")
    parser = ValidHtml()
    parser.feed(text)
    assert not parser.tags
    # Every ampersand starts a complete escape entity, never a truncated one.
    import re
    assert not re.search(r"&(?!amp;|lt;|gt;|quot;|#x27;)", text)


def test_caption_without_ai_budget_drops_line(monkeypatch):
    base = telegram.format_caption(_event(), "C", None, None, tz=WIB)
    monkeypatch.setattr(telegram, "CAPTION_MAX", len(base) + 39)
    assert telegram.format_caption(_event(), "C", None, None, tz=WIB, ai_text="caption") == base


@pytest.mark.parametrize("ai", [None, "", " \n "])
def test_caption_without_ai_text_is_unchanged(ai):
    assert telegram.format_caption(_event(), "Cam", None, None, tz=WIB, ai_text=ai) == (
        "🚨 <b>INTRUSION</b>\n\n<b>Kamera</b>: Cam\n<b>Waktu</b>: 25 Sep 2026 11:42:07 WIB\n"
        "<b>Level</b>: WARNING")


def test_caption_budget_counts_utf16_units_of_the_base_fields():
    """Nama kamera/zona berisi emoji astral dihitung dua unit oleh Telegram; anggaran harus memakainya,
    bukan jumlah karakter Python, supaya caption akhir tidak melewati 1024 dan ditolak (400)."""
    text = telegram.format_caption(_event(), "😀" * 60, "😀" * 60, "http://app.test", tz=WIB, ai_text="x" * 2000)
    assert len(text.encode("utf-16-le")) // 2 <= 1024
    assert "🤖 <b>AI</b>: " in text


def test_caption_attendance_already_in_shows_first_entry_and_exit_status():
    payload = {"match_reason": "already_in", "employee_name": "Budi Santoso",
               "first_entry_ts": "2026-09-25T07:10:00+07:00"}
    ev = _event(type="attendance", payload=payload)
    lines = telegram.format_caption(ev, "Receptionist", "Gerbang Lobi", None, tz=WIB).splitlines()
    assert lines == [
        "🔁 <b>ATTENDANCE — SUDAH CHECK IN</b>", "", "<b>Nama</b>: Budi Santoso",
        "<b>Check in pertama</b>: 07:10:00 WIB", "<b>Exit sejak itu</b>: belum terlihat",
        "<b>Kamera</b>: Receptionist", "<b>Zona</b>: Gerbang Lobi",
        "<b>Waktu</b>: 25 Sep 2026 11:42:07 WIB",
    ]
    payload["exit_ts"] = "2026-09-25T09:00:00+07:00"
    assert "<b>Exit sejak itu</b>: 09:00:00 WIB" in telegram.format_caption(
        ev, "Receptionist", "Gerbang Lobi", None, tz=WIB).splitlines()


@pytest.mark.parametrize("value", [None, "bad-time", 123])
def test_caption_already_in_without_first_entry_ts_shows_dash(value):
    ev = _event(type="attendance", payload={"match_reason": "already_in"})
    if value is not None:
        ev.payload["first_entry_ts"] = value
    lines = telegram.format_caption(ev, "C", None, None, tz=WIB).splitlines()
    assert "<b>Check in pertama</b>: -" in lines
