import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from app.core.config import settings
from app.models import Camera, Zone
from app.models.alert import Alert
from app.models.employee import Employee
from app.models.node import Node
from app.services import attendance, events_consumer as ec, face
from app.services.events_consumer import handle_message
from app.ws.hub import hub


def _event(node_id=None, **over):
    data = {
        "event_id": str(uuid.uuid4()),
        "type": "intrusion",
        "severity": "critical",
        "ts_event": datetime.now(timezone.utc).isoformat(),
    }
    if node_id is not None:
        data["node_id"] = node_id
    data.update(over)
    return data


@pytest.fixture
def broadcast(monkeypatch):
    sent = []
    async def fake_broadcast(payload):
        sent.append(payload)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    return sent


def test_valid_event_ingests_and_broadcasts(db, broadcast):
    handle_message(db, "isentinel/events", json.dumps(_event()).encode())
    assert db.query(ec.Event).count() == 1
    assert len(broadcast) == 1
    assert broadcast[0]["type"] == "intrusion"


def test_malformed_payload_no_raise_no_row(db, broadcast):
    handle_message(db, "isentinel/events", b"{not json")
    assert db.query(ec.Event).count() == 0
    assert broadcast == []


def test_invalid_event_no_raise_no_row(db, broadcast):
    # missing required fields (no event_id) -> validation error, swallowed
    handle_message(db, "isentinel/events", b'{"type":"intrusion"}')
    assert db.query(ec.Event).count() == 0
    assert broadcast == []


def test_lwt_offline_marks_node_once(db, broadcast, monkeypatch):
    from app.services import telegram
    monkeypatch.setattr(telegram, "send_text", lambda db, t: True)
    db.add(Node(name="server", status="online"))
    db.commit()
    handle_message(db, "isentinel/nodes/server/lwt", b'{"status":"offline"}')
    handle_message(db, "isentinel/nodes/server/lwt", b'{"status":"offline"}')  # retained dikirim ulang
    node = db.query(Node).filter_by(name="server").one()
    assert node.status == "offline"
    ev = db.query(ec.Event).one()
    assert ev.type == "system" and ev.severity == "warning"
    assert ev.payload == {"node": "server", "reason": "lwt"}
    assert broadcast and broadcast[-1]["type"] == "system"


def test_lwt_online_payload_ignored(db, broadcast):
    db.add(Node(name="server", status="online"))
    db.commit()
    handle_message(db, "isentinel/nodes/server/lwt", b'{"status":"online"}')
    handle_message(db, "isentinel/nodes/server/lwt", b"")  # retained dihapus
    assert db.query(Node).filter_by(name="server").one().status == "online"
    assert db.query(ec.Event).count() == 0


def test_heartbeat_after_offline_emits_recovered_and_stores_runtime(db, broadcast, monkeypatch):
    from app.services import telegram
    monkeypatch.setattr(telegram, "send_text", lambda db, t: True)
    db.add(Node(name="vision-1", status="offline"))
    db.commit()
    hb = {"ts": datetime.now(timezone.utc).isoformat(), "mqtt_backlog": 2,
          "cameras": [{"id": 3, "worker": "detect", "state": "streaming", "fps": 5.0}],
          "hw": {"gpus": [], "host": {"cpu_pct": 10.0}},
          "modules": {"detector": {"device": "auto", "model": "m"}}}
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    node = db.query(Node).filter_by(name="vision-1").one()
    assert node.status == "online"
    assert node.modules["cameras"][0]["state"] == "streaming" and node.modules["mqtt_backlog"] == 2
    assert node.hw["host"]["cpu_pct"] == 10.0
    [ev] = db.query(ec.Event).all()
    assert ev.payload == {"node": "vision-1", "reason": "online"}


def test_heartbeat_legacy_camera_ids_normalized(db, broadcast):
    db.add(Node(name="vision-1"))
    db.commit()
    hb = {"ts": "x", "cameras": [1, 2], "modules": {"detector": {"device": "auto"}}}
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    node = db.query(Node).filter_by(name="vision-1").one()
    assert node.modules["cameras"] == [{"id": 1}, {"id": 2}]


def test_heartbeat_without_cameras_key_does_not_mark_not_running(db, broadcast):
    """Heartbeat tanpa key cameras (vision lama/HTTP) tidak boleh menulis daftar kosong."""
    db.add(Node(name="vision-1"))
    db.commit()
    hb = {"ts": "x", "modules": {"detector": {"device": "auto"}}}
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    node = db.query(Node).filter_by(name="vision-1").one()
    assert "cameras" not in node.modules


def test_duplicate_event_id_no_error_no_double_row(db, broadcast):
    payload = json.dumps(_event()).encode()
    handle_message(db, "isentinel/events", payload)
    handle_message(db, "isentinel/events", payload)
    assert db.query(ec.Event).count() == 1


def test_heartbeat_saves_hw_and_modules(db, broadcast):
    db.add(Node(name="vision-1"))
    db.commit()
    hb = {"ts": datetime.now(timezone.utc).isoformat(), "cpu_percent": 5.0,
          "cameras": [1, 2],
          "hw": {"gpus": [{"idx": 0, "name": "RTX 4090", "vram_used_mb": 900,
                           "vram_total_mb": 24564, "util_pct": 10, "processes": []}]},
          "modules": {"detector": {"device": "cuda:0", "model": "yolo26s.engine"}}}
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    node = db.query(Node).filter_by(name="vision-1").one()
    assert node.hw["gpus"][0]["name"] == "RTX 4090"
    assert node.modules["detector"]["device"] == "cuda:0"


def test_heartbeat_without_hw_backward_compatible(db, broadcast):
    db.add(Node(name="vision-1"))
    db.commit()
    hb = {"ts": datetime.now(timezone.utc).isoformat(), "cpu_percent": 5.0, "cameras": []}
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    node = db.query(Node).filter_by(name="vision-1").one()
    assert node.status == "online"
    assert node.hw is None and node.modules is None


def test_heartbeat_bad_hw_shape_ignored(db, broadcast):
    db.add(Node(name="vision-1"))
    db.commit()
    handle_message(db, "isentinel/nodes/vision-1/heartbeat",
                   json.dumps({"ts": "x", "hw": "junk"}).encode())
    node = db.query(Node).filter_by(name="vision-1").one()
    assert node.hw is None and node.status == "online"


def test_heartbeat_records_history(db, broadcast):
    from app.services import monitoring_history as mh
    db.add(Node(name="vision-1", status="online"))
    db.commit()
    hb = {"ts": "x", "hw": {"host": {"cpu_pct": 42.0}, "gpus": []},
          "modules": {"detector": {"ms_avg": 7.0}}, "cameras": [], "mqtt_backlog": 0}
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps({"ts": "x"}).encode())  # format lama
    node = db.query(Node).filter_by(name="vision-1").one()
    rows = mh.flush(datetime.now(timezone.utc) + timedelta(minutes=2))
    assert [(n, d["cpu_pct"]["avg"]) for n, _, d in rows] == [(node.id, 42.0)]


# --- R3: relay detections topic → WS -----------------------------------------

DETECTIONS_TOPIC = "isentinel/detections/test-node"


def test_detections_relayed_to_hub(db, broadcast):
    payload = json.dumps({"camera_id": 7, "boxes": [
        {"id": 1, "bbox_norm": [0.1, 0.1, 0.5, 0.6]}]}).encode()
    handle_message(db, DETECTIONS_TOPIC, payload)
    assert broadcast == [{
        "type": "detections", "camera_id": 7,
        "boxes": [{"id": 1, "bbox_norm": [0.1, 0.1, 0.5, 0.6]}],
    }]


def test_detections_malformed_no_raise_no_broadcast(db, broadcast):
    handle_message(db, DETECTIONS_TOPIC, b"not-json")
    assert broadcast == []


def test_attendance_embedding_never_persisted_or_broadcast_when_matching_fails(db, broadcast, monkeypatch):
    """Embedding biometrik tidak boleh sampai ke tabel event/WS, bahkan saat match melempar error
    (dulu: ingest commit payload ber-embedding, rollback menyisakannya permanen)."""
    from app.models.event import Event
    from app.services import attendance
    seen = {}

    def boom(vector, quality=None, policy=None):
        seen["len"] = len(vector)
        raise RuntimeError("matcher down")

    monkeypatch.setattr(attendance.face, "match_vector", boom)
    ev = _event(type="attendance", severity="info",
                payload={"direction": "entry", "embedding": [0.1] * 512, "face_quality": 0.8})
    handle_message(db, "isentinel/events", json.dumps(ev).encode())

    assert seen["len"] == 512                       # matcher tetap menerima embedding
    row = db.query(Event).filter_by(event_id=ev["event_id"]).one()
    assert "embedding" not in (row.payload or {})
    assert all("embedding" not in (m.get("payload") or {}) for m in broadcast)


def test_caption_hook_new_snapshot_and_media(db, broadcast, monkeypatch):
    from app.services.ai_worker import worker
    calls = []
    monkeypatch.setattr(worker, "maybe_enqueue_caption", lambda session, ev: calls.append(ev.id))
    data = _event(snapshot_path="snapshots/synthetic.jpg")
    handle_message(db, ec.EVENTS_TOPIC, json.dumps(data).encode())
    ev = db.query(ec.Event).one()
    assert calls == [ev.id] and len(broadcast) == 1
    handle_message(db, ec.MEDIA_TOPIC, json.dumps({"event_id": ev.event_id, "snapshot_path": "snapshots/next.jpg"}).encode())
    assert calls == [ev.id, ev.id] and ev.snapshot_path == "snapshots/next.jpg"


def test_caption_hook_failure_does_not_stop_alerting_or_broadcast(db, broadcast, monkeypatch):
    from app.services.ai_worker import worker
    from app.models.alert import Alert
    from app.models import Camera, Zone
    from app.services.alert_dispatcher import dispatcher
    cam = Camera(name="CAM-hook", host="camera.test")
    db.add(cam); db.commit()
    zone = Zone(camera_id=cam.id, name="Area", type="behavior", polygon=[],
                behaviors=[{"kind": "intrusion", "telegram": True}])
    db.add(zone); db.commit()
    monkeypatch.setattr(dispatcher, "enqueue", lambda aid: True)
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic worker failure")
    monkeypatch.setattr(worker, "maybe_enqueue_caption", fail)
    handle_message(db, ec.EVENTS_TOPIC, json.dumps(_event(camera_id=cam.id, zone_id=zone.id,
                                                       snapshot_path="snapshots/test.jpg")).encode())
    assert db.query(ec.Event).count() == 1
    assert db.query(Alert).count() == 1
    assert broadcast[-1]["type"] == "intrusion" and broadcast[0]["kind"] == "alert"


# --- Tujuan wajah tidak dikenal: zona `none` membuang event ------------------

def _jpeg(path) -> None:
    """Berkas JPEG kecil yang benar-benar bisa dibaca `annotate_snapshot` (corrupt = warning)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), (120, 120, 120)).save(path, "JPEG")


@pytest.fixture
def media(tmp_path, monkeypatch):
    """`storage_root` bersih + crop/snapshot nyata untuk satu event."""
    root = tmp_path / "root"
    monkeypatch.setattr(settings, "storage_root", str(root))
    _jpeg(root / "crops" / "a.jpg")
    _jpeg(root / "snapshots" / "a.jpg")
    return root


def _attendance_zone(db, behaviors):
    cam = Camera(name=f"cam-{uuid.uuid4().hex[:6]}", host="1.2.3.4")
    db.add(cam)
    db.commit()
    zone = Zone(camera_id=cam.id, name="z", type="attendance", direction="entry",
                polygon=[[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]], behaviors=behaviors)
    db.add(zone)
    db.commit()
    return cam, zone


def _unknown_zone(db):
    return _attendance_zone(db, [{"kind": "attendance", "trigger_seconds": 0, "unknown_delivery": "none"}])


def _face_event(cam, zone, **over):
    """Event absensi lengkap: embedding + crop di payload, snapshot di baris event."""
    data = _event(camera_id=cam.id, zone_id=zone.id, type="attendance", severity="info",
                  snapshot_path="snapshots/a.jpg",
                  payload={"direction": "entry", "embedding": [0.1] * 512, "face_quality": 0.9,
                           "crop_path": "crops/a.jpg"})
    data.update(over)
    return data


def _match(monkeypatch, result):
    monkeypatch.setattr(face, "match_vector", lambda vector, quality=None, policy=None: result)


@pytest.mark.parametrize("reason", ["no_match", "ambiguous", "low_quality"])
def test_unknown_face_dropped_when_zone_none(db, broadcast, media, monkeypatch, reason):
    from app.services.ai_worker import worker
    captions = []
    monkeypatch.setattr(worker, "maybe_enqueue_caption", lambda session, ev: captions.append(ev.id))
    cam, zone = _unknown_zone(db)
    _match(monkeypatch, face.MatchResult(None, 0.2, 0.9, reason))

    handle_message(db, ec.EVENTS_TOPIC, json.dumps(_face_event(cam, zone)).encode())

    assert db.query(ec.Event).count() == 0
    assert db.query(Alert).count() == 0
    assert broadcast == []
    assert captions == []
    assert not (media / "crops" / "a.jpg").exists()
    assert not (media / "snapshots" / "a.jpg").exists()


@pytest.mark.parametrize("behavior", [{"unknown_delivery": "inbox"}, {"unknown_delivery": "all"}, {}])
def test_unknown_face_kept_for_inbox_all_or_unset(db, broadcast, media, monkeypatch, behavior):
    cam, zone = _attendance_zone(db, [{"kind": "attendance", "trigger_seconds": 0, **behavior}])
    _match(monkeypatch, face.MatchResult(None, 0.2, 0.9, "no_match"))

    handle_message(db, ec.EVENTS_TOPIC, json.dumps(_face_event(cam, zone)).encode())

    assert db.query(ec.Event).count() == 1
    assert len(broadcast) == 1
    assert (media / "crops" / "a.jpg").exists()
    assert (media / "snapshots" / "a.jpg").exists()


def test_recognized_and_anomalous_events_never_dropped(db, broadcast, media, monkeypatch):
    cam, zone = _unknown_zone(db)
    emp = Employee(name="Budi", employee_code="E1")
    db.add(emp)
    db.commit()
    _match(monkeypatch, face.MatchResult(emp.id, 0.9, 0.9, "matched"))

    handle_message(db, ec.EVENTS_TOPIC, json.dumps(_face_event(cam, zone)).encode())
    assert db.query(ec.Event).count() == 1  # dikenali: tidak pernah dibuang

    bare = _face_event(cam, zone, snapshot_path=None, payload={"direction": "entry"})
    handle_message(db, ec.EVENTS_TOPIC, json.dumps(bare).encode())
    assert db.query(ec.Event).count() == 2  # tanpa embedding dan crop: anomali

    sideways = _face_event(cam, zone, payload={"direction": "sideways", "embedding": [0.1] * 512,
                                              "face_quality": 0.9, "crop_path": "crops/a.jpg"})
    handle_message(db, ec.EVENTS_TOPIC, json.dumps(sideways).encode())
    assert db.query(ec.Event).count() == 3  # arah tidak valid: anomali


def test_failed_match_event_not_dropped(db, broadcast, media, monkeypatch):
    cam, zone = _unknown_zone(db)

    def boom(vector, quality=None, policy=None):
        raise RuntimeError("matcher down")

    monkeypatch.setattr(face, "match_vector", boom)
    handle_message(db, ec.EVENTS_TOPIC, json.dumps(_face_event(cam, zone)).encode())

    assert db.query(ec.Event).count() == 1


def test_unsafe_media_path_not_deleted(db, broadcast, tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(settings, "storage_root", str(root))
    outside = tmp_path / "outside.jpg"
    _jpeg(outside)
    cam, zone = _unknown_zone(db)
    _match(monkeypatch, face.MatchResult(None, 0.2, 0.9, "no_match"))

    data = _face_event(cam, zone, snapshot_path=None,
                       payload={"direction": "entry", "embedding": [0.1] * 512, "face_quality": 0.9,
                                "crop_path": "../outside.jpg"})
    handle_message(db, ec.EVENTS_TOPIC, json.dumps(data).encode())

    assert db.query(ec.Event).count() == 0
    assert outside.exists()


def test_late_media_for_dropped_event(db, broadcast, media, monkeypatch, caplog):
    cam, zone = _unknown_zone(db)
    _match(monkeypatch, face.MatchResult(None, 0.2, 0.9, "no_match"))
    data = _face_event(cam, zone)

    handle_message(db, ec.EVENTS_TOPIC, json.dumps(data).encode())
    assert db.query(ec.Event).count() == 0
    late = media / "snapshots" / "late.jpg"
    _jpeg(late)

    caplog.clear()
    handle_message(db, ec.MEDIA_TOPIC, json.dumps(
        {"event_id": data["event_id"], "snapshot_path": "snapshots/late.jpg"}).encode())
    assert not late.exists()
    assert [r for r in caplog.records if "media update for unknown event" in r.getMessage()] == []

    caplog.clear()
    handle_message(db, ec.MEDIA_TOPIC, json.dumps(
        {"event_id": str(uuid.uuid4()), "snapshot_path": "snapshots/late.jpg"}).encode())
    assert any("media update for unknown event" in r.getMessage() for r in caplog.records)


def test_duplicate_unknown_event_dropped_twice(db, broadcast, media, monkeypatch):
    cam, zone = _unknown_zone(db)
    _match(monkeypatch, face.MatchResult(None, 0.2, 0.9, "no_match"))
    payload = json.dumps(_face_event(cam, zone)).encode()

    handle_message(db, ec.EVENTS_TOPIC, payload)
    handle_message(db, ec.EVENTS_TOPIC, payload)

    assert db.query(ec.Event).count() == 0
    assert broadcast == []


def test_unified_policy_event_dropped_with_real_matcher(db, broadcast, media):
    """Jalur produksi: `payload.policy == "unified"` → `match_strict` asli (galeri kosong → `no_match`)."""
    cam, zone = _unknown_zone(db)
    data = _face_event(cam, zone)
    data["payload"]["policy"] = "unified"

    handle_message(db, ec.EVENTS_TOPIC, json.dumps(data).encode())

    assert db.query(ec.Event).count() == 0
    assert broadcast == []
    assert not (media / "crops" / "a.jpg").exists()
    assert not (media / "snapshots" / "a.jpg").exists()


def test_clip_of_dropped_event_is_never_deleted(db, broadcast, media, monkeypatch):
    """Klip insiden dipakai bersama banyak event: membuang satu event absensi tidak boleh menghapusnya."""
    shared = media / "clips" / "shared.mp4"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(b"clip")
    cam, zone = _unknown_zone(db)
    _match(monkeypatch, face.MatchResult(None, 0.2, 0.9, "no_match"))
    data = _face_event(cam, zone, clip_path="clips/shared.mp4")

    handle_message(db, ec.EVENTS_TOPIC, json.dumps(data).encode())
    assert db.query(ec.Event).count() == 0
    assert not (media / "snapshots" / "a.jpg").exists()  # media miliknya sendiri tetap dihapus
    assert shared.exists()

    handle_message(db, ec.MEDIA_TOPIC, json.dumps(
        {"event_id": data["event_id"], "clip_path": "clips/shared.mp4"}).encode())
    assert shared.exists()
