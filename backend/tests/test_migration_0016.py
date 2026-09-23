"""Migration 0016: backfill face settings and remove stored biometric vectors."""
import importlib.util
import pathlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_PATH = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0016_face_gate_settings.py"
_spec = importlib.util.spec_from_file_location("mig0016", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_strip_embedding_removes_only_embedding():
    assert mig.strip_embedding({"embedding": [0.1] * 512, "crop_path": "crops/x.jpg"}) == {
        "crop_path": "crops/x.jpg"}


def test_strip_embedding_leaves_other_payloads_untouched():
    assert mig.strip_embedding({"crop_path": "crops/x.jpg"}) is None
    assert mig.strip_embedding(None) is None


def test_upgrade_backfills_face_columns_and_removes_attendance_embeddings(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE detector_setting (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("INSERT INTO detector_setting (id) VALUES (1)"))
        conn.execute(sa.text("CREATE TABLE event (id INTEGER PRIMARY KEY, type VARCHAR, payload JSON)"))
        conn.execute(sa.text("INSERT INTO event VALUES (1, 'attendance', :payload)"),
                     {"payload": '{"embedding":[0.1],"crop_path":"crops/x.jpg"}'})
        conn.execute(sa.text("INSERT INTO event VALUES (2, 'intrusion', :payload)"),
                     {"payload": '{"embedding":[0.2]}'})
        monkeypatch.setattr(mig, "op", Operations(MigrationContext.configure(conn)))
        mig.upgrade()
        row = conn.execute(sa.text("SELECT face_min_width_px, face_min_det_score, face_max_yaw, "
                                   "face_blur_min, face_min_frames FROM detector_setting")).one()
        assert tuple(row) == (80.0, 0.6, 0.35, 120.0, 3)
        rows = conn.execute(sa.text("SELECT payload FROM event ORDER BY id")).scalars().all()
        assert [sa.JSON().result_processor(conn.dialect, None)(value) for value in rows] == [
            {"crop_path": "crops/x.jpg"}, {"embedding": [0.2]},
        ]
    engine.dispose()
