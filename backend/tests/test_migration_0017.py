"""0017: zona lama tergambar di editor yang memotong frame (object-fit: cover di kotak 16:9)."""
import importlib.util
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0017_zone_full_frame.py"
_spec = importlib.util.spec_from_file_location("mig0017", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_frame_aspect_from_probe():
    assert mig.frame_aspect({"res": "640x480"}) == pytest.approx(4 / 3)
    assert mig.frame_aspect({"res": "1920x1080"}) == pytest.approx(16 / 9)
    for bad in (None, {}, {"res": "?"}, {"res": "0x480"}):
        assert mig.frame_aspect(bad) is None


def test_to_full_frame_4_3_maps_cropped_view_into_middle_75_percent():
    # editor lama menampilkan 75% tengah frame 4:3: y=0 → 0.125, y=1 → 0.875, x tetap
    out = mig.to_full_frame([[0.2, 0.0], [0.8, 0.5], [0.5, 1.0]], 4 / 3)
    assert out == [[0.2, 0.125], [0.8, 0.5], [0.5, 0.875]]


def test_to_full_frame_16_9_unchanged_and_wider_frames_scale_x():
    poly = [[0.1, 0.2], [0.9, 0.2], [0.5, 0.8]]
    assert mig.to_full_frame(poly, 16 / 9) == poly
    wide = mig.to_full_frame([[0.0, 0.3], [1.0, 0.3], [0.5, 0.9]], 32 / 9)  # 2× lebih lebar
    assert wide == [[0.25, 0.3], [0.75, 0.3], [0.5, 0.9]]


def test_from_full_frame_is_exact_inverse():
    poly = [[0.2, 0.3], [0.7, 0.4], [0.5, 0.95]]
    for aspect in (4 / 3, 11 / 9, 16 / 9, 32 / 9):
        back = mig.from_full_frame(mig.to_full_frame(poly, aspect), aspect)
        assert [c for pt in back for c in pt] == pytest.approx([c for pt in poly for c in pt], abs=1e-5)


def test_upgrade_downgrade_against_real_tables():
    """Jalankan upgrade/downgrade 0017 di skema model (SQLite) lewat konteks Alembic."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.core.db import Base
    from app.models.camera import Camera
    from app.models.zone import Zone

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tri = [[0.2, 0.0], [0.8, 0.5], [0.5, 1.0]]
    with Session(engine) as s:
        s.add_all([
            Camera(id=1, name="nvr-4x3", host="h", rtsp_sub="/s", probe_sub={"res": "640x480"},
                   probe_main={"res": "1920x1080"}),
            Camera(id=2, name="zk-16x9", host="h", rtsp_sub=None, probe_main={"res": "1920x1080"}),
            Camera(id=3, name="tanpa-probe", host="h", rtsp_sub="/s"),
        ])
        s.add_all([Zone(id=10 + i, camera_id=i, name=f"z{i}", type="behavior", polygon=tri) for i in (1, 2, 3)])
        s.commit()

    def run(fn):
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            fn()

    def polygons():
        with Session(engine) as s:
            return {z.id: z.polygon for z in s.query(Zone).order_by(Zone.id)}

    run(mig.upgrade)
    after = polygons()
    assert after[11] == [[0.2, 0.125], [0.8, 0.5], [0.5, 0.875]]  # 4:3 → frame penuh
    assert after[12] == tri and after[13] == tri  # 16:9 tetap; probe tak diketahui dilewati
    run(mig.downgrade)
    assert polygons()[11] == tri
