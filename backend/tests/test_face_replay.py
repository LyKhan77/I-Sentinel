"""Replay offline: klasifikasi legacy vs strict, ringkasan, dan main dengan embedder palsu."""
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.camera import Camera
from app.models.employee import Employee
from app.models.event import Event
from app.services import face
from app.services.face import FaceResult, MatchResult
from scripts import face_replay


def _strict(employee_id=None, reason="no_match", margin=None):
    return MatchResult(employee_id, 0.5 if employee_id is not None else None, None, reason, margin)


def test_classify_covers_six_categories():
    assert face_replay.classify(1, _strict(1, "matched", 0.3)) == "same"
    assert face_replay.classify(1, _strict(2, "matched", 0.3)) == "flipped"
    assert face_replay.classify(1, _strict(None, "ambiguous", 0.02)) == "ambiguous"
    assert face_replay.classify(1, _strict(None, "no_match")) == "lost"
    assert face_replay.classify(None, _strict(2, "matched", 0.3)) == "gained"
    assert face_replay.classify(None, _strict(None, "no_match")) == "both_none"
    assert face_replay.classify(None, _strict(None, "ambiguous", 0.02)) == "both_none"


def test_summarize_counts_and_same_pct():
    rows = [
        {"event_id": "e1", "legacy_employee_id": 1, "strict": _strict(1, "matched", 0.3)},
        {"event_id": "e2", "legacy_employee_id": 1, "strict": _strict(1, "matched", 0.3)},
        {"event_id": "e3", "legacy_employee_id": 1, "strict": _strict(1, "matched", 0.3)},
        {"event_id": "e4", "legacy_employee_id": 1, "strict": _strict(2, "matched", 0.3)},
        {"event_id": "e5", "legacy_employee_id": 1, "strict": _strict(None, "no_match")},
        {"event_id": "e6", "legacy_employee_id": None, "strict": _strict(2, "matched", 0.3)},
    ]

    summary = face_replay.summarize(rows)

    assert summary["counts"] == {"same": 3, "flipped": 1, "lost": 1, "ambiguous": 0,
                                "gained": 1, "both_none": 0}
    assert summary["same_pct"] == 60.0
    assert summary["flipped"] == ["e4"]
    assert summary["ambiguous"] == []
    assert summary["gained"] == ["e6"]


def test_summarize_without_legacy_recognized_does_not_divide_by_zero():
    summary = face_replay.summarize(
        [{"event_id": "e1", "legacy_employee_id": None, "strict": _strict(None, "no_match")}])

    assert summary["same_pct"] == 0.0
    assert summary["counts"]["both_none"] == 1


# --- main dengan embedder/gallery palsu dan DB SQLite ---

A_VEC = [1.0, 0.0, 0.0, 0.0]
MID_VEC = [0.7071, 0.7071, 0.0, 0.0]  # jarak skor sama ke dua karyawan → margin 0


def _seed(db, tmp_path):
    cam = Camera(name="Gate", host="127.0.0.1")
    a = Employee(name="Budi", employee_code="E1")
    b = Employee(name="Siti", employee_code="E2")
    db.add_all([cam, a, b])
    db.commit()
    for employee, vector in ((a, A_VEC), (b, [0.0, 1.0, 0.0, 0.0])):
        from app.models.face_embedding import FaceEmbedding

        db.add(FaceEmbedding(employee_id=employee.id, vector=vector, quality=0.9))
    db.commit()
    (tmp_path / "crops").mkdir()
    (tmp_path / "crops" / "a.jpg").write_bytes(b"jpeg")
    (tmp_path / "crops" / "b.jpg").write_bytes(b"jpeg")
    now = datetime.now(timezone.utc)
    rows = [
        # legacy cocok A, strict cocok A juga
        ("ev-same", "crops/a.jpg", a.id, "matched"),
        # legacy cocok A, strict ragu (margin 0) → ambiguous
        ("ev-ambiguous", "crops/b.jpg", a.id, "matched"),
        # legacy tidak cocok, strict cocok A → gained
        ("ev-gained", "crops/a.jpg", None, "no_match"),
    ]
    for event_id, crop, employee_id, reason in rows:
        db.add(Event(event_id=event_id, type="attendance", camera_id=cam.id, severity="info",
                     ts_event=now,
                     payload={"direction": "entry", "crop_path": crop, "employee_id": employee_id,
                              "match_reason": reason}))
    db.commit()
    return a, b


def _fake_embedder(vectors):
    def embed(self, path):
        return [FaceResult(vector=vectors[path], det_score=0.9, bbox=[0.0, 0.0, 10.0, 10.0],
                           quality=0.9)]

    return embed


def test_main_prints_summary_of_ids_without_names_or_embeddings(db, tmp_path, monkeypatch, capsys):
    a, b = _seed(db, tmp_path)
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    monkeypatch.setattr(face_replay, "SessionLocal", lambda: Session(bind=db.get_bind()))
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    vectors = {str(tmp_path / "crops" / "a.jpg"): A_VEC, str(tmp_path / "crops" / "b.jpg"): MID_VEC}
    monkeypatch.setattr(face.FaceEngine, "embed", _fake_embedder(vectors))
    monkeypatch.setattr(face, "refresh_gallery", lambda db_: face.gallery)
    face.gallery._by_employee = {a.id: [A_VEC], b.id: [[0.0, 1.0, 0.0, 0.0]]}

    code = face_replay.main(["--sleep", "0"])
    out = capsys.readouterr().out

    assert code == 0
    assert os.environ["OMP_NUM_THREADS"] == "2"  # dibatasi sebelum model dimuat
    assert "same=1" in out and "ambiguous=1" in out and "gained=1" in out
    # rincian hanya untuk kategori yang butuh penilaian manual
    assert "event=ev-ambiguous" in out and "event=ev-gained" in out
    assert "Budi" not in out and "Siti" not in out
    assert "0.707" not in out  # tanpa embedding di keluaran


def test_main_reports_missing_model_with_nonzero_exit(db, tmp_path, monkeypatch, capsys):
    _seed(db, tmp_path)
    monkeypatch.setattr(face_replay, "SessionLocal", lambda: Session(bind=db.get_bind()))
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(face, "refresh_gallery", lambda db_: face.gallery)

    def boom(self, path):
        raise RuntimeError("model wajah gagal dimuat dari /kosong")

    monkeypatch.setattr(face.FaceEngine, "embed", boom)

    code = face_replay.main(["--sleep", "0"])
    err = capsys.readouterr().err

    assert code != 0
    assert "model wajah" in err


# --- batas CPU: onnxruntime memasang afinitas sendiri sehingga taskset/OMP_NUM_THREADS tidak membatasinya ---

import sys
import types

import pytest

_REAL_CAP = face_replay.cap_onnx_threads if hasattr(face_replay, "cap_onnx_threads") else None


@pytest.fixture(autouse=True)
def _no_global_ort_patch(monkeypatch):
    """Tes `main` tidak boleh menambal onnxruntime nyata (bocor ke tes lain)."""
    if _REAL_CAP is not None:
        monkeypatch.setattr(face_replay, "cap_onnx_threads", lambda threads: None)


def test_cap_onnx_threads_injects_session_options_even_when_caller_passes_none(monkeypatch):
    seen = {}

    class FakeOptions:
        def __init__(self):
            self.entries = {}

        def add_session_config_entry(self, key, value):
            self.entries[key] = value

    class FakeSession:
        def __init__(self, path_or_bytes, sess_options=None, providers=None, **kwargs):
            seen["options"] = sess_options
            seen["providers"] = providers

    fake = types.SimpleNamespace(SessionOptions=FakeOptions, InferenceSession=FakeSession)
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)

    assert _REAL_CAP(2) is True
    fake.InferenceSession("m.onnx", providers=["CPUExecutionProvider"])  # cara insightface memanggil

    opts = seen["options"]
    assert (opts.intra_op_num_threads, opts.inter_op_num_threads) == (2, 1)
    assert opts.entries == {"session.intra_op.allow_spinning": "0"}
    assert seen["providers"] == ["CPUExecutionProvider"]


def test_cap_onnx_threads_overrides_options_passed_by_the_caller(monkeypatch):
    seen = {}

    class FakeOptions:
        intra_op_num_threads = 0
        inter_op_num_threads = 0

        def add_session_config_entry(self, key, value):
            pass

    class FakeSession:
        def __init__(self, path_or_bytes, sess_options=None, **kwargs):
            seen["options"] = sess_options

    monkeypatch.setitem(sys.modules, "onnxruntime",
                        types.SimpleNamespace(SessionOptions=FakeOptions, InferenceSession=FakeSession))
    _REAL_CAP(3)
    own = FakeOptions()
    sys.modules["onnxruntime"].InferenceSession("m.onnx", own)

    assert seen["options"] is own and own.intra_op_num_threads == 3


def test_cap_onnx_threads_without_onnxruntime_is_a_noop(monkeypatch):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)  # import gagal
    assert _REAL_CAP(2) is False


def test_main_caps_threads_before_any_model_call(db, tmp_path, monkeypatch, capsys):
    a, b = _seed(db, tmp_path)
    calls = []
    monkeypatch.setattr(face_replay, "cap_onnx_threads", lambda threads: calls.append(("cap", threads)))
    monkeypatch.setattr(face_replay, "SessionLocal", lambda: Session(bind=db.get_bind()))
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    vectors = {str(tmp_path / "crops" / "a.jpg"): A_VEC, str(tmp_path / "crops" / "b.jpg"): MID_VEC}
    inner = _fake_embedder(vectors)

    def embed(self, path):
        calls.append(("embed", path))
        return inner(self, path)

    monkeypatch.setattr(face.FaceEngine, "embed", embed)
    monkeypatch.setattr(face, "refresh_gallery", lambda db_: face.gallery)
    face.gallery._by_employee = {a.id: [A_VEC], b.id: [[0.0, 1.0, 0.0, 0.0]]}

    assert face_replay.main(["--sleep", "0", "--threads", "3"]) == 0
    assert calls[0] == ("cap", 3) and calls[1][0] == "embed"


def test_main_stops_at_max_seconds_and_still_prints_the_summary(db, tmp_path, monkeypatch, capsys):
    a, b = _seed(db, tmp_path)
    monkeypatch.setattr(face_replay, "SessionLocal", lambda: Session(bind=db.get_bind()))
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(face.FaceEngine, "embed", _fake_embedder({}))  # tidak boleh dipanggil
    monkeypatch.setattr(face, "refresh_gallery", lambda db_: face.gallery)

    code = face_replay.main(["--sleep", "0", "--max-seconds", "0"])
    out = capsys.readouterr().out

    assert code == 0
    assert "batas waktu" in out and "direplay: 0" in out and "same_pct" in out


def test_main_counts_crops_without_a_face(db, tmp_path, monkeypatch, capsys):
    a, b = _seed(db, tmp_path)
    monkeypatch.setattr(face_replay, "SessionLocal", lambda: Session(bind=db.get_bind()))
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(face.FaceEngine, "embed", lambda self, path: [])
    monkeypatch.setattr(face, "refresh_gallery", lambda db_: face.gallery)

    assert face_replay.main(["--sleep", "0"]) == 0
    out = capsys.readouterr().out

    assert "tanpa wajah: 3" in out  # _seed membuat tiga event ber-crop
