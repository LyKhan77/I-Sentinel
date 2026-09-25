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


def _zone(db, behaviors, telegram=False, rate_limit_min=2, type="behavior", direction=None):
    cam = Camera(name=f"cam-{uuid.uuid4().hex[:6]}", host="1.2.3.4")
    db.add(cam)
    db.commit()
    zone = Zone(camera_id=cam.id, name="z", type=type, direction=direction, polygon=POLY,
                behaviors=behaviors, telegram=telegram, rate_limit_min=rate_limit_min)
    db.add(zone)
    db.commit()
    return cam, zone


def _event(db, cam, zone, type="intrusion", payload=None, severity="warning", track=None):
    event_payload = dict(payload or {})
    if track is not None:
        event_payload["track_id"] = track
    ev = Event(type=type, camera_id=cam.id, zone_id=zone.id if zone else None, severity=severity,
               payload=event_payload, ts_event=NOW)
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


def test_behavior_same_track_rate_limited_for_two_minutes(db, queued):
    cam, zone = _zone(db, INTRUSION_ON)
    first = alerting.handle(db, _event(db, cam, zone, track=1), now=NOW)
    second = alerting.handle(db, _event(db, cam, zone, track=1), now=NOW + timedelta(seconds=90))
    third = alerting.handle(db, _event(db, cam, zone, track=1), now=NOW + timedelta(seconds=150))
    assert (first.status, second.status, third.status) == ("queued", "rate_limited", "queued")
    assert queued == [first.id, third.id]


def test_behavior_different_tracks_queue_independently(db, queued):
    cam, zone = _zone(db, INTRUSION_ON)
    first = alerting.handle(db, _event(db, cam, zone, track=1), now=NOW)
    second = alerting.handle(db, _event(db, cam, zone, track=2), now=NOW + timedelta(seconds=5))
    assert (first.status, second.status) == ("queued", "queued")
    assert queued == [first.id, second.id]
    assert len(queued) == 2


def test_critical_behavior_same_track_always_queues(db, queued):
    cam, zone = _zone(db, INTRUSION_ON)
    alerts = [
        alerting.handle(db, _event(db, cam, zone, severity="critical", track=1),
                        now=NOW + timedelta(seconds=offset))
        for offset in (0, 5, 10)
    ]
    assert [alert.status for alert in alerts] == ["queued", "queued", "queued"]
    assert queued == [alert.id for alert in alerts]


def test_missing_track_ids_share_rate_limit_bucket(db, queued):
    cam, zone = _zone(db, INTRUSION_ON, rate_limit_min=0)
    first = alerting.handle(db, _event(db, cam, zone, severity="info"), now=NOW)
    second = alerting.handle(db, _event(db, cam, zone, severity="info"),
                             now=NOW + timedelta(seconds=30))
    assert (first.status, second.status) == ("queued", "rate_limited")
    assert queued == [first.id]


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


def test_unknown_face_rate_limit_per_track_separate_from_matched(db, queued):
    cam, zone = _zone(db, GATE_ON, type="attendance", direction="entry")
    matched = _event(db, cam, zone, type="attendance", severity="info",
                     payload={"match_reason": "matched", "employee_id": 1})
    matched_alert = alerting.handle(db, matched, now=NOW)
    first = alerting.handle(
        db, _event(db, cam, zone, type="attendance", severity="info",
                   payload={"match_reason": "no_match"}, track=1), now=NOW,
    )
    again = alerting.handle(
        db, _event(db, cam, zone, type="attendance", severity="info",
                   payload={"match_reason": "no_match"}, track=1), now=NOW + timedelta(seconds=30),
    )
    different = alerting.handle(
        db, _event(db, cam, zone, type="attendance", severity="info",
                   payload={"match_reason": "no_match"}, track=2), now=NOW + timedelta(seconds=40),
    )
    assert (matched_alert.status, first.type, first.status, again.status, different.status) == (
        "queued", "attendance_unknown", "queued", "rate_limited", "queued"
    )
    assert queued == [matched_alert.id, first.id, different.id]


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


def test_genuine_negative_writes_no_row(db, queued):
    """telegram_off/no_zone = NOL baris, bukan baris rate_limited (badge Inbox)."""
    cam, zone = _zone(db, [{"kind": "intrusion", "trigger_seconds": 0, "telegram": False}])
    assert alerting.handle(db, _event(db, cam, zone), now=NOW) is None
    assert alerting.handle(db, _event(db, cam, None), now=NOW) is None
    assert db.query(Alert).count() == 0 and queued == []
