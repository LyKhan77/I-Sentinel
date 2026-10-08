"""Pesan susulan face MQTT: pemetaan status, crop_path, unverified, saklar zona."""
import json
import uuid
from datetime import datetime, timezone

import pytest

from app.models import Alert, Camera, Event, Node, Zone
from app.services import events_consumer as ec
from app.services import face, intrusion_face
from app.services.events_consumer import handle_message

GAL = [[1.0, 0.0, 0.0, 0.0]]


@pytest.fixture
def gallery(db):
    from app.models.employee import Employee
    from app.models.face_embedding import FaceEmbedding
    e = Employee(name="Budi", employee_code="E1")
    db.add(e); db.commit(); db.refresh(e)
    db.add(FaceEmbedding(employee_id=e.id, vector=GAL[0], quality=0.9))
    db.commit()
    face.gallery._by_employee = {e.id: [GAL[0]]}
    face.gallery.employee_names = {e.id: e.name}
    return e


@pytest.fixture
def critical_event(db, monkeypatch):
    cam = Camera(name="C", host="h")
    db.add(cam); db.flush()
    zone = Zone(camera_id=cam.id, name="Server", type="behavior", polygon=[],
                severity="critical",
                behaviors=[{"kind": "intrusion", "trigger_seconds": 0, "face_id": True}])
    db.add(zone); db.flush()
    ev = Event(event_id=str(uuid.uuid4()), type="intrusion", severity="critical",
               camera_id=cam.id, zone_id=zone.id,
               ts_event=datetime.now(timezone.utc), payload={})
    db.add(ev); db.commit()
    return ev


def _msg(event_id, **over):
    p = {"event_id": event_id, "camera_id": 1, "node_id": "n1", "track_id": 1,
         "embedding": None, "quality": None, "crop_path": None,
         "stats": {"faces": 0, "rejects": {}, "frames_used": 0}}
    p.update(over)
    return p


def test_consumer_subscribes_face_topic():
    assert ("isentinel/events/face", 1) in ec.EventConsumer()._subscriptions()


def test_face_result_pops_embedding_and_never_persists_or_broadcasts_it(
        db, critical_event, gallery, monkeypatch):
    seen = []

    async def fake_broadcast(payload):
        seen.append(payload)

    monkeypatch.setattr(ec.hub, "broadcast", fake_broadcast)
    handle_message(db, ec.FACE_TOPIC, json.dumps(
        _msg(critical_event.event_id, embedding=[0.5] * 512)).encode())
    db.refresh(critical_event)
    assert "[0.5" not in json.dumps(critical_event.payload)
    assert all("[0.5" not in json.dumps(s) for s in seen)


def test_face_result_recognized_mapping(db, critical_event, gallery, monkeypatch):
    seen = []

    async def fake_broadcast(payload):
        seen.append(payload)

    monkeypatch.setattr(ec.hub, "broadcast", fake_broadcast)
    vec = [1.0, 0.0, 0.0, 0.0]
    handle_message(db, ec.FACE_TOPIC, json.dumps(
        _msg(critical_event.event_id, embedding=vec, quality=0.8)).encode())
    db.refresh(critical_event)
    f = critical_event.payload["face"]
    assert f["status"] == "recognized" and f["name"] == "Budi"
    assert f["employee_id"] == gallery.id
    assert seen and seen[0]["kind"] == "face" and seen[0]["event_id"] == critical_event.id


def test_face_result_unknown_ambiguous_not_visible_mapping(db, critical_event, gallery):
    # unknown: embedding ortogonal
    ev2 = Event(event_id=str(uuid.uuid4()), type="intrusion", severity="critical",
                camera_id=critical_event.camera_id, zone_id=critical_event.zone_id,
                ts_event=datetime.now(timezone.utc), payload={})
    db.add(ev2); db.commit()
    handle_message(db, ec.FACE_TOPIC, json.dumps(
        _msg(ev2.event_id, embedding=[0.0, 1.0, 0.0, 0.0])).encode())
    db.refresh(ev2)
    assert ev2.payload["face"]["status"] == "unknown"
    assert ev2.payload["face"]["reason"] == "no_match"

    # not_visible: tanpa embedding, rejects dominan small
    ev3 = Event(event_id=str(uuid.uuid4()), type="intrusion", severity="critical",
                camera_id=critical_event.camera_id, zone_id=critical_event.zone_id,
                ts_event=datetime.now(timezone.utc), payload={})
    db.add(ev3); db.commit()
    handle_message(db, ec.FACE_TOPIC, json.dumps(
        _msg(ev3.event_id, stats={"faces": 4, "rejects": {"small": 3}, "frames_used": 0})).encode())
    db.refresh(ev3)
    assert ev3.payload["face"]["status"] == "not_visible"
    assert ev3.payload["face"]["reason"] == "small"

    # not_visible: no_face
    ev4 = Event(event_id=str(uuid.uuid4()), type="intrusion", severity="critical",
                camera_id=critical_event.camera_id, zone_id=critical_event.zone_id,
                ts_event=datetime.now(timezone.utc), payload={})
    db.add(ev4); db.commit()
    handle_message(db, ec.FACE_TOPIC, json.dumps(
        _msg(ev4.event_id, stats={"faces": 0, "rejects": {}, "frames_used": 0})).encode())
    db.refresh(ev4)
    assert ev4.payload["face"]["status"] == "not_visible" and ev4.payload["face"]["reason"] == "no_face"


def test_face_result_quality_no_longer_blocks_matching(db, critical_event, gallery, monkeypatch):
    """Identitas diputuskan oleh ambang ketat + margin; rumus quality berbasis lebar tidak lagi menolak."""
    monkeypatch.setattr(face.settings, "face_min_quality", 0.9)
    handle_message(db, ec.FACE_TOPIC, json.dumps(
        _msg(critical_event.event_id, embedding=[1.0, 0.0, 0.0, 0.0], quality=0.2)).encode())
    db.refresh(critical_event)
    assert critical_event.payload["face"]["status"] == "recognized"


def test_face_result_unknown_event_does_not_crash(db):
    handle_message(db, ec.FACE_TOPIC, json.dumps(_msg("ev-tak-ada")).encode())


def test_duplicate_face_result_does_not_edit_twice(db, critical_event, gallery, monkeypatch):
    called = []

    def fake_sync(db_, eid):
        called.append(eid)
        return True

    monkeypatch.setattr(intrusion_face.alert_ai, "sync_face_caption", fake_sync)
    msg = _msg(critical_event.event_id, embedding=[1.0, 0.0, 0.0, 0.0])
    handle_message(db, ec.FACE_TOPIC, json.dumps(msg).encode())
    handle_message(db, ec.FACE_TOPIC, json.dumps(msg).encode())
    assert called == [critical_event.id]  # duplikat diabaikan


def test_real_result_overrides_unverified_and_resets_face_synced(db, critical_event, gallery):
    alert = Alert(event_id=critical_event.id, camera_id=critical_event.camera_id,
                  type="intrusion", severity="critical", status="sent")
    db.add(alert); db.commit()
    critical_event.payload = {"face": {"status": "unverified"}}
    db.query(Alert).filter_by(event_id=critical_event.id).update({"face_synced": True})
    db.commit()
    handle_message(db, ec.FACE_TOPIC, json.dumps(
        _msg(critical_event.event_id, embedding=[1.0, 0.0, 0.0, 0.0])).encode())
    db.expire_all()
    assert critical_event.payload["face"]["status"] == "recognized"
    assert db.query(Alert).filter_by(event_id=critical_event.id).one().face_synced is False


def test_face_result_stores_valid_crop_path_and_ignores_unsafe_ones(db, critical_event, gallery):
    handle_message(db, ec.FACE_TOPIC, json.dumps(
        _msg(critical_event.event_id, crop_path="crops/2026/10/08/x.jpg")).encode())
    db.refresh(critical_event)
    assert critical_event.payload["crop_path"] == "crops/2026/10/08/x.jpg"
    for bad in ("../x.jpg", "crops/../x.jpg", "snapshots/a.jpg", "/etc/passwd"):
        ev = Event(event_id=str(uuid.uuid4()), type="intrusion", severity="critical",
                   camera_id=critical_event.camera_id, zone_id=critical_event.zone_id,
                   ts_event=datetime.now(timezone.utc), payload={})
        db.add(ev); db.commit()
        handle_message(db, ec.FACE_TOPIC, json.dumps(
            _msg(ev.event_id, crop_path=bad)).encode())
        db.refresh(ev)
        assert ev.payload["face"]["status"] in ("not_visible",)
        assert "crop_path" not in ev.payload


def test_face_result_broadcasts_kind_face_frame(db, critical_event, gallery, monkeypatch):
    seen = []

    async def fake_broadcast(payload):
        seen.append(payload)

    monkeypatch.setattr(ec.hub, "broadcast", fake_broadcast)
    handle_message(db, ec.FACE_TOPIC, json.dumps(_msg(critical_event.event_id)).encode())
    assert seen and seen[0] == {"kind": "face", "event_id": critical_event.id,
                                "status": "not_visible"}


def test_finalize_unverified_sets_status_once_and_noops_when_face_present(db, critical_event):
    assert intrusion_face.finalize_unverified(
        critical_event.event_id, session_factory=lambda: db) is True
    db.expire_all()
    assert critical_event.payload["face"]["status"] == "unverified"
    # tidak melakukan apa-apa bila face sudah ada (hasil nyata)
    assert intrusion_face.finalize_unverified(
        critical_event.event_id, session_factory=lambda: db) is False
    assert critical_event.payload["face"]["status"] == "unverified"


def test_schedule_unverified_only_for_critical_intrusion_with_face_id(db, critical_event,
                                                                      monkeypatch):
    calls = []
    monkeypatch.setattr(intrusion_face, "schedule_unverified",
                        lambda eid: calls.append(eid))
    handle_message(db, ec.EVENTS_TOPIC, json.dumps({
        "event_id": str(uuid.uuid4()), "node_id": None, "type": "intrusion",
        "severity": "critical", "camera_id": critical_event.camera_id,
        "zone_id": critical_event.zone_id,
        "ts_event": datetime.now(timezone.utc).isoformat(), "payload": {},
    }).encode())
    assert len(calls) == 1  # critical + intrusion + face_id

    # zona warning → tidak dipanggil
    db_zone = db.get(Zone, critical_event.zone_id)
    db_zone.behaviors = [{"kind": "intrusion", "trigger_seconds": 0, "face_id": True}]
    zone_warning = Zone(camera_id=critical_event.camera_id, name="w", type="behavior",
                        polygon=[], severity="warning",
                        behaviors=[{"kind": "intrusion", "trigger_seconds": 0, "face_id": True}])
    db.add(zone_warning); db.commit()
    handle_message(db, ec.EVENTS_TOPIC, json.dumps({
        "event_id": str(uuid.uuid4()), "node_id": None, "type": "intrusion",
        "severity": "critical", "camera_id": critical_event.camera_id,
        "zone_id": zone_warning.id,
        "ts_event": datetime.now(timezone.utc).isoformat(), "payload": {},
    }).encode())
    assert len(calls) == 1

    # saklar mati → tidak dipanggil
    db_zone = db.get(Zone, critical_event.zone_id)
    db_zone.behaviors = [{"kind": "intrusion", "trigger_seconds": 0, "face_id": False}]
    db.commit()
    handle_message(db, ec.EVENTS_TOPIC, json.dumps({
        "event_id": str(uuid.uuid4()), "node_id": None, "type": "intrusion",
        "severity": "critical", "camera_id": critical_event.camera_id,
        "zone_id": critical_event.zone_id,
        "ts_event": datetime.now(timezone.utc).isoformat(), "payload": {},
    }).encode())
    assert len(calls) == 1


# --- pembaruan progresif: hasil lebih baik menimpa, tidak pernah menurun -------------------

UNKNOWN_LOW = [0.30, 0.9539392, 0.0, 0.0]   # cosine 0,30 ke galeri: di bawah ambang -> unknown
UNKNOWN_HIGH = [0.45, 0.8930286, 0.0, 0.0]  # cosine 0,45: masih unknown, skor lebih tinggi
MATCH = [1.0, 0.0, 0.0, 0.0]


def _send(db, event, **over):
    handle_message(db, ec.FACE_TOPIC, json.dumps(_msg(event.event_id, **over)).encode())
    db.expire_all()


def _count_syncs(monkeypatch):
    called = []
    monkeypatch.setattr(intrusion_face.alert_ai, "sync_face_caption",
                        lambda db_, eid: called.append(eid) or True)
    return called


def test_better_result_replaces_a_worse_one_and_edits_the_caption_again(
        db, critical_event, gallery, monkeypatch):
    called = _count_syncs(monkeypatch)
    _send(db, critical_event, embedding=UNKNOWN_LOW, crop_path="crops/2026/10/08/a.jpg", seq=0)
    assert critical_event.payload["face"]["status"] == "unknown"
    _send(db, critical_event, embedding=MATCH, crop_path="crops/2026/10/08/b.jpg", seq=1)
    assert critical_event.payload["face"]["status"] == "recognized"
    assert critical_event.payload["crop_path"] == "crops/2026/10/08/b.jpg"  # crop mengikuti hasil terbaik
    assert called == [critical_event.id, critical_event.id]


def test_a_worse_result_never_downgrades_a_recognized_one(db, critical_event, gallery, monkeypatch):
    called = _count_syncs(monkeypatch)
    _send(db, critical_event, embedding=MATCH, crop_path="crops/2026/10/08/a.jpg", seq=0)
    _send(db, critical_event, embedding=UNKNOWN_LOW, crop_path="crops/2026/10/08/b.jpg", seq=1)
    _send(db, critical_event, embedding=None, seq=2)  # tanpa wajah
    assert critical_event.payload["face"]["status"] == "recognized"
    assert critical_event.payload["crop_path"] == "crops/2026/10/08/a.jpg"
    assert called == [critical_event.id]


def test_same_status_with_a_higher_score_updates_the_payload_without_a_second_edit(
        db, critical_event, gallery, monkeypatch):
    called = _count_syncs(monkeypatch)
    _send(db, critical_event, embedding=UNKNOWN_LOW, seq=0)
    _send(db, critical_event, embedding=UNKNOWN_HIGH, crop_path="crops/2026/10/08/b.jpg", seq=1)
    assert critical_event.payload["face"]["score"] == pytest.approx(0.45, abs=1e-3)
    assert critical_event.payload["crop_path"] == "crops/2026/10/08/b.jpg"
    assert called == [critical_event.id]  # teks caption sama: tanpa edit kedua
    _send(db, critical_event, embedding=UNKNOWN_LOW, seq=2)  # skor lebih rendah: diabaikan
    assert critical_event.payload["face"]["score"] == pytest.approx(0.45, abs=1e-3)


def test_not_visible_is_upgraded_when_a_face_finally_shows_up(db, critical_event, gallery, monkeypatch):
    called = _count_syncs(monkeypatch)
    _send(db, critical_event, embedding=None, seq=0)
    assert critical_event.payload["face"]["status"] == "not_visible"
    _send(db, critical_event, embedding=UNKNOWN_LOW, seq=1)
    assert critical_event.payload["face"]["status"] == "unknown"
    assert called == [critical_event.id, critical_event.id]
