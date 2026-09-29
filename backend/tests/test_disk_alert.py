import time
from datetime import datetime, timedelta, timezone

from app.models.setting import Setting
from app.services import disk_alert, storage_settings

T0 = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)
GB = 1024 ** 3


def test_alert_once_repeat_after_24h_and_recover(db):
    storage_settings.put(db, {"disk_alert_percent": 85})
    sent = []
    send = lambda db, text: sent.append(text) or True
    check = lambda now, pct: disk_alert.check(db, now=now, percent=pct, free_bytes=50 * GB, send=send)
    assert check(T0, 80.0) is None
    assert check(T0, 86.0) == "alert" and "86" in sent[-1] and "85" in sent[-1]
    assert check(T0 + timedelta(hours=23), 90.0) is None               # belum 24 jam
    assert check(T0 + timedelta(hours=24, minutes=1), 90.0) == "alert"  # pengingat harian
    assert check(T0 + timedelta(hours=25), 84.0) is None               # di atas ambang − 2 → belum pulih
    assert check(T0 + timedelta(hours=26), 82.0) == "recovered" and "82" in sent[-1]
    assert len(sent) == 3
    assert check(T0 + timedelta(hours=27), 86.0) == "alert"            # lewat lagi → kirim lagi


def test_without_telegram_state_kept_and_sent_later(db):
    storage_settings.put(db, {"disk_alert_percent": 85})
    assert disk_alert.check(db, now=T0, percent=95.0, free_bytes=GB, send=lambda db, t: False) is None
    state = db.get(Setting, disk_alert.STATE_KEY).value
    assert state["over"] is True and state["last_sent_at"] is None
    got = []
    assert disk_alert.check(db, now=T0 + timedelta(minutes=10), percent=95.0, free_bytes=GB,
                            send=lambda db, t: got.append(t) or True) == "alert"
    assert got


def test_default_send_skips_when_telegram_not_configured(db, monkeypatch):
    from app.services import telegram
    monkeypatch.setattr(telegram, "get_token", lambda: "")
    called = []
    monkeypatch.setattr(telegram, "deliver", lambda *a, **k: called.append(a) or ("sent", None))
    assert disk_alert._send(db, "x") is False and called == []


def test_monitor_runs_check_and_stops(monkeypatch):
    calls = []
    monkeypatch.setattr(disk_alert, "check", lambda db: calls.append(db))

    class FakeSession:
        def close(self):
            pass

    m = disk_alert.DiskAlertMonitor(interval_s=0.01, session_factory=FakeSession)
    m.start()
    time.sleep(0.1)
    m.stop()
    assert calls and not m._thread.is_alive()


def test_monitor_start_twice_keeps_single_loop(monkeypatch):
    monkeypatch.setattr(disk_alert, "check", lambda db: None)

    class FakeSession:
        def close(self):
            pass

    m = disk_alert.DiskAlertMonitor(interval_s=5, session_factory=FakeSession)
    m.start()
    first = m._thread
    m.start()  # stop() boleh saja kehabisan join timeout — start() tidak boleh menggandakan loop
    assert m._thread is first and first.is_alive()
    m.stop()
