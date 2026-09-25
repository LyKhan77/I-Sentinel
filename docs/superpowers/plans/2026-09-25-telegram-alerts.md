# Integrasi Bot Telegram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kejadian yang toggle Telegram-nya menyala dikirim ke satu grup petugas sebagai foto snapshot + caption (tautan ke event di aplikasi), tanpa menahan ingest event, dengan setelan bot di tab Notifikasi.

**Architecture:** `services/telegram.py` (klien stdlib urllib + setelan: token di `secret_store`, grup = satu baris aktif `telegram_chat`, URL aplikasi di `setting`). `alerting.handle` hanya memutuskan (toggle per behavior, aturan attendance, rate-limit), membuat baris `alert` berstatus `queued`, lalu `alert_dispatcher` (thread di proses API) menunggu snapshot ≤ 5 s dan mengirim `sendPhoto`/`sendMessage`. API `/telegram/settings|discover|test`, tab Notifikasi, toggle Telegram per behavior di Zona Deteksi, deep-link Inbox `?event=`.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic v2 + stdlib `urllib`/`threading`/`queue`, pytest; React 19 + TypeScript + Carbon, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-25-telegram-alerts-design.md`

## Global Constraints

- Branch `feat/telegram-alerts` (sudah ada, dari `main` @ `053df42`; spec di `277584a`).
- **Tanpa AI attribution** di commit/kode/docs (`AGENTS.md` §9).
- Tanpa dependensi baru, tanpa migrasi DB (flag `telegram` per behavior di JSON `zone.behaviors`; URL aplikasi di tabel `setting`; grup di tabel `telegram_chat` yang sudah ada).
- **Token bot tidak pernah** muncul di response API, log, pesan error (`alert.error`), commit, atau output percakapan. Tes memakai token palsu.
- Tidak ada panggilan jaringan Telegram di thread konsumen MQTT; semua lewat dispatcher.
- Tes tidak pernah memanggil `api.telegram.org` (monkeypatch `telegram._urlopen`).
- Vision node tidak diubah. Pipeline wajah R5b tidak diubah (hanya urutan pemanggilan di `events_consumer`).
- Semua string UI lewat `frontend/src/app/i18n.tsx`, `id` dan `en`. Mobile 390 px tanpa overflow.
- Setiap task: commit Conventional Commits + satu bullet di `CHANGELOG.md` bagian `### Integrasi bot Telegram (2026-09-25 – …)` (dibuat di Task 1, di atas `### Zona UX (2026-09-25)`).
- Baseline `main` `053df42`: backend **370 passed**; vision **204 passed, 3 deselected**; frontend **127 passed**; build 0; lint = set rule+file lama.
- Server `gspe-ai3`: deploy/restart butuh izin user (Task 7). Bot dan grup dibuat oleh user.

## Deviasi dari spec (disengaja)

1. **Setting `telegram` hanya menyimpan `app_url`**; grup terpilih disimpan di tabel `telegram_chat` (satu baris aktif) — kompatibel dengan `/telegram/status` dan tesnya yang sudah menghitung baris aktif.
2. **`alert.type = "attendance_unknown"`** untuk wajah tidak dikenal (bukan `attendance`) — supaya rate-limit wajah asing tidak tertahan oleh alert absensi tercatat di menit yang sama.
3. **Status alert baru `queued`** (sebelum dispatcher selesai) — ditambahkan ke chip Inbox.
4. **Pesan uji dikirim tanpa retry** (1 percobaan) agar request API tidak tertahan backoff.

## Review Focus

1. **Telegram mati/lambat saat banyak event** → ingest event tidak tertahan; alert berakhir `failed` dengan pesan tanpa token. Tes: Task 2 `test_handle_never_touches_network`, Task 1 `test_deliver_retries_then_failed_without_token_in_error`.
2. **Snapshot datang terlambat atau file hilang** → tetap terkirim sebagai teks, bukan hilang. Tes: Task 3 `test_process_falls_back_to_text_when_snapshot_missing`.
3. **Dua karyawan absen berurutan di gate yang sama dalam 5 menit** → keduanya terkirim; wajah asing setelah absensi tercatat tidak ter-rate-limit oleh absensi itu. Tes: Task 2 `test_attendance_matched_not_rate_limited`, `test_unknown_face_rate_limit_separate_from_matched`.
4. **Token salah ditempel admin** → 422, token lama tetap berlaku, response tidak menggemakan token. Tes: Task 4 `test_put_token_rejected_keeps_old_and_no_echo`.
5. **Zona lama tanpa key `telegram` per behavior** → mengikuti `zone.telegram` (false) → tidak ada spam setelah deploy. Tes: Task 2 `test_behavior_toggle_falls_back_to_zone_flag`.

---

### Task 1: `services/telegram.py` — klien + setelan + caption

**Files:**
- Create: `backend/app/services/telegram.py`
- Modify: `backend/tests/conftest.py` (fixture autouse: file rahasia tes di `tmp_path`)
- Test: `backend/tests/test_telegram.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces:
  - `TelegramError(Exception)`; konstanta `TOKEN_KEY = "telegram_bot_token"`, `TOKEN_RE`, `TEST_TEXT`, `CAPTION_MAX = 1024`; hook tes `telegram._urlopen`.
  - `get_token() -> str` (secret_store, fallback `settings.telegram_bot_token`), `set_token(token: str) -> None`.
  - `active_chat(db) -> TelegramChat | None`, `set_chat(db, chat_id: str, title: str) -> None` (tidak commit).
  - `app_url(db) -> str | None`, `set_app_url(db, url: str | None) -> None` (tidak commit).
  - `get_me(token) -> dict`, `get_updates(token) -> list[{"chat_id": str, "title": str, "type": str}]`.
  - `deliver(token, chat_id, caption, photo: bytes | None = None, *, retries=3, sleep=time.sleep) -> tuple[str, str | None]` → `("sent", None)` / `("failed", pesan)`.
  - `format_caption(event, camera_name: str, zone_name: str | None, app_url: str | None, tz=None) -> str`.

- [ ] **Step 1: Fixture autouse di `backend/tests/conftest.py`**

Tambahkan di akhir file:

```python
@pytest.fixture(autouse=True)
def _isolated_secret_store(tmp_path, monkeypatch):
    """Tes tidak pernah membaca/menulis file rahasia asli di ~/.isentinel."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "camera_secrets_file", str(tmp_path / "secrets" / "store.json"))
```

(Tes yang sudah mem-patch `camera_secrets_file` sendiri tetap menang karena monkeypatch-nya dijalankan setelah fixture ini.)

- [ ] **Step 2: Tulis tes yang gagal**

`backend/tests/test_telegram.py`:

```python
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


def test_caption_behavior_with_link():
    text = telegram.format_caption(_event(), "Lorong Server", "Lorong-15", "http://10.0.0.1:5173", tz=WIB)
    assert text.splitlines()[0] == "🚨 Intrusi — Lorong Server · zona Lorong-15"
    assert "25 Sep 2026 11:42:07 WIB" in text and "severity warning" in text
    assert text.endswith("http://10.0.0.1:5173/events?event=1234")


def test_caption_attendance_matched_and_unknown_and_fallback():
    matched = _event(type="attendance", severity="info", payload={
        "match_reason": "matched", "direction": "entry", "employee_name": "Budi Santoso"})
    assert telegram.format_caption(matched, "Lobi", "Gate", None, tz=WIB).splitlines()[0] == \
        "✅ Budi Santoso — Absen masuk 11:42 · Lobi"
    unknown = _event(type="attendance", severity="info", payload={"match_reason": "no_match"})
    assert telegram.format_caption(unknown, "Lobi", "Gate", None, tz=WIB).splitlines()[0] == \
        "⚠️ Wajah tidak dikenal — Lobi · zona Gate"
    new_kind = _event(type="fall_detect")
    assert "fall_detect — Lobi" in telegram.format_caption(new_kind, "Lobi", None, None, tz=WIB)
    assert "events?event" not in telegram.format_caption(new_kind, "Lobi", None, None, tz=WIB)


def test_caption_naive_timestamp_is_utc_and_capped():
    naive = _event(ts_event=datetime(2026, 9, 25, 4, 42, 7), type="x" * 2000)
    text = telegram.format_caption(naive, "Cam", None, None, tz=WIB)
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


def test_deliver_text_without_photo(urlopen):
    assert telegram.deliver(TOKEN, "-1001", "halo") == ("sent", None)
    assert urlopen.calls[0].full_url.endswith("/sendMessage")
    assert json.loads(urlopen.calls[0].data) == {"chat_id": "-1001", "text": "halo"}


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
```

- [ ] **Step 3: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_telegram.py -q`
Expected: FAIL — `ImportError: cannot import name 'telegram'`.

- [ ] **Step 4: Implementasi**

`backend/app/services/telegram.py`:

```python
"""Klien bot Telegram (stdlib urllib) + setelan notifikasi.

Token di secret_store (fallback env TELEGRAM_BOT_TOKEN), grup terpilih = satu baris aktif
telegram_chat, URL aplikasi di setting "telegram". Token tidak pernah masuk log/pesan error.
"""
from __future__ import annotations

import json
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

API = "https://api.telegram.org/bot{token}/{method}"
TOKEN_KEY = "telegram_bot_token"
SETTING_KEY = "telegram"
TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")
CAPTION_MAX = 1024  # batas caption sendPhoto
TEST_TEXT = "✅ Tes I-Sentinel — bot terhubung ke grup ini."
LABELS = {"intrusion": "Intrusi", "loitering": "Berlama-lama", "running": "Berlari"}

_urlopen = urllib.request.urlopen  # hook tes


class TelegramError(Exception):
    """Panggilan Telegram gagal; pesan sudah bebas token dan ≤ 250 karakter."""


def get_token() -> str:
    try:
        stored = secret_store.get(TOKEN_KEY)
    except secret_store.SecretStoreError:
        stored = None
    return stored or settings.telegram_bot_token


def set_token(token: str) -> None:
    secret_store.put(TOKEN_KEY, token)


def active_chat(db) -> TelegramChat | None:
    return db.query(TelegramChat).filter_by(active=True).order_by(TelegramChat.id).first()


def set_chat(db, chat_id: str, title: str) -> None:
    """Satu grup aktif: nonaktifkan yang lain, upsert yang dipilih (tanpa commit)."""
    for row in db.query(TelegramChat).filter_by(active=True):
        row.active = False
    row = db.query(TelegramChat).filter_by(chat_id=chat_id).first()
    if row is None:
        row = TelegramChat(chat_id=chat_id, label=title[:64])
        db.add(row)
    row.label = title[:64]
    row.active = True


def app_url(db) -> str | None:
    row = db.get(Setting, SETTING_KEY)
    return (row.value or {}).get("app_url") if row is not None else None


def set_app_url(db, url: str | None) -> None:
    row = db.get(Setting, SETTING_KEY)
    value = dict(row.value or {}) if row is not None else {}
    value["app_url"] = url.strip().rstrip("/") if url and url.strip() else None
    if row is None:
        db.add(Setting(key=SETTING_KEY, value=value))
    else:
        row.value = value


def _clean(message: str, token: str) -> str:
    return (message.replace(token, "***") if token else message)[:250]


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
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
    if files:
        body, ctype = _multipart(data or {}, files)
    else:
        body, ctype = json.dumps(data or {}).encode(), "application/json"
    req = urllib.request.Request(API.format(token=token, method=method), data=body,
                                 headers={"Content-Type": ctype})
    try:
        with _urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:  # Telegram mengirim JSON di 4xx
        try:
            payload = json.loads(exc.read() or b"{}")
        except ValueError:
            raise TelegramError(f"HTTP {exc.code}") from None
    except Exception as exc:  # jaringan / timeout / JSON rusak
        raise TelegramError(_clean(str(exc), token)) from None
    if not payload.get("ok"):
        raise TelegramError(_clean(str(payload.get("description") or "telegram error"), token))
    return payload.get("result")


def get_me(token: str) -> dict:
    return _call(token, "getMe") or {}


def get_updates(token: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for upd in _call(token, "getUpdates", {"allowed_updates": ["message", "my_chat_member"]}) or []:
        for key in ("message", "my_chat_member"):
            chat = (upd.get(key) or {}).get("chat") or {}
            if chat.get("type") in ("group", "supergroup") and chat.get("id") is not None:
                cid = str(chat["id"])
                seen[cid] = {"chat_id": cid, "title": chat.get("title") or cid, "type": chat["type"]}
    return list(seen.values())


def deliver(token: str, chat_id: str, caption: str, photo: bytes | None = None, *,
            retries: int = 3, sleep=time.sleep) -> tuple[str, str | None]:
    last = None
    for attempt in range(retries):
        try:
            if photo:
                _call(token, "sendPhoto", {"chat_id": chat_id, "caption": caption},
                      {"photo": ("snapshot.jpg", photo, "image/jpeg")})
            else:
                _call(token, "sendMessage", {"chat_id": chat_id, "text": caption})
            return "sent", None
        except TelegramError as exc:
            last = str(exc)
        if attempt < retries - 1:
            sleep(2 ** attempt)
    return "failed", last


def format_caption(event, camera_name: str, zone_name: str | None, app_url: str | None, tz=None) -> str:
    ts = event.ts_event if event.ts_event.tzinfo else event.ts_event.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(tz)
    when = ts.strftime("%d %b %Y %H:%M:%S %Z").strip()
    where = f"{camera_name} · zona {zone_name}" if zone_name else camera_name
    payload = event.payload or {}
    if event.type == "attendance" and payload.get("match_reason") == "matched":
        arah = "Absen masuk" if payload.get("direction") == "entry" else "Absen keluar"
        name = payload.get("employee_name") or "Karyawan"
        lines = [f"✅ {name} — {arah} {ts:%H:%M} · {camera_name}", when]
    elif event.type == "attendance":
        lines = [f"⚠️ Wajah tidak dikenal — {where}", when]
    else:
        lines = [f"🚨 {LABELS.get(event.type, event.type)} — {where}", f"{when} · severity {event.severity}"]
    if app_url:
        lines.append(f"Klip video: lihat di aplikasi → {app_url}/events?event={event.id}")
    return "\n".join(lines)[:CAPTION_MAX]
```

- [ ] **Step 5: Jalankan, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest tests/test_telegram.py tests/test_secret_store.py tests/test_alerts_api.py -q`
Expected: semua passed. Lalu suite penuh: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`.

(`%Z` untuk `WIB` di tes berasal dari nama `timezone(..., "WIB")`; di server `astimezone()` tanpa argumen memakai zona lokal Asia/Jakarta.)

- [ ] **Step 6: CHANGELOG + commit**

Di `CHANGELOG.md`, di atas `### Zona UX (2026-09-25)`:

```markdown
### Integrasi bot Telegram (2026-09-25 – …)

- **`services/telegram.py`**: klien stdlib (getMe, getUpdates → daftar grup unik, sendPhoto multipart,
  sendMessage, retry 3× backoff), token di `secret_store` (fallback env), grup = satu baris aktif
  `telegram_chat`, URL aplikasi di `setting`; caption (behavior, absensi tercatat, wajah tidak dikenal, fallback
  tipe baru, ≤ 1024); token tidak pernah masuk pesan error. Tes memakai file rahasia terisolasi. Backend **<angka> passed**.
```

```bash
git add backend/app/services/telegram.py backend/tests/test_telegram.py backend/tests/conftest.py CHANGELOG.md
git commit -m "feat(telegram): klien bot + setelan + caption alert"
```

---

### Task 2: Gerbang alert per behavior + urutan consumer + fix `/alerts`

**Files:**
- Modify: `backend/app/services/alerting.py` (tulis ulang)
- Modify: `backend/app/services/events_consumer.py` (urutan attendance → alert)
- Modify: `backend/app/schemas/zone.py` (`_validate_behaviors` menerima `telegram`)
- Modify: `backend/app/schemas/alert.py:8` (`camera_id: int | None`)
- Create: `backend/app/services/alert_dispatcher.py` (kerangka `enqueue` saja; worker di Task 3)
- Test: `backend/tests/test_alerting.py` (tulis ulang), `backend/tests/test_alerts_api.py`, `backend/tests/test_zones_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: —
- Produces:
  - `alerting.alert_type(event) -> str` (`"attendance_unknown"` untuk wajah tak dikenal, selain itu `event.type`)
  - `alerting.should_alert(db, event, now=None) -> tuple[bool, str]` (alasan: `""`, `no_zone`, `telegram_off`, `attendance_skipped`, `rate_limited`)
  - `alerting.handle(db, event, now=None) -> Alert | None` — status `queued` lalu `alert_dispatcher.dispatcher.enqueue(alert.id)`; enqueue gagal → `failed` "queue full".
  - `alert_dispatcher.dispatcher` (instance modul) dengan `enqueue(alert_id: int) -> bool`.

- [ ] **Step 1: Tulis tes (gagal)**

Ganti **seluruh** isi `backend/tests/test_alerting.py` dengan:

```python
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.alert import Alert
from app.models.camera import Camera
from app.models.event import Event
from app.models.zone import Zone
from app.services import alert_dispatcher, alerting
from app.services.events_consumer import handle_message

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
POLY = [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]]


@pytest.fixture
def queued(monkeypatch):
    ids = []
    monkeypatch.setattr(alert_dispatcher.dispatcher, "enqueue", lambda alert_id: ids.append(alert_id) or True)
    return ids


@pytest.fixture(autouse=True)
def broadcast(monkeypatch):
    sent = []

    async def fake(payload):
        sent.append(payload)

    monkeypatch.setattr(alerting.hub, "broadcast", fake)
    return sent


def _zone(db, behaviors, telegram=False, rate_limit_min=5, type="behavior", direction=None):
    cam = Camera(name=f"cam-{uuid.uuid4().hex[:6]}", host="1.2.3.4")
    db.add(cam)
    db.commit()
    zone = Zone(camera_id=cam.id, name="z", type=type, direction=direction, polygon=POLY,
                behaviors=behaviors, telegram=telegram, rate_limit_min=rate_limit_min)
    db.add(zone)
    db.commit()
    return cam, zone


def _event(db, cam, zone, type="intrusion", payload=None, severity="warning"):
    ev = Event(type=type, camera_id=cam.id, zone_id=zone.id if zone else None, severity=severity,
               payload=payload or {}, ts_event=NOW)
    db.add(ev)
    db.commit()
    return ev


INTRUSION_ON = [{"kind": "intrusion", "trigger_seconds": 0, "telegram": True}]
GATE_ON = [{"kind": "attendance", "trigger_seconds": 0, "telegram": True}]


def test_behavior_toggle_on_queues_alert(db, queued):
    cam, zone = _zone(db, INTRUSION_ON)
    alert = alerting.handle(db, _event(db, cam, zone), now=NOW)
    assert alert.status == "queued" and queued == [alert.id]


def test_behavior_toggle_off_and_other_kind_skip(db, queued):
    cam, zone = _zone(db, [{"kind": "intrusion", "trigger_seconds": 0, "telegram": False},
                           {"kind": "loitering", "trigger_seconds": 30}])
    assert alerting.should_alert(db, _event(db, cam, zone), now=NOW) == (False, "telegram_off")
    assert alerting.should_alert(db, _event(db, cam, zone, type="loitering"), now=NOW) == (False, "telegram_off")
    assert alerting.should_alert(db, _event(db, cam, zone, type="running"), now=NOW) == (False, "telegram_off")
    assert queued == []


def test_behavior_toggle_falls_back_to_zone_flag(db, queued):
    cam, zone = _zone(db, [{"kind": "intrusion", "trigger_seconds": 0}], telegram=True)
    assert alerting.should_alert(db, _event(db, cam, zone), now=NOW) == (True, "")
    cam2, zone2 = _zone(db, [{"kind": "intrusion", "trigger_seconds": 0}], telegram=False)
    assert alerting.should_alert(db, _event(db, cam2, zone2), now=NOW) == (False, "telegram_off")


def test_event_without_zone_or_camera_is_skipped(db, queued):
    cam, _ = _zone(db, INTRUSION_ON)
    assert alerting.should_alert(db, _event(db, cam, None), now=NOW) == (False, "no_zone")
    ev = Event(type="system", camera_id=None, severity="critical", ts_event=NOW)
    db.add(ev)
    db.commit()
    assert alerting.handle(db, ev, now=NOW) is None


def test_severity_is_no_longer_a_gate(db, queued):
    cam, zone = _zone(db, INTRUSION_ON)
    assert alerting.should_alert(db, _event(db, cam, zone, severity="info"), now=NOW) == (True, "")


def test_behavior_rate_limited_within_window(db, queued):
    cam, zone = _zone(db, INTRUSION_ON)
    alerting.handle(db, _event(db, cam, zone), now=NOW)
    second = alerting.handle(db, _event(db, cam, zone), now=NOW + timedelta(minutes=2))
    third = alerting.handle(db, _event(db, cam, zone), now=NOW + timedelta(minutes=6))
    assert (second.status, third.status) == ("rate_limited", "queued")
    assert len(queued) == 2


def test_attendance_matched_and_unknown_sent_others_skipped(db, queued):
    cam, zone = _zone(db, GATE_ON, type="attendance", direction="entry")
    for reason, employee in (("matched", 1), ("no_match", None)):
        ev = _event(db, cam, zone, type="attendance",
                    payload={"match_reason": reason, "employee_id": employee}, severity="info")
        assert alerting.should_alert(db, ev, now=NOW) == (True, "")
    for reason in ("cooldown", "already_in", "low_quality", "no_face", None):
        ev = _event(db, cam, zone, type="attendance", payload={"match_reason": reason}, severity="info")
        assert alerting.should_alert(db, ev, now=NOW) == (False, "attendance_skipped")


def test_attendance_matched_not_rate_limited(db, queued):
    cam, zone = _zone(db, GATE_ON, type="attendance", direction="entry")
    for employee in (1, 2):
        ev = _event(db, cam, zone, type="attendance", severity="info",
                    payload={"match_reason": "matched", "employee_id": employee})
        assert alerting.handle(db, ev, now=NOW).status == "queued"


def test_unknown_face_rate_limit_separate_from_matched(db, queued):
    cam, zone = _zone(db, GATE_ON, type="attendance", direction="entry")
    matched = _event(db, cam, zone, type="attendance", severity="info",
                     payload={"match_reason": "matched", "employee_id": 1})
    alerting.handle(db, matched, now=NOW)
    unknown = _event(db, cam, zone, type="attendance", severity="info", payload={"match_reason": "no_match"})
    first = alerting.handle(db, unknown, now=NOW + timedelta(minutes=1))
    again = alerting.handle(db, _event(db, cam, zone, type="attendance", severity="info",
                                       payload={"match_reason": "no_match"}), now=NOW + timedelta(minutes=2))
    assert (first.type, first.status, again.status) == ("attendance_unknown", "queued", "rate_limited")


def test_handle_never_touches_network(db, queued, monkeypatch):
    from app.services import telegram

    monkeypatch.setattr(telegram, "_urlopen", lambda *a, **k: pytest.fail("network in consumer thread"))
    cam, zone = _zone(db, INTRUSION_ON)
    assert alerting.handle(db, _event(db, cam, zone), now=NOW).status == "queued"


def test_queue_full_marks_failed(db, monkeypatch):
    monkeypatch.setattr(alert_dispatcher.dispatcher, "enqueue", lambda alert_id: False)
    cam, zone = _zone(db, INTRUSION_ON)
    alert = alerting.handle(db, _event(db, cam, zone), now=NOW)
    assert (alert.status, alert.error) == ("failed", "queue full")


def test_consumer_runs_attendance_before_alert(db, queued, monkeypatch):
    """Keputusan alert attendance butuh match_reason yang diisi attendance.handle_face_event."""
    order = []
    from app.services import attendance
    monkeypatch.setattr(attendance, "handle_face_event", lambda db, ev, embedding=None: order.append("attendance"))
    monkeypatch.setattr(alerting, "handle", lambda db, ev: order.append("alert"))
    cam, _ = _zone(db, INTRUSION_ON)
    handle_message(db, "isentinel/events", json.dumps({
        "event_id": str(uuid.uuid4()), "type": "intrusion", "camera_id": cam.id,
        "severity": "warning", "ts_event": NOW.isoformat(),
    }).encode())
    assert order == ["attendance", "alert"]
```

Di `backend/tests/test_alerts_api.py` tambahkan:

```python
def test_list_alerts_with_null_camera_is_200(client, db):
    ev = Event(type="system", camera_id=None, severity="critical", ts_event=datetime.now(timezone.utc))
    db.add(ev); db.commit(); db.refresh(ev)
    db.add(Alert(event_id=ev.id, camera_id=None, zone_id=None, type="system", severity="critical",
                 status="not_configured"))
    db.commit()
    r = client.get("/api/v1/alerts", headers=_admin_headers(client))
    assert r.status_code == 200 and r.json()[0]["camera_id"] is None
```

Di `backend/tests/test_zones_api.py` tambahkan:

```python
def test_behavior_telegram_flag_roundtrip_and_validation(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    behaviors = [{"kind": "intrusion", "trigger_seconds": 0, "telegram": True}]
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                           "behaviors": behaviors}, headers=h)
    assert r.status_code == 200 and r.json()["behaviors"] == behaviors
    bad = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                             "behaviors": [{"kind": "intrusion", "telegram": "ya"}]}, headers=h)
    assert bad.status_code == 422
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_alerting.py tests/test_alerts_api.py tests/test_zones_api.py -q`
Expected: FAIL — `alert_dispatcher` tidak ada, `/alerts` 500, `telegram: "ya"` diterima.

- [ ] **Step 3: Implementasi**

`backend/app/services/alert_dispatcher.py` (kerangka; Task 3 menambah worker):

```python
"""Antrean alert Telegram: dipisah dari thread konsumen MQTT (ingest tidak boleh tertahan Telegram)."""
from __future__ import annotations

import logging
import queue

logger = logging.getLogger(__name__)
QUEUE_MAX = 200


class AlertDispatcher:
    def __init__(self, maxsize: int = QUEUE_MAX):
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)

    def enqueue(self, alert_id: int) -> bool:
        try:
            self._q.put_nowait(alert_id)
            return True
        except queue.Full:
            logger.warning("alert queue full, alert %s dropped", alert_id)
            return False


dispatcher = AlertDispatcher()
```

`backend/app/services/alerting.py` — ganti seluruh isi:

```python
"""Alerting: gerbang Telegram per behavior + rate-limit, lalu antre ke dispatcher.

Tidak ada I/O jaringan di sini: thread konsumen MQTT tidak boleh tertahan Telegram. Kirim
(tunggu snapshot, sendPhoto/sendMessage, retry) dikerjakan `alert_dispatcher`.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.models.alert import Alert
from app.models.zone import Zone
from app.services import alert_dispatcher
from app.ws.hub import hub

logger = logging.getLogger(__name__)


def _telegram_on(zone: Zone, kind: str) -> bool:
    """Toggle per behavior; item tanpa key → flag zona; zona pra-R5 (behaviors null) → flag zona."""
    if zone.behaviors is None:
        return bool(zone.telegram)
    for b in zone.behaviors:
        if isinstance(b, dict) and b.get("kind") == kind:
            return bool(b.get("telegram", zone.telegram))
    return False


def alert_type(event) -> str:
    """Wajah tidak dikenal punya kunci rate-limit sendiri, terpisah dari absensi tercatat."""
    if event.type == "attendance" and (event.payload or {}).get("match_reason") == "no_match":
        return "attendance_unknown"
    return event.type


def should_alert(db, event, now: datetime | None = None) -> tuple[bool, str]:
    now = now or datetime.now(timezone.utc)
    zone = db.get(Zone, event.zone_id) if event.zone_id else None
    if zone is None:
        return False, "no_zone"
    if not _telegram_on(zone, event.type):
        return False, "telegram_off"
    if event.type == "attendance":
        payload = event.payload or {}
        if payload.get("match_reason") == "matched":
            return True, ""  # duplikat sudah dicegah cooldown/already_in absensi
        if payload.get("match_reason") != "no_match" or payload.get("employee_id") is not None:
            return False, "attendance_skipped"
    cutoff = now - timedelta(minutes=zone.rate_limit_min)
    recent = (
        db.query(Alert)
        .filter(
            Alert.camera_id == event.camera_id,
            Alert.zone_id == event.zone_id,
            Alert.type == alert_type(event),
            Alert.created_at > cutoff,
        )
        .first()
    )
    if recent is not None:
        return False, "rate_limited"
    return True, ""


def handle(db, event, now: datetime | None = None) -> Alert | None:
    """Gerbang → baris alert (queued / rate_limited) → antre → broadcast. Tidak pernah raise."""
    now = now or datetime.now(timezone.utc)
    if event.camera_id is None:
        return None
    ok, reason = should_alert(db, event, now)
    if not ok and reason != "rate_limited":
        return None
    alert = Alert(
        event_id=event.id,
        camera_id=event.camera_id,
        zone_id=event.zone_id,
        type=alert_type(event),
        severity=event.severity,
        status="queued" if ok else "rate_limited",
        created_at=now,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    if ok and not alert_dispatcher.dispatcher.enqueue(alert.id):
        alert.status, alert.error = "failed", "queue full"
        db.commit()
    try:
        asyncio.run(hub.broadcast({"kind": "alert", "event_id": event.id, "status": alert.status}))
    except Exception:
        logger.exception("alert broadcast failed for event %s", event.id)
    return alert
```

`backend/app/services/events_consumer.py` — tukar urutan dua blok `try` di cabang `status == "created"`: blok `attendance.handle_face_event(...)` dulu, lalu blok `alerting.handle(db, ev)` (isi `except` masing-masing tetap). Tambahkan komentar: `# attendance dulu: keputusan alert absensi butuh match_reason`.

`backend/app/schemas/zone.py` — di `_validate_behaviors`, tuple flag menjadi `("snapshot", "clip", "telegram")`; docstring menyebut `[telegram]`.

`backend/app/schemas/alert.py:8` — `camera_id: int | None`.

`backend/app/core/config.py` — komentar pada `alert_min_severity`: `# deprecated: gerbang Telegram = toggle per behavior`.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`
Expected: semua passed. Tes lain yang masih memakai `alerting.send_telegram` atau severity gate (cari `grep -rn "send_telegram\|alert_min_severity" backend/tests`) diubah mengikuti perilaku baru dan disebut di ringkasan.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Gerbang alert baru**: toggle `telegram` per behavior (fallback `zone.telegram`, default off; berlaku untuk tipe
  apa pun), `ALERT_MIN_SEVERITY` bukan gerbang lagi; attendance hanya `matched` (tanpa rate-limit) dan wajah tidak
  dikenal (`alert.type = attendance_unknown`, rate-limit sendiri); `handle` tanpa I/O jaringan → status `queued` +
  antrean dispatcher. Consumer memproses attendance sebelum alert. Fix `GET /alerts` 500 (`camera_id` null).
  Backend **<angka> passed**.
```

```bash
git add backend/app/services/alerting.py backend/app/services/alert_dispatcher.py backend/app/services/events_consumer.py backend/app/schemas/zone.py backend/app/schemas/alert.py backend/app/core/config.py backend/tests/test_alerting.py backend/tests/test_alerts_api.py backend/tests/test_zones_api.py CHANGELOG.md
git commit -m "feat(alert): gerbang Telegram per behavior + antrean, tanpa I/O di consumer"
```

---

### Task 3: Dispatcher — tunggu snapshot, kirim, catat hasil

**Files:**
- Modify: `backend/app/services/alert_dispatcher.py`
- Modify: `backend/app/main.py` (start/stop dispatcher di `lifespan`)
- Test: `backend/tests/test_alert_dispatcher.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `telegram.get_token`, `active_chat`, `app_url`, `format_caption`, `deliver` (Task 1); `dispatcher.enqueue` (Task 2).
- Produces: `AlertDispatcher.process(alert_id: int, db) -> None` (sinkron, dipakai worker dan tes), `start()`, `stop()`; parameter `snapshot_polls: int = 10`, `poll_s: float = 0.5`, `sleep=time.sleep`, `session_factory=SessionLocal`.

- [ ] **Step 1: Tulis tes yang gagal**

`backend/tests/test_alert_dispatcher.py`:

```python
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.event import Event
from app.models.telegram_chat import TelegramChat
from app.models.zone import Zone
from app.services import telegram
from app.services.alert_dispatcher import AlertDispatcher

TOKEN = "123456:" + "B" * 35


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_deliver(token, chat_id, caption, photo=None, **kw):
        calls.append({"token": token, "chat_id": chat_id, "caption": caption, "photo": photo})
        return "sent", None

    monkeypatch.setattr(telegram, "deliver", fake_deliver)
    return calls


def _alert(db, tmp_path, monkeypatch, snapshot=b"\xff\xd8jpg", configured=True):
    root = tmp_path / "media"
    (root / "snapshots").mkdir(parents=True)
    monkeypatch.setattr(settings, "storage_root", str(root))
    if snapshot is not None:
        (root / "snapshots" / "a.jpg").write_bytes(snapshot)
    if configured:
        telegram.set_token(TOKEN)
        db.add(TelegramChat(label="Satpam", chat_id="-1001", active=True))
    cam = Camera(name="Lorong Server", host="1.2.3.4")
    db.add(cam); db.commit()
    zone = Zone(camera_id=cam.id, name="Lorong-15", type="behavior", polygon=[[0, 0], [1, 0], [1, 1]])
    db.add(zone); db.commit()
    ev = Event(type="intrusion", camera_id=cam.id, zone_id=zone.id, severity="warning",
               ts_event=datetime(2026, 9, 25, 4, 42, 7, tzinfo=timezone.utc),
               snapshot_path="snapshots/a.jpg" if snapshot is not None else None)
    db.add(ev); db.commit()
    alert = Alert(event_id=ev.id, camera_id=cam.id, zone_id=zone.id, type="intrusion",
                  severity="warning", status="queued")
    db.add(alert); db.commit()
    return alert


def _dispatcher():
    return AlertDispatcher(snapshot_polls=3, poll_s=0, sleep=lambda s: None)


def test_process_sends_photo_with_caption(db, tmp_path, sent, monkeypatch):
    alert = _alert(db, tmp_path, monkeypatch)
    _dispatcher().process(alert.id, db)
    db.refresh(alert)
    assert (alert.status, alert.chat_id, alert.error) == ("sent", "-1001", None)
    assert sent[0]["photo"] == b"\xff\xd8jpg"
    assert sent[0]["caption"].startswith("🚨 Intrusi — Lorong Server · zona Lorong-15")


def test_process_waits_for_late_snapshot(db, tmp_path, sent, monkeypatch):
    alert = _alert(db, tmp_path, monkeypatch)
    ev = db.get(Event, alert.event_id)
    ev.snapshot_path = None
    db.commit()
    polls = []

    def late(_s):
        polls.append(1)
        if len(polls) == 2:
            ev.snapshot_path = "snapshots/a.jpg"
            db.commit()

    AlertDispatcher(snapshot_polls=5, poll_s=0.5, sleep=late).process(alert.id, db)
    assert sent[0]["photo"] == b"\xff\xd8jpg" and len(polls) == 2


def test_process_falls_back_to_text_when_snapshot_missing(db, tmp_path, sent, monkeypatch):
    alert = _alert(db, tmp_path, monkeypatch, snapshot=None)
    _dispatcher().process(alert.id, db)
    db.refresh(alert)
    assert alert.status == "sent" and sent[0]["photo"] is None


def test_process_not_configured_makes_no_call(db, tmp_path, sent, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    alert = _alert(db, tmp_path, monkeypatch, configured=False)
    _dispatcher().process(alert.id, db)
    db.refresh(alert)
    assert alert.status == "not_configured" and sent == []


def test_process_records_failure(db, tmp_path, monkeypatch):
    monkeypatch.setattr(telegram, "deliver", lambda *a, **k: ("failed", "Forbidden: bot was kicked"))
    alert = _alert(db, tmp_path, monkeypatch)
    _dispatcher().process(alert.id, db)
    db.refresh(alert)
    assert (alert.status, alert.error) == ("failed", "Forbidden: bot was kicked")


def test_worker_thread_drains_queue(db, tmp_path, sent, monkeypatch):
    alert = _alert(db, tmp_path, monkeypatch)

    class _NoClose:
        def __init__(self, s): self.s = s
        def __getattr__(self, name): return getattr(self.s, name)
        def close(self): pass

    d = AlertDispatcher(snapshot_polls=1, poll_s=0, sleep=lambda s: None, session_factory=lambda: _NoClose(db))
    d.start()
    try:
        assert d.enqueue(alert.id)
        d.join_queue(timeout=5)
    finally:
        d.stop()
    db.refresh(alert)
    assert alert.status == "sent"
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_alert_dispatcher.py -q`
Expected: FAIL — `AlertDispatcher()` tidak menerima `snapshot_polls` / tidak punya `process`.

- [ ] **Step 3: Implementasi**

`backend/app/services/alert_dispatcher.py` — ganti isi:

```python
"""Dispatcher alert Telegram: dipisah dari thread konsumen MQTT (ingest tidak boleh tertahan Telegram).

Per alert: tunggu snapshot event (media datang ±0,5 s setelah event) maksimal ~5 s, lalu
sendPhoto (file dari storage_root) atau sendMessage teks. Hasil ditulis ke baris alert.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.zone import Zone
from app.services import telegram

logger = logging.getLogger(__name__)
QUEUE_MAX = 200


class AlertDispatcher:
    def __init__(self, maxsize: int = QUEUE_MAX, *, snapshot_polls: int = 10, poll_s: float = 0.5,
                 sleep=time.sleep, session_factory=SessionLocal):
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)
        self._snapshot_polls = snapshot_polls
        self._poll_s = poll_s
        self._sleep = sleep
        self._session_factory = session_factory
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    def enqueue(self, alert_id: int) -> bool:
        try:
            self._q.put_nowait(alert_id)
            return True
        except queue.Full:
            logger.warning("alert queue full, alert %s dropped", alert_id)
            return False

    def start(self) -> None:
        self._stopped.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="alert-dispatcher")
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def join_queue(self, timeout: float) -> None:
        """Tes: tunggu antrean kosong dan item terakhir selesai diproses."""
        deadline = time.monotonic() + timeout
        while self._q.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)

    def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                alert_id = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            db = self._session_factory()
            try:
                self.process(alert_id, db)
            except Exception:
                db.rollback()
                logger.exception("alert %s dispatch failed", alert_id)
            finally:
                db.close()
                self._q.task_done()

    def _snapshot(self, db, event) -> bytes | None:
        for attempt in range(self._snapshot_polls):
            db.refresh(event)
            if event.snapshot_path:
                root = os.path.realpath(settings.storage_root)
                full = os.path.realpath(os.path.join(root, event.snapshot_path))
                if full.startswith(root + os.sep) and os.path.isfile(full):
                    with open(full, "rb") as f:
                        return f.read()
                return None  # path ada tapi file hilang/di luar root → kirim teks
            if attempt < self._snapshot_polls - 1:
                self._sleep(self._poll_s)
        return None

    def process(self, alert_id: int, db) -> None:
        alert = db.get(Alert, alert_id)
        if alert is None:
            return
        token = telegram.get_token()
        chat = telegram.active_chat(db)
        if not token or chat is None:
            alert.status, alert.error = "not_configured", None
            db.commit()
            return
        event = alert.event
        camera = db.get(Camera, alert.camera_id) if alert.camera_id else None
        zone = db.get(Zone, alert.zone_id) if alert.zone_id else None
        caption = telegram.format_caption(
            event, camera.name if camera else f"cam {alert.camera_id}",
            zone.name if zone else None, telegram.app_url(db))
        photo = self._snapshot(db, event)
        status, error = telegram.deliver(token, chat.chat_id, caption, photo)
        alert.status, alert.error, alert.chat_id = status, error, chat.chat_id
        db.commit()


dispatcher = AlertDispatcher()
```

`backend/app/main.py` — di `lifespan`, setelah `consumer.start()`:

```python
    from app.services.alert_dispatcher import dispatcher
    dispatcher.start()
```

dan di blok `finally`, sebelum `consumer.stop()`: `dispatcher.stop()`.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`
Expected: semua passed (TestClient memicu `lifespan` → dispatcher start/stop tanpa error).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Dispatcher alert**: thread di proses API (start/stop di `lifespan`) mengambil antrean, menunggu snapshot ±5 s
  (10 × 0,5 s), kirim `sendPhoto` dari `storage_root` atau teks bila snapshot tidak datang / file hilang; hasil
  `sent` / `failed` (+ pesan Telegram) / `not_configured` di baris alert. Backend **<angka> passed**.
```

```bash
git add backend/app/services/alert_dispatcher.py backend/app/main.py backend/tests/test_alert_dispatcher.py CHANGELOG.md
git commit -m "feat(alert): dispatcher Telegram — tunggu snapshot, sendPhoto/teks, catat hasil"
```

---

### Task 4: API setelan Telegram

**Files:**
- Modify: `backend/app/api/telegram.py`
- Test: `backend/tests/test_telegram_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 1 (`get_token`, `set_token`, `TOKEN_RE`, `get_me`, `get_updates`, `active_chat`, `set_chat`, `app_url`, `set_app_url`, `deliver`, `TEST_TEXT`, `TelegramError`).
- Produces:
  - `GET /api/v1/telegram/settings` (admin) → `{has_token: bool, chat_id: str|null, chat_title: str|null, app_url: str|null, last_alert: {status, error, created_at}|null}`
  - `PUT /api/v1/telegram/settings` (admin) body `{token?, chat_id?, chat_title?, app_url?}` → bentuk sama dengan GET. Token format salah / ditolak `getMe` → 422 (`"invalid token format"` / `"token rejected by Telegram"`); gagal simpan → 500.
  - `POST /api/v1/telegram/discover` (admin) → `{"chats": [...]}`; tanpa token → 409 `"token not configured"`; error Telegram → 502 (pesan bebas token).
  - `POST /api/v1/telegram/test` (admin) → `{status, error}`; tanpa token/grup → 409 `"telegram not configured"`.
  - `GET /api/v1/telegram/status` tetap (configured = `bool(get_token())`).

- [ ] **Step 1: Tulis tes yang gagal**

`backend/tests/test_telegram_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.services import secret_store, telegram
from tests.conftest import admin_headers

TOKEN = "123456:" + "C" * 35
OTHER = "654321:" + "D" * 35


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "media"))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def tg(monkeypatch):
    calls = []
    monkeypatch.setattr(telegram, "get_me", lambda token: calls.append(("getMe", token)) or {"username": "bot"})
    monkeypatch.setattr(telegram, "get_updates", lambda token: [{"chat_id": "-1001", "title": "Satpam", "type": "supergroup"}])
    monkeypatch.setattr(telegram, "deliver", lambda token, chat, text, photo=None, **kw: calls.append(("send", chat, text, kw)) or ("sent", None))
    return calls


def test_settings_empty(client):
    body = client.get("/api/v1/telegram/settings", headers=admin_headers(client)).json()
    assert body == {"has_token": False, "chat_id": None, "chat_title": None, "app_url": None, "last_alert": None}


def test_put_token_chat_and_url(client, tg):
    h = admin_headers(client)
    r = client.put("/api/v1/telegram/settings", json={
        "token": TOKEN, "chat_id": "-1001", "chat_title": "Satpam", "app_url": "http://10.0.0.1:5173/",
    }, headers=h)
    assert r.status_code == 200
    assert r.json() == {"has_token": True, "chat_id": "-1001", "chat_title": "Satpam",
                        "app_url": "http://10.0.0.1:5173", "last_alert": None}
    assert TOKEN not in r.text
    assert secret_store.get(telegram.TOKEN_KEY) == TOKEN


def test_put_token_rejected_keeps_old_and_no_echo(client, tg, monkeypatch):
    h = admin_headers(client)
    client.put("/api/v1/telegram/settings", json={"token": TOKEN}, headers=h)

    def reject(token):
        raise telegram.TelegramError("Unauthorized")

    monkeypatch.setattr(telegram, "get_me", reject)
    r = client.put("/api/v1/telegram/settings", json={"token": OTHER}, headers=h)
    assert r.status_code == 422 and OTHER not in r.text
    bad_format = client.put("/api/v1/telegram/settings", json={"token": "bukan-token"}, headers=h)
    assert bad_format.status_code == 422 and "bukan-token" not in bad_format.text
    assert telegram.get_token() == TOKEN


def test_discover_and_test_message(client, tg):
    h = admin_headers(client)
    assert client.post("/api/v1/telegram/discover", headers=h).status_code == 409
    assert client.post("/api/v1/telegram/test", headers=h).status_code == 409
    client.put("/api/v1/telegram/settings", json={"token": TOKEN}, headers=h)
    assert client.post("/api/v1/telegram/discover", headers=h).json() == {
        "chats": [{"chat_id": "-1001", "title": "Satpam", "type": "supergroup"}]}
    client.put("/api/v1/telegram/settings", json={"chat_id": "-1001", "chat_title": "Satpam"}, headers=h)
    assert client.post("/api/v1/telegram/test", headers=h).json() == {"status": "sent", "error": None}
    send = [c for c in tg if c[0] == "send"][0]
    assert send[1] == "-1001" and send[2] == telegram.TEST_TEXT and send[3] == {"retries": 1}


def test_discover_telegram_error_is_502_without_token(client, tg, monkeypatch):
    h = admin_headers(client)
    client.put("/api/v1/telegram/settings", json={"token": TOKEN}, headers=h)

    def boom(token):
        raise telegram.TelegramError("Conflict: webhook is active")

    monkeypatch.setattr(telegram, "get_updates", boom)
    r = client.post("/api/v1/telegram/discover", headers=h)
    assert r.status_code == 502 and TOKEN not in r.text


def test_viewer_cannot_manage(client, db):
    from app.core.security import hash_password
    from app.models.user import User
    db.add(User(username="viewer", password_hash=hash_password("viewerpass1"), role="viewer"))
    db.commit()
    tok = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "viewerpass1"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/v1/telegram/settings", headers=h).status_code == 403
    assert client.put("/api/v1/telegram/settings", json={"app_url": "x"}, headers=h).status_code == 403
    assert client.get("/api/v1/telegram/status", headers=h).status_code == 200
```

(Bila kolom model `User` berbeda — mis. `password` bukan `password_hash` — sesuaikan pembuatan user ke pola di `backend/tests/test_users_api.py`.)

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_telegram_api.py -q`
Expected: FAIL — 404/405 untuk `/telegram/settings`.

- [ ] **Step 3: Implementasi**

`backend/app/api/telegram.py` — ganti isi:

```python
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.db import get_db
from app.models.alert import Alert
from app.models.telegram_chat import TelegramChat
from app.services import secret_store, telegram

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])


class TelegramSettingsIn(BaseModel):
    token: str | None = Field(default=None, max_length=128)  # write-only
    chat_id: str | None = Field(default=None, max_length=64)
    chat_title: str | None = Field(default=None, max_length=128)
    app_url: str | None = Field(default=None, max_length=256)


def _settings_out(db: Session) -> dict:
    chat = telegram.active_chat(db)
    last = db.query(Alert).order_by(Alert.id.desc()).first()
    return {
        "has_token": bool(telegram.get_token()),
        "chat_id": chat.chat_id if chat else None,
        "chat_title": chat.label if chat else None,
        "app_url": telegram.app_url(db),
        "last_alert": ({"status": last.status, "error": last.error, "created_at": last.created_at}
                       if last else None),
    }


@router.get("/status")
def telegram_status(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "configured": bool(telegram.get_token()),
        "active_chats": db.query(TelegramChat).filter_by(active=True).count(),
    }


@router.get("/settings")
def get_settings(admin=Depends(require_admin), db: Session = Depends(get_db)):
    return _settings_out(db)


@router.put("/settings")
def put_settings(body: TelegramSettingsIn, admin=Depends(require_admin), db: Session = Depends(get_db)):
    if body.token is not None:
        token = body.token.strip()
        if not telegram.TOKEN_RE.fullmatch(token):
            raise HTTPException(422, "invalid token format")
        try:
            telegram.get_me(token)
        except telegram.TelegramError:
            raise HTTPException(422, "token rejected by Telegram") from None
        try:
            telegram.set_token(token)
        except secret_store.SecretStoreError:
            logger.error("telegram token store write failed")
            raise HTTPException(500, "failed to store token") from None
    fields = body.model_dump(exclude_unset=True, exclude={"token"})
    if fields.get("chat_id"):
        telegram.set_chat(db, fields["chat_id"], fields.get("chat_title") or fields["chat_id"])
    if "app_url" in fields:
        telegram.set_app_url(db, fields["app_url"])
    db.commit()
    return _settings_out(db)


@router.post("/discover")
def discover(admin=Depends(require_admin)):
    token = telegram.get_token()
    if not token:
        raise HTTPException(409, "token not configured")
    try:
        return {"chats": telegram.get_updates(token)}
    except telegram.TelegramError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post("/test")
def send_test(admin=Depends(require_admin), db: Session = Depends(get_db)):
    token = telegram.get_token()
    chat = telegram.active_chat(db)
    if not token or chat is None:
        raise HTTPException(409, "telegram not configured")
    status, error = telegram.deliver(token, chat.chat_id, telegram.TEST_TEXT, retries=1)
    return {"status": status, "error": error}
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`
Expected: semua passed (termasuk tes lama `/telegram/status`).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **API Telegram**: `GET/PUT /telegram/settings` (token write-only, validasi format + `getMe`, 422 tanpa gema token;
  grup; URL aplikasi; alert terakhir), `POST /telegram/discover` (grup dari `getUpdates`, 409/502),
  `POST /telegram/test` (1 percobaan). Admin saja; `/status` tetap. Backend **<angka> passed**.
```

```bash
git add backend/app/api/telegram.py backend/tests/test_telegram_api.py CHANGELOG.md
git commit -m "feat(telegram): API setelan bot, deteksi grup, pesan uji"
```

---

### Task 5: Tab Notifikasi

**Files:**
- Create: `frontend/src/api/telegram.ts`
- Create: `frontend/src/features/config/NotificationsPage.tsx`
- Modify: `frontend/src/features/config/ConfigurationPage.tsx`
- Modify: `frontend/src/app/i18n.tsx` (key `notifications.*`)
- Test: `frontend/src/__tests__/notifications.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: API Task 4.
- Produces: `TelegramSettings = { has_token: boolean; chat_id: string | null; chat_title: string | null; app_url: string | null; last_alert: { status: string; error: string | null; created_at: string } | null }`; fungsi `getTelegramSettings()`, `putTelegramSettings(patch)`, `discoverTelegramChats()`, `sendTelegramTest()`; tab `notifications`.

- [ ] **Step 1: Tulis tes yang gagal**

`frontend/src/__tests__/notifications.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import ConfigurationPage from '../features/config/ConfigurationPage'

const EMPTY = { has_token: false, chat_id: null, chat_title: null, app_url: null, last_alert: null }
type Call = { url: string; init?: RequestInit }

function stub(state: Record<string, unknown>) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const u = String(url)
    if (u.endsWith('/telegram/settings') && init?.method === 'PUT') {
      Object.assign(state, JSON.parse(String(init.body)), { has_token: true })
      delete state.token
      return { ok: true, status: 200, json: async () => state }
    }
    if (u.endsWith('/telegram/settings')) return { ok: true, status: 200, json: async () => state }
    if (u.endsWith('/telegram/discover')) {
      return { ok: true, status: 200, json: async () => ({ chats: [{ chat_id: '-1001', title: 'Satpam', type: 'supergroup' }] }) }
    }
    if (u.endsWith('/telegram/test')) return { ok: true, status: 200, json: async () => ({ status: 'sent', error: null }) }
    return { ok: true, status: 200, json: async () => ({ id: 1, username: 'admin', role: 'admin' }) }
  }))
  return calls
}

function renderTab() {
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=notifications']}><ConfigurationPage /></MemoryRouter></I18nProvider>)
}

test('setup flow: token, detect group, choose, test message', async () => {
  const state = { ...EMPTY }
  const calls = stub(state)
  renderTab()

  const tokenInput = await screen.findByLabelText('Token bot', { selector: 'input' })
  await userEvent.type(tokenInput, '123456:' + 'A'.repeat(35))
  await userEvent.click(screen.getByRole('button', { name: 'Simpan token' }))
  expect(await screen.findByText('Token tersimpan ✓')).toBeInTheDocument()
  const put = calls.find((c) => c.init?.method === 'PUT')
  expect(JSON.parse(String(put!.init!.body))).toEqual({ token: '123456:' + 'A'.repeat(35) })

  await userEvent.click(screen.getByRole('button', { name: 'Deteksi grup' }))
  await userEvent.click(await screen.findByLabelText('Satpam'))
  await userEvent.click(screen.getByRole('button', { name: 'Simpan grup' }))
  await waitFor(() => {
    const puts = calls.filter((c) => c.init?.method === 'PUT').map((c) => JSON.parse(String(c.init!.body)))
    expect(puts).toContainEqual({ chat_id: '-1001', chat_title: 'Satpam', app_url: window.location.origin })
  })

  await userEvent.click(screen.getByRole('button', { name: 'Kirim pesan uji' }))
  expect(await screen.findByText('Pesan uji terkirim ✓')).toBeInTheDocument()
})

test('configured state hides the token field until Ganti', async () => {
  stub({ ...EMPTY, has_token: true, chat_id: '-1001', chat_title: 'Satpam', app_url: 'http://10.0.0.1:5173',
    last_alert: { status: 'failed', error: 'Forbidden: bot was kicked', created_at: '2026-09-25T04:00:00Z' } })
  renderTab()
  expect(await screen.findByText('Token tersimpan ✓')).toBeInTheDocument()
  expect(screen.queryByLabelText('Token bot', { selector: 'input' })).not.toBeInTheDocument()
  expect(screen.getByText(/Satpam/)).toBeInTheDocument()
  expect(screen.getByText(/Forbidden: bot was kicked/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Ganti token' }))
  expect(screen.getByLabelText('Token bot', { selector: 'input' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/notifications.test.tsx`
Expected: FAIL — tab `notifications` tidak ada.

- [ ] **Step 3: Implementasi**

`frontend/src/api/telegram.ts`:

```ts
import { apiFetch } from './client'

export type TelegramSettings = {
  has_token: boolean
  chat_id: string | null
  chat_title: string | null
  app_url: string | null
  last_alert: { status: string; error: string | null; created_at: string } | null
}
export type TelegramChat = { chat_id: string; title: string; type: string }
export type TelegramSettingsPatch = { token?: string; chat_id?: string; chat_title?: string; app_url?: string | null }

async function ok<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) throw new Error(`${what} failed: ${res.status}`)
  return res.json()
}

export async function getTelegramSettings(): Promise<TelegramSettings> {
  return ok(await apiFetch('/telegram/settings'), 'telegram settings')
}

export async function putTelegramSettings(patch: TelegramSettingsPatch): Promise<TelegramSettings> {
  return ok(await apiFetch('/telegram/settings', { method: 'PUT', body: JSON.stringify(patch) }), 'save telegram settings')
}

export async function discoverTelegramChats(): Promise<TelegramChat[]> {
  return (await ok<{ chats: TelegramChat[] }>(await apiFetch('/telegram/discover', { method: 'POST' }), 'discover')).chats
}

export async function sendTelegramTest(): Promise<{ status: string; error: string | null }> {
  return ok(await apiFetch('/telegram/test', { method: 'POST' }), 'telegram test')
}
```

`frontend/src/features/config/NotificationsPage.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Button, InlineNotification, PasswordInput, RadioButton, RadioButtonGroup, TextInput } from '@carbon/react'
import { useT } from '../../app/i18n'
import {
  discoverTelegramChats, getTelegramSettings, putTelegramSettings, sendTelegramTest,
  type TelegramChat, type TelegramSettings,
} from '../../api/telegram'

// Satu grup petugas menerima alert (toggle Telegram per behavior di Zona Deteksi).
export default function NotificationsPage() {
  const { t } = useT()
  const [settings, setSettings] = useState<TelegramSettings | null>(null)
  const [token, setToken] = useState('')
  const [editingToken, setEditingToken] = useState(false)
  const [chats, setChats] = useState<TelegramChat[] | null>(null)
  const [chosen, setChosen] = useState<TelegramChat | null>(null)
  const [appUrl, setAppUrl] = useState('')
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    getTelegramSettings()
      .then((s) => {
        setSettings(s)
        setAppUrl(s.app_url ?? window.location.origin)
      })
      .catch(() => setMessage({ kind: 'error', text: t('notifications.loadError') }))
  }, [t])

  if (!settings) return null
  const showToken = !settings.has_token || editingToken

  const saveToken = async () => {
    setMessage(null)
    try {
      setSettings(await putTelegramSettings({ token: token.trim() }))
      setToken('')
      setEditingToken(false)
    } catch (e) {
      setMessage({ kind: 'error', text: t(e instanceof Error && e.message.endsWith(': 422') ? 'notifications.tokenRejected' : 'notifications.saveError') })
    }
  }

  const discover = async () => {
    setMessage(null)
    try {
      setChats(await discoverTelegramChats())
    } catch {
      setMessage({ kind: 'error', text: t('notifications.discoverError') })
    }
  }

  const saveChat = async () => {
    if (!chosen) return
    try {
      setSettings(await putTelegramSettings({ chat_id: chosen.chat_id, chat_title: chosen.title, app_url: appUrl.trim() || null }))
      setChats(null)
    } catch {
      setMessage({ kind: 'error', text: t('notifications.saveError') })
    }
  }

  const saveUrl = async () => {
    try {
      setSettings(await putTelegramSettings({ app_url: appUrl.trim() || null }))
    } catch {
      setMessage({ kind: 'error', text: t('notifications.saveError') })
    }
  }

  const test = async () => {
    setMessage(null)
    try {
      const r = await sendTelegramTest()
      setMessage(r.status === 'sent'
        ? { kind: 'success', text: t('notifications.testSent') }
        : { kind: 'error', text: `${t('notifications.testFailed')}: ${r.error ?? ''}` })
    } catch {
      setMessage({ kind: 'error', text: t('notifications.testFailed') })
    }
  }

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 20, maxWidth: 560 }}>
      <p style={{ margin: 0 }}>{t('notifications.intro')}</p>

      <div>
        <h4>{t('notifications.step1')}</h4>
        {showToken ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <PasswordInput id="tg-token" labelText={t('notifications.token')} helperText={t('notifications.tokenHint')}
              autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
            <Button size="md" disabled={!token.trim()} onClick={() => void saveToken()}>{t('notifications.saveToken')}</Button>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <span>{t('notifications.tokenSaved')}</span>
            <Button kind="ghost" size="sm" onClick={() => setEditingToken(true)}>{t('notifications.changeToken')}</Button>
          </div>
        )}
      </div>

      <div>
        <h4>{t('notifications.step2')}</h4>
        <p style={{ fontSize: 12 }}>{t('notifications.groupHint')}</p>
        {settings.chat_title && <p>{t('notifications.currentGroup')}: <strong>{settings.chat_title}</strong></p>}
        <Button kind="secondary" size="sm" disabled={!settings.has_token} onClick={() => void discover()}>
          {t('notifications.discover')}
        </Button>
        {chats && chats.length === 0 && <p style={{ fontSize: 12 }}>{t('notifications.noGroups')}</p>}
        {chats && chats.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <RadioButtonGroup legendText={t('notifications.chooseGroup')} name="tg-group" orientation="vertical"
              valueSelected={chosen?.chat_id} onChange={(v) => setChosen(chats.find((c) => c.chat_id === v) ?? null)}>
              {chats.map((c) => <RadioButton key={c.chat_id} id={`tg-${c.chat_id}`} labelText={c.title} value={c.chat_id} />)}
            </RadioButtonGroup>
            <Button size="sm" disabled={!chosen} onClick={() => void saveChat()} style={{ marginTop: 8 }}>
              {t('notifications.saveGroup')}
            </Button>
          </div>
        )}
      </div>

      <div>
        <h4>{t('notifications.step3')}</h4>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <TextInput id="tg-app-url" labelText={t('notifications.appUrl')} helperText={t('notifications.appUrlHint')}
            value={appUrl} onChange={(e) => setAppUrl(e.target.value)} />
          <Button kind="ghost" size="md" onClick={() => void saveUrl()}>{t('common.save')}</Button>
        </div>
      </div>

      <div>
        <Button kind="secondary" disabled={!settings.has_token || !settings.chat_id} onClick={() => void test()}>
          {t('notifications.test')}
        </Button>
        {settings.last_alert && (
          <p style={{ fontSize: 12, marginTop: 8 }}>
            {t('notifications.lastAlert')}: {settings.last_alert.status}
            {settings.last_alert.error ? ` — ${settings.last_alert.error}` : ''}
          </p>
        )}
      </div>

      {message && (
        <InlineNotification kind={message.kind} lowContrast title={message.text} onCloseButtonClick={() => setMessage(null)} />
      )}
    </section>
  )
}
```

`ConfigurationPage.tsx`: import `NotificationsPage`; `TABS = ['cameras', 'zones', 'detection', 'notifications', 'storage', 'nodes'] as const`; `TAB_LABEL.notifications = 'notifications.title'`; `<TabPanel>{tab === 'notifications' && <NotificationsPage />}</TabPanel>` di posisi yang sama dengan urutan `TABS`.

`i18n.tsx` — `id`:

```ts
    'notifications.title': 'Notifikasi',
    'notifications.intro': 'Alert dikirim ke satu grup Telegram petugas. Pilih kejadian yang dikirim lewat toggle Telegram di tab Zona Deteksi.',
    'notifications.step1': '1. Token bot',
    'notifications.token': 'Token bot',
    'notifications.tokenHint': 'Buat bot di @BotFather, lalu tempel token-nya di sini. Token tidak ditampilkan lagi setelah disimpan.',
    'notifications.saveToken': 'Simpan token',
    'notifications.tokenSaved': 'Token tersimpan ✓',
    'notifications.changeToken': 'Ganti token',
    'notifications.tokenRejected': 'Token ditolak Telegram — periksa lagi token dari @BotFather.',
    'notifications.step2': '2. Grup penerima',
    'notifications.groupHint': 'Tambahkan bot ke grup petugas, kirim satu pesan di grup, lalu klik Deteksi grup.',
    'notifications.currentGroup': 'Grup aktif',
    'notifications.discover': 'Deteksi grup',
    'notifications.noGroups': 'Belum ada grup terdeteksi. Pastikan bot sudah ditambahkan dan ada pesan baru di grup.',
    'notifications.chooseGroup': 'Pilih grup',
    'notifications.saveGroup': 'Simpan grup',
    'notifications.step3': '3. URL aplikasi (untuk tautan di pesan)',
    'notifications.appUrl': 'URL aplikasi',
    'notifications.appUrlHint': 'Alamat yang dibuka petugas dari LAN, mis. http://192.168.2.133:5173',
    'notifications.test': 'Kirim pesan uji',
    'notifications.testSent': 'Pesan uji terkirim ✓',
    'notifications.testFailed': 'Pesan uji gagal',
    'notifications.lastAlert': 'Alert terakhir',
    'notifications.loadError': 'Gagal memuat setelan notifikasi',
    'notifications.saveError': 'Gagal menyimpan setelan notifikasi',
    'notifications.discoverError': 'Gagal mendeteksi grup — periksa token dan koneksi internet server.',
```

`en`: terjemahan yang sama (`'notifications.title': 'Notifications'`, `'notifications.saveToken': 'Save token'`, `'notifications.tokenSaved': 'Token saved ✓'`, `'notifications.changeToken': 'Change token'`, `'notifications.discover': 'Detect groups'`, `'notifications.saveGroup': 'Save group'`, `'notifications.test': 'Send test message'`, `'notifications.testSent': 'Test message sent ✓'`, dst. — semua key di atas wajib ada).

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd frontend && npx vitest run && npx tsc -b`
Expected: semua passed. Bila tes navigasi tab di `configuration.test.tsx` bergantung pada urutan/indeks tab, sesuaikan dan sebutkan di ringkasan.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Tab Notifikasi**: token bot (write-only, "Token tersimpan ✓" + Ganti), Deteksi grup → pilih → simpan, URL
  aplikasi (default alamat browser), Kirim pesan uji, status alert terakhir. Frontend **<angka> passed**.
```

```bash
git add frontend/src/api/telegram.ts frontend/src/features/config/NotificationsPage.tsx frontend/src/features/config/ConfigurationPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/notifications.test.tsx CHANGELOG.md
git commit -m "feat(telegram): tab Notifikasi — token, grup, URL aplikasi, pesan uji"
```

---

### Task 6: Toggle Telegram di Zona Deteksi + deep-link Inbox + status `queued`

**Files:**
- Modify: `frontend/src/api/zones.ts` (`Behavior.telegram?`)
- Modify: `frontend/src/features/config/ZonesPage.tsx`
- Modify: `frontend/src/api/alerts.ts` (`AlertStatus` + `'queued'`, `AlertOut.camera_id: number | null`)
- Modify: `frontend/src/features/events/EventsPage.tsx` (`?event=`, map status `queued`)
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/zones.test.tsx`, `frontend/src/__tests__/events.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: flag `telegram` per behavior (Task 2), status `queued` (Task 2).
- Produces: toggle ber-`id` `zone-telegram-<kind>` (behavior) dan `zone-telegram-attendance` (zona absensi).

- [ ] **Step 1: Tulis tes (gagal)**

`frontend/src/__tests__/zones.test.tsx` — tambah:

```tsx
test('Telegram per behavior default off, dikirim di item behaviors; toggle zona lama hilang', async () => {
  const fetchMock = await selectZone([zoneFix({ behaviors: [{ kind: 'intrusion', trigger_seconds: 0 }] })])
  expect(document.getElementById('zone-telegram')).toBeNull()
  const tg = document.getElementById('zone-telegram-intrusion')!
  expect(tg).toHaveAttribute('aria-checked', 'false')
  fireEvent.click(tg)
  fireEvent.click(screen.getByTestId('zone-save'))
  await waitFor(() => expect(patchBody(fetchMock).behaviors).toEqual([
    { kind: 'intrusion', trigger_seconds: 0, telegram: true },
  ]))
})

test('zona absensi punya satu toggle Telegram pada behavior attendance', async () => {
  const fetchMock = await selectZone([zoneFix({ type: 'attendance', direction: 'entry',
    behaviors: [{ kind: 'attendance', trigger_seconds: 0 }] })])
  fireEvent.click(document.getElementById('zone-telegram-attendance')!)
  fireEvent.click(screen.getByTestId('zone-save'))
  await waitFor(() => expect(patchBody(fetchMock).behaviors).toEqual([
    { kind: 'attendance', trigger_seconds: 0, telegram: true },
  ]))
})
```

`frontend/src/__tests__/events.test.tsx` — tambah (pola `renderPage` file ini memakai `MemoryRouter`; tambahkan parameter `entry` ke `renderPage` bila belum ada, default `'/events'`):

```tsx
test('?event=<id> opens that event in the detail panel', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage('/events?event=2')
  await screen.findByTestId('event-detail')
  expect(screen.getByTestId('event-detail')).toHaveTextContent('loitering')
})
```

(`EVENTS[1]` ber-id 2 dan bertipe `loitering`; tanpa parameter panel memilih `EVENTS[0]` `intrusi`.)

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/zones.test.tsx src/__tests__/events.test.tsx`
Expected: FAIL — `zone-telegram-intrusion` tidak ada; detail menampilkan event pertama.

- [ ] **Step 3: Implementasi**

`frontend/src/api/zones.ts`: `Behavior` tambah `telegram?: boolean // kosong = ikut flag zona (default off)`.

`frontend/src/features/config/ZonesPage.tsx`:
- Di baris behavior, setelah toggle Clip:

```tsx
                              <Toggle
                                id={`zone-telegram-${kind}`}
                                size="sm"
                                labelText={t('zones.telegram')}
                                toggled={b.telegram ?? selected.telegram}
                                onToggle={(v) => setBehavior(kind, { telegram: v })}
                              />
```

- Di cabang `selected.type === 'attendance'`, setelah paragraf `zone-attendance-hint`:

```tsx
                  <Toggle
                    id="zone-telegram-attendance"
                    size="sm"
                    labelText={t('zones.telegram')}
                    toggled={selected.behaviors.find((b) => b.kind === 'attendance')?.telegram ?? selected.telegram}
                    onToggle={(v) => patchSelected({
                      behaviors: selected.behaviors.map((b) => (b.kind === 'attendance' ? { ...b, telegram: v } : b)),
                    })}
                  />
```

  (Bungkus paragraf + toggle dalam `<>…</>` bila perlu.)
- Hapus blok `<div>` berisi `<Toggle id="zone-telegram" … disabled />` dan `zones.telegramFase3`.

`frontend/src/api/alerts.ts`: `AlertStatus = 'queued' | 'sent' | 'failed' | 'rate_limited' | 'not_configured'`; `AlertOut.camera_id: number | null`.

`frontend/src/features/events/EventsPage.tsx`:
- Tambah entri `queued` pada `ALERT_KEY` (`'events.alert.queued'`), `ALERT_TAG` (`'ev-tag--muted'`), `ALERT_BADGE` (`'ev-badge--not_configured'`).
- `import { useSearchParams } from 'react-router-dom'`; di komponen: `const [params] = useSearchParams()` dan inisialisasi `const [selectedId, setSelectedId] = useState<number | null>(() => Number(params.get('event')) || null)`.

`frontend/src/app/i18n.tsx`:
- `id`: `'zones.telegram': 'Telegram'`, `'events.alert.queued': 'MENGIRIM…'`; hapus `zones.telegramFase3`.
- `en`: `'zones.telegram': 'Telegram'`, `'events.alert.queued': 'SENDING…'`; hapus `zones.telegramFase3`.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: semua passed; build 0; lint = set rule+file lama. Cek 390 px untuk `?tab=notifications` dan `?tab=zones` (`document.documentElement.scrollWidth <= 390`).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Zona Deteksi + Inbox**: toggle **Telegram** per behavior (default off, di samping Snapshot/Clip) dan satu toggle
  pada zona absensi; toggle level zona "tersedia di Fase 3" dihapus. Inbox mendukung `?event=<id>` (tautan caption)
  dan status alert `queued` ("MENGIRIM…"). Frontend **<angka> passed**, build 0, lint set sama.
```

```bash
git add frontend/src/api/zones.ts frontend/src/api/alerts.ts frontend/src/features/config/ZonesPage.tsx frontend/src/features/events/EventsPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/zones.test.tsx frontend/src/__tests__/events.test.tsx CHANGELOG.md
git commit -m "feat(telegram): toggle Telegram per behavior + deep-link Inbox"
```

---

### Task 7: Dokumen, suite penuh, deploy + verifikasi (langkah ⚠ butuh izin user)

**Files:**
- Modify: `README.md` (bagian alert/Telegram: cara menghubungkan bot dan grup), `ROADMAP.md`, `.env.example` (catatan `TELEGRAM_BOT_TOKEN` = fallback; `ALERT_MIN_SEVERITY` deprecated)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Dokumen**

- README: langkah (1) buat bot di @BotFather, (2) buat grup petugas dan tambahkan bot, kirim satu pesan, (3) Konfigurasi → Notifikasi: token → Deteksi grup → pilih → Kirim pesan uji, (4) Zona Deteksi: nyalakan toggle Telegram pada behavior yang ingin dikirim. Catat: foto snapshot dikirim ke server Telegram (keluar LAN); tautan klip hanya bisa dibuka dari LAN; token disimpan di `CAMERA_SECRETS_FILE` (ikut dibackup).
- `ROADMAP.md` tabel ringkasan sebelum `| E | Edge Jetson …`: `| TG | Integrasi bot Telegram (foto + caption, toggle per behavior, tab Notifikasi) | [~] lokal selesai, PENDING deploy + verifikasi | — | spec + plan 2026-09-25 | |`.
- `.env.example`: komentar di `TELEGRAM_BOT_TOKEN` "fallback; normalnya diisi dari UI Notifikasi", di `ALERT_MIN_SEVERITY` "deprecated".

- [ ] **Step 2: Suite penuh**

```bash
cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1; cd ..
backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu" | tail -1
cd frontend && npx vitest run | tail -3 && npm run build > /dev/null; echo build=$?; npm run lint | tail -2; cd ..
```

Expected: semua passed (vision tetap 204); build 0; lint set sama.

- [ ] **Step 3: Commit dokumen**

```bash
git add README.md ROADMAP.md .env.example CHANGELOG.md
git commit -m "docs(telegram): cara menghubungkan bot + grup, status TG"
```

- [ ] **Step 4 ⚠: Deploy (minta izin user dulu)**

```bash
git push -u origin feat/telegram-alerts
ssh gspe-ai3 'cd /home/gspe-ai3/project_cv/I-Sentinel && git fetch -q && git checkout -q feat/telegram-alerts && git pull -q --ff-only \
  && kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs); sleep 8; curl -s localhost:8000/api/v1/health'
```

Expected: `{"status":"ok"}`. Vision tidak di-restart (tidak berubah). Frontend Vite ikut tanpa restart.

- [ ] **Step 5: Verifikasi bersama user**

1. User membuat bot (@BotFather) + grup petugas, menambahkan bot, mengirim satu pesan di grup.
2. Tab Notifikasi: simpan token → "Token tersimpan ✓" → Deteksi grup → pilih → Simpan grup → Kirim pesan uji → pesan masuk grup.
3. Zona 15 cam 363: nyalakan Telegram pada Intrusi → berdiri di zona ≥ 2 s → foto + caption masuk grup ≤ ~5 s; tautan membuka event di Inbox (dari LAN); chip Inbox "TELEGRAM TERKIRIM".
4. Ulangi dalam `rate_limit_min` → tidak ada pesan kedua, chip "RATE-LIMITED".
5. (Bila zona absensi diaktifkan) absen tercatat dan wajah tidak dikenal terkirim; absen ulang tidak.
6. Cek server (baca-saja): `ls -l ~/.isentinel/camera-secrets.json` tetap `-rw-------`; `journalctl -u isentinel-api -n 200 | grep -c "<potongan token>"` = 0 (jangan cetak token penuh).
7. 390 px tanpa overflow; screenshot ke `docs/evidence/telegram-*.png` (sensor nama grup/pesan bila perlu).

- [ ] **Step 6: CHANGELOG + ROADMAP + commit**

Bullet "Deploy + verifikasi" dengan hasil nyata (latensi kejadian → pesan, rate-limit, attendance); ROADMAP TG → `[x]` bila user OK.

```bash
git add docs/evidence/telegram-* CHANGELOG.md ROADMAP.md
git commit -m "docs(telegram): evidence deploy + verifikasi"
```

Setelah user E2E OK: merge `--no-ff` ke `main` (butuh izin), server kembali ke `main`.
