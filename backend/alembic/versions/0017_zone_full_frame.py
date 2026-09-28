"""zone: polygon ke koordinat frame penuh.

Editor zona lama menampilkan snapshot dengan object-fit: cover di kotak 16:9. Untuk substream
4:3 (NVR anamorfik 640x480) 12,5% atas & bawah terpotong, jadi titik tersimpan relatif ke tampilan
terpotong — padahal vision memakainya sebagai koordinat frame penuh. Editor kini object-fit: fill;
migrasi ini memetakan polygon lama ke frame penuh agar zona persis seperti yang dulu terlihat.

Revision ID: 0017
Revises: 0016
"""

import logging

from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")
EDITOR_ASPECT = 16 / 9


def frame_aspect(probe) -> float | None:
    """Rasio w/h dari probe {"res": "640x480"}; None bila tidak diketahui."""
    try:
        w, h = (int(v) for v in str((probe or {}).get("res", "")).lower().split("x"))
    except (ValueError, AttributeError):
        return None
    return w / h if w > 0 and h > 0 else None


def _visible(aspect: float) -> tuple[float, float]:
    """Bagian frame yang tampil di kotak 16:9 ber-cover: (fraksi x, fraksi y)."""
    if aspect < EDITOR_ASPECT:
        return 1.0, aspect / EDITOR_ASPECT  # lebih tinggi: atas-bawah terpotong
    return EDITOR_ASPECT / aspect, 1.0  # lebih lebar: kiri-kanan terpotong


def to_full_frame(polygon, aspect: float):
    vx, vy = _visible(aspect)
    return [[round((1 - vx) / 2 + vx * x, 6), round((1 - vy) / 2 + vy * y, 6)] for x, y in polygon]


def from_full_frame(polygon, aspect: float):
    vx, vy = _visible(aspect)
    return [[round((x - (1 - vx) / 2) / vx, 6), round((y - (1 - vy) / 2) / vy, 6)] for x, y in polygon]


def _convert(transform) -> None:
    bind = op.get_bind()
    zone = sa.table("zone", sa.column("id", sa.Integer), sa.column("camera_id", sa.Integer),
                    sa.column("polygon", sa.JSON))
    camera = sa.table("camera", sa.column("id", sa.Integer), sa.column("rtsp_sub", sa.String),
                      sa.column("probe_main", sa.JSON), sa.column("probe_sub", sa.JSON))
    cams = {c.id: c for c in bind.execute(sa.select(camera))}
    for row in bind.execute(sa.select(zone.c.id, zone.c.camera_id, zone.c.polygon)).fetchall():
        cam = cams.get(row.camera_id)
        # editor memakai snapshot stream cam_<id>: substream bila ada, selain itu mainstream
        probe = (cam.probe_sub if cam.rtsp_sub else cam.probe_main) if cam is not None else None
        aspect = frame_aspect(probe)
        if aspect is None:
            log.warning("zone %s: rasio frame kamera %s tidak diketahui, polygon tidak diubah",
                        row.id, row.camera_id)
            continue
        if abs(aspect - EDITOR_ASPECT) < 1e-3 or not row.polygon:
            continue
        new = transform(row.polygon, aspect)
        bind.execute(zone.update().where(zone.c.id == row.id).values(polygon=new))
        log.info("zone %s (camera %s, rasio %.3f): %s -> %s", row.id, row.camera_id, aspect,
                 row.polygon, new)


def upgrade() -> None:
    _convert(to_full_frame)


def downgrade() -> None:
    _convert(from_full_frame)
