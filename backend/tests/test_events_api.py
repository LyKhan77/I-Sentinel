import pytest
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db

@pytest.fixture

def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "node_api_key", "test-node-key")
    # _payload() hardcodes camera_id=1 — seed the parent row (FK enforced)
    from app.models.camera import Camera
    db.add(Camera(id=1, name="cam1", host="1.2.3.4")); db.commit()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}

def _ingest_headers():
    return {"Authorization": "Bearer test-node-key"}

def _payload(**kw):
    from datetime import datetime, timezone, timedelta
    ts = datetime.now(timezone.utc).isoformat()
    p = {"event_id": str(uuid.uuid4()), "type": "intrusion", "camera_id": 1,
         "ts_event": ts, "payload": {"x": 1}}
    p.update(kw)
    return p

def test_ingest_without_api_key_401(client):
    assert client.post("/internal/nodes/1/events", json=_payload()).status_code == 401

def test_ingest_bad_api_key_401(client):
    r = client.post("/internal/nodes/1/events", json=_payload(), headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401

def test_ingest_created_then_duplicate(client):
    body = _payload()
    r1 = client.post("/internal/nodes/1/events", json=body, headers=_ingest_headers())
    assert r1.status_code == 200
    assert r1.json()["status"] == "created" and r1.json()["id"] > 0
    r2 = client.post("/internal/nodes/1/events", json=body, headers=_ingest_headers())
    assert r2.status_code == 200 and r2.json()["status"] == "duplicate"

def test_ingest_dedup_key_collision_returns_existing_id(client):
    dedup = "node1-cam1-2024"
    r1 = client.post("/internal/nodes/1/events", json=_payload(dedup_key=dedup), headers=_ingest_headers())
    assert r1.status_code == 200 and r1.json()["status"] == "created"
    id_a = r1.json()["id"]
    r2 = client.post("/internal/nodes/1/events", json=_payload(dedup_key=dedup), headers=_ingest_headers())
    assert r2.status_code == 200 and r2.json()["status"] == "duplicate"
    assert r2.json()["id"] == id_a

def test_ingest_validates_uuid(client):
    r = client.post("/internal/nodes/1/events", json=_payload(event_id="not-a-uuid"), headers=_ingest_headers())
    assert r.status_code == 422

def test_ingest_validates_type(client):
    r = client.post("/internal/nodes/1/events", json=_payload(type="weird"), headers=_ingest_headers())
    assert r.status_code == 422

def test_new_behaviors_ingest_via_internal_api_and_mqtt(client, db):
    import json
    from app.services.events_consumer import handle_message
    from app.models.event import Event
    for kind in ("idle_zone", "crowd"):
        payload = _payload(type=kind, payload={"reminder": 0})
        res = client.post("/internal/nodes/1/events", json=payload, headers=_ingest_headers())
        assert res.status_code == 200 and res.json()["status"] == "created"
        mqtt = _payload(type=kind, payload={"reminder": 1})
        handle_message(db, "isentinel/events", json.dumps(mqtt).encode())
        assert db.query(Event).filter_by(event_id=mqtt["event_id"]).one().type == kind


def test_ingest_unknown_node_still_ok(client):
    r = client.post("/internal/nodes/999/events", json=_payload(), headers=_ingest_headers())
    assert r.status_code == 200 and r.json()["status"] == "created"

def test_ingest_updates_node_last_seen(client, db):
    from app.models.node import Node
    r = client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Node, 1).last_seen is not None

def test_list_events_requires_auth(client):
    assert client.get("/api/v1/events").status_code == 401

def test_list_events_filter_type(client):
    client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
    client.post("/internal/nodes/1/events", json=_payload(type="loitering"), headers=_ingest_headers())
    h = _admin_headers(client)
    all_events = client.get("/api/v1/events", headers=h).json()
    assert len(all_events) == 2
    only = client.get("/api/v1/events?type=intrusion", headers=h).json()
    assert len(only) == 1 and only[0]["type"] == "intrusion"

def test_list_events_filter_multiple_types(client):
    # lonceng notifikasi: satu query untuk semua jenis pemicu, tanpa event absensi memakan limit
    for kind in ("intrusion", "crowd", "running"):
        client.post("/internal/nodes/1/events", json=_payload(type=kind), headers=_ingest_headers())
    h = _admin_headers(client)
    got = client.get("/api/v1/events?type=intrusion&type=crowd", headers=h).json()
    assert sorted(e["type"] for e in got) == ["crowd", "intrusion"]

def test_list_events_filter_severity(client):
    for sev in ("critical", "warning", "info"):
        client.post("/internal/nodes/1/events", json=_payload(severity=sev), headers=_ingest_headers())
    client.post("/internal/nodes/1/events", json=_payload(type="loitering", severity="info"), headers=_ingest_headers())
    h = _admin_headers(client)
    only = client.get("/api/v1/events?severity=critical", headers=h).json()
    assert len(only) == 1 and only[0]["severity"] == "critical"
    both = client.get("/api/v1/events?severity=critical&severity=warning", headers=h).json()
    assert sorted(e["severity"] for e in both) == ["critical", "warning"]
    combo = client.get("/api/v1/events?type=intrusion&severity=info", headers=h).json()
    assert len(combo) == 1 and combo[0]["type"] == "intrusion"
    assert client.get("/api/v1/events?severity=foo", headers=h).json() == []

def test_list_events_limit(client):
    for _ in range(3):
        client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
    h = _admin_headers(client)
    assert len(client.get("/api/v1/events?limit=2", headers=h).json()) == 2

def test_list_events_offset_pages_do_not_overlap(client):
    # paginasi offset: halaman tidak tumpang tindih dan urutan tetap menurun
    from datetime import datetime, timezone, timedelta
    base = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
    ids = [
        client.post(
            "/internal/nodes/1/events",
            json=_payload(ts_event=(base + timedelta(minutes=i)).isoformat()),
            headers=_ingest_headers(),
        ).json()["id"]
        for i in range(5)
    ]
    h = _admin_headers(client)
    pages = [client.get(f"/api/v1/events?limit=2&offset={o}", headers=h).json() for o in (0, 2, 4)]
    assert [len(p) for p in pages] == [2, 2, 1]
    got = [e["id"] for page in pages for e in page]
    assert len(got) == 5 and sorted(got) == sorted(ids)
    assert got == sorted(ids, reverse=True)

def test_list_events_order_is_deterministic_for_equal_ts(client):
    # pemutus seri id DESC: ts_event sama tetap punya urutan pasti antar-halaman
    from datetime import datetime, timezone
    ts = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc).isoformat()
    ids = [
        client.post("/internal/nodes/1/events", json=_payload(ts_event=ts), headers=_ingest_headers()).json()["id"]
        for _ in range(3)
    ]
    h = _admin_headers(client)
    expected = sorted(ids, reverse=True)
    got = [e["id"] for e in client.get("/api/v1/events", headers=h).json()]
    assert got == expected
    second = client.get("/api/v1/events?limit=1&offset=1", headers=h).json()
    assert [e["id"] for e in second] == [expected[1]]

def test_list_events_offset_validation(client):
    h = _admin_headers(client)
    assert client.get("/api/v1/events?offset=-1", headers=h).status_code == 422
    assert client.get("/api/v1/events?offset=10001", headers=h).status_code == 422
    assert client.get("/api/v1/events?offset=0", headers=h).status_code == 200

def test_stats_today(client):
    client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
    client.post("/internal/nodes/1/events", json=_payload(type="loitering"), headers=_ingest_headers())
    h = _admin_headers(client)
    s = client.get("/api/v1/events/stats/today", headers=h).json()
    assert s["total"] >= 2
    assert s["by_type"]["intrusion"] >= 1 and s["by_type"]["loitering"] >= 1

def _today_local_iso(h, m, s, days_ago=0):
    # Momen lokal hari ini, dikirim sebagai ISO UTC: SQLite menyimpan wall UTC
    # (offset dibuang), jadi baca-balik naive = UTC — sama seperti asumsi event_stats.
    from datetime import datetime, date, time, timedelta, timezone
    day = date.today() - timedelta(days=days_ago)
    return datetime.combine(day, time(h, m, s)).astimezone().astimezone(timezone.utc).isoformat()

def test_stats_today_excludes_attendance(client):
    # D1: "Event hari ini" adalah angka keamanan — lintasan face gate tidak dihitung
    h = _admin_headers(client)
    client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
    for _ in range(2):
        client.post("/internal/nodes/1/events", json=_payload(type="attendance"), headers=_ingest_headers())
    s = client.get("/api/v1/events/stats/today", headers=h).json()
    assert s["total"] == 1
    assert "attendance" not in s["by_type"]

def test_stats_today_by_severity_three_keys_sum_to_total(client):
    h = _admin_headers(client)
    for sev in ("critical", "warning", "warning", "info"):
        client.post("/internal/nodes/1/events", json=_payload(severity=sev), headers=_ingest_headers())
    s = client.get("/api/v1/events/stats/today", headers=h).json()
    assert s["by_severity"] == {"critical": 1, "warning": 2, "info": 1}
    assert sum(s["by_severity"].values()) == sum(s["by_hour"]) == s["total"] == 4

def test_stats_today_excludes_yesterday(client):
    # batas bawah filter: 23:59:30 kemarin (lokal) tidak dihitung, event hari ini dihitung
    h = _admin_headers(client)
    client.post("/internal/nodes/1/events",
                json=_payload(ts_event=_today_local_iso(23, 59, 30, days_ago=1)),
                headers=_ingest_headers())
    client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
    s = client.get("/api/v1/events/stats/today", headers=h).json()
    assert s["total"] == 1
    assert sum(s["by_hour"]) == 1

def test_stats_today_buckets_by_local_hour(client):
    # Review focus #1: event tepat di batas hari (00:00:30 dan 23:59:30 lokal)
    h = _admin_headers(client)
    client.post("/internal/nodes/1/events",
                json=_payload(severity="critical", ts_event=_today_local_iso(0, 0, 30)),
                headers=_ingest_headers())
    client.post("/internal/nodes/1/events",
                json=_payload(severity="warning", ts_event=_today_local_iso(23, 59, 30)),
                headers=_ingest_headers())
    s = client.get("/api/v1/events/stats/today", headers=h).json()
    assert len(s["by_hour"]) == 24
    assert s["by_hour"][0] == 1 and s["by_hour"][23] == 1
    assert s["critical_by_hour"][0] == 1 and s["critical_by_hour"][23] == 0
    assert sum(s["critical_by_hour"]) == s["by_severity"]["critical"]
    # severity tanpa event tetap ada sebagai kunci bernilai 0
    assert set(s["by_severity"]) == {"critical", "warning", "info"}
    assert s["by_severity"]["info"] == 0

def test_ws_close_on_bad_token(client):
    try:
        with client.websocket_connect("/api/v1/ws/events?token=bad") as ws:
            ws.receive_json()
        assert False, "should not connect"
    except Exception as e:
        assert getattr(e, "code", None) == 1008

def test_ws_receives_ingest_broadcast(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    with client.websocket_connect(f"/api/v1/ws/events?token={tok}") as ws:
        client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
        msg = ws.receive_json()
        assert msg["type"] == "intrusion" and msg["event_id"]

def test_get_event_by_id(client):
    ingest = client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers()).json()
    h = _admin_headers(client)
    r = client.get(f"/api/v1/events/{ingest['id']}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == ingest["id"]
    assert body["type"] == "intrusion" and body["severity"] == "info"

def test_get_event_by_id_not_found(client):
    h = _admin_headers(client)
    assert client.get("/api/v1/events/999999", headers=h).status_code == 404

def test_get_event_by_id_requires_auth(client):
    assert client.get("/api/v1/events/1").status_code == 401

def test_get_event_by_id_rejects_non_integer(client):
    h = _admin_headers(client)
    assert client.get("/api/v1/events/abc", headers=h).status_code == 422

def test_stats_today_route_not_shadowed(client):
    h = _admin_headers(client)
    r = client.get("/api/v1/events/stats/today", headers=h)
    assert r.status_code == 200 and "total" in r.json()

def test_ingest_node_by_name(db, monkeypatch):
    from app.services.ingest import ingest_event
    from app.models.node import Node
    db.add(Node(name="srv-test", type="server")); db.commit()
    status, ev = ingest_event(db, {
        "event_id": "7d8a4a1e-1f2b-4c3d-8e9f-001122334455",
        "type": "person_detect", "node_id": "srv-test",
        "ts_event": "2026-09-11T09:00:00+07:00",
    })
    assert status == "created" and ev.node_id is not None and ev.node.name == "srv-test"

def test_get_event_by_id_out_of_range_is_404(client):
    # Event.id = INTEGER (int4 di Postgres): id raksasa dari URL ngawur harus 404, bukan 500
    h = _admin_headers(client)
    for bad in ("99999999999999999999", "0", "-5"):
        assert client.get(f"/api/v1/events/{bad}", headers=h).status_code == 404

def test_list_events_camera_id_out_of_range_is_422(client):
    # Event.camera_id = INTEGER (int4 di Postgres): id di luar rentang kolom → 422, bukan 500 dari driver
    h = _admin_headers(client)
    for bad in ("99999999999999999999", "2147483648"):
        assert client.get(f"/api/v1/events?camera_id={bad}", headers=h).status_code == 422
    assert client.get("/api/v1/events?camera_id=1", headers=h).status_code == 200

# --- Plan A Task 1: parameter q (pencarian server di GET /events) ---

def _post_event(client, **kw):
    r = client.post("/internal/nodes/1/events", json=_payload(**kw), headers=_ingest_headers())
    assert r.status_code == 200, r.text
    return r.json()

def _search_events(client, q, **params):
    r = client.get("/api/v1/events", params={"q": q, **params}, headers=_admin_headers(client))
    assert r.status_code == 200, r.text
    return r.json()

def test_list_events_q_matches_employee_name_ignoring_case_and_padding(client):
    _post_event(client, type="attendance", payload={"employee_name": "Budi Santoso"})
    _post_event(client, type="attendance", payload={"employee_name": "Rina Wijaya"})
    assert len(_search_events(client, "budi")) == 1
    assert len(_search_events(client, "BUDI")) == 1
    assert len(_search_events(client, "  budi  ")) == 1
    assert _search_events(client, "siti") == []

def test_list_events_q_matches_face_name_in_payload(client):
    _post_event(client, type="intrusion", payload={"face": {"name": "Agus Setiawan"}})
    _post_event(client, type="intrusion", payload={"x": 1})
    hits = _search_events(client, "agus setiawan")
    assert len(hits) == 1 and hits[0]["payload"]["face"]["name"] == "Agus Setiawan"

def test_list_events_q_matches_camera_name_event_id_prefix_and_severity(client, db):
    from app.models.camera import Camera
    db.add(Camera(id=2, name="Lorong-9", host="1.2.3.5")); db.commit()
    eid = "9a7c3e10-0000-4000-8000-00000000c0de"
    _post_event(client, camera_id=2, event_id=eid, type="loitering", severity="critical")
    _post_event(client, type="loitering")
    assert [e["event_id"] for e in _search_events(client, "lorong-9")] == [eid]
    assert [e["event_id"] for e in _search_events(client, "9a7c3e10")] == [eid]
    assert [e["event_id"] for e in _search_events(client, "critical")] == [eid]

def test_list_events_q_blank_is_ignored(client):
    _post_event(client, type="intrusion")
    _post_event(client, type="loitering")
    assert len(_search_events(client, "")) == 2
    assert len(_search_events(client, "   ")) == 2

def test_list_events_q_wildcards_and_backslash_are_literal(client):
    _post_event(client, type="crowd", payload={"count": "1000"})
    _post_event(client, type="crowd", payload={"note": "dekat 100% penuh"})
    _post_event(client, type="crowd", payload={"code": "a_b"})
    _post_event(client, type="crowd", payload={"code": "axb"})
    _post_event(client, type="crowd", payload={"path": "C:\\data"})
    assert [e["payload"] for e in _search_events(client, "100%")] == [{"note": "dekat 100% penuh"}]
    assert [e["payload"] for e in _search_events(client, "a_b")] == [{"code": "a_b"}]
    assert [e["payload"] for e in _search_events(client, "\\")] == [{"path": "C:\\data"}]

def test_list_events_q_max_length_is_100(client):
    h = _admin_headers(client)
    assert client.get("/api/v1/events", params={"q": "x" * 100}, headers=h).status_code == 200
    assert client.get("/api/v1/events", params={"q": "x" * 101}, headers=h).status_code == 422

def test_list_events_q_with_type_and_offset_pages_do_not_overlap(client):
    for i in range(6):
        _post_event(client, type="intrusion", payload={"zona": "gudang", "i": i})
    for i in range(4):
        _post_event(client, type="loitering", payload={"zona": "gudang", "i": i})
    _post_event(client, type="intrusion", payload={"zona": "dermaga"})
    everything = _search_events(client, "gudang", type="intrusion", limit=50)
    assert len(everything) == 6
    seen = []
    for off in (0, 2, 4, 6):
        seen += [e["event_id"] for e in _search_events(client, "gudang", type="intrusion", limit=2, offset=off)]
    assert len(seen) == 6 and len(set(seen)) == 6
    assert set(seen) == {e["event_id"] for e in everything}

def test_list_events_q_finds_match_beyond_first_page(client):
    from datetime import datetime, timezone, timedelta
    base = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
    _post_event(client, type="attendance", payload={"employee_name": "Dewi Lestari"},
                ts_event=(base - timedelta(days=1)).isoformat())
    for i in range(59):
        _post_event(client, type="attendance", payload={"employee_name": f"Karyawan {i}"},
                    ts_event=(base - timedelta(minutes=i)).isoformat())
    page1 = _search_events(client, "", limit=50)
    assert len(page1) == 50 and all(e["payload"]["employee_name"] != "Dewi Lestari" for e in page1)
    hits = _search_events(client, "dewi", limit=50)
    assert len(hits) == 1 and hits[0]["payload"]["employee_name"] == "Dewi Lestari"
