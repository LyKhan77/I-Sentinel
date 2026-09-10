import pytest

from vision.pipeline.detector import Detection
from vision.pipeline.tracker import ByteTracker, Track


def D(cx: float, cy: float, w: float = 0.1, h: float = 0.2, conf: float = 0.9) -> Detection:
    """Detection centered at (cx, cy)."""
    return Detection(bbox=(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), conf=conf)


def test_first_update_creates_track_id_1():
    tr = ByteTracker()
    tracks = tr.update([D(0.5, 0.5)], ts=0.0)
    assert [t.id for t in tracks] == [1]
    assert tracks[0].age == 1
    assert tracks[0].misses == 0


def test_same_bbox_next_frame_same_id_velocity_zero():
    tr = ByteTracker()
    tr.update([D(0.5, 0.5)], ts=0.0)
    tracks = tr.update([D(0.5, 0.5)], ts=0.2)
    assert [t.id for t in tracks] == [1]
    assert tracks[0].velocity == (0.0, 0.0)
    assert tracks[0].age == 2


def test_shifted_bbox_same_id_velocity_x_positive():
    tr = ByteTracker()
    tr.update([D(0.4, 0.5)], ts=0.0)
    tracks = tr.update([D(0.5, 0.5)], ts=0.2)
    assert [t.id for t in tracks] == [1]
    assert tracks[0].velocity[0] > 0


def test_track_dropped_after_max_age_misses():
    tr = ByteTracker(max_age=15)
    tr.update([D(0.5, 0.5)], ts=0.0)
    lost_at = None
    for i in range(1, 21):
        tracks = tr.update([], ts=i * 0.2)
        if 1 in tr.lost_ids:
            lost_at = i
            break
    assert lost_at == 16  # misses reaches 16 > max_age=15 -> dropped
    assert all(t.id != 1 for t in tracks)


def test_two_tracks_stable_ids():
    tr = ByteTracker()
    a, b = (0.3, 0.5), (0.7, 0.5)
    ids_first = [t.id for t in tr.update([D(*a), D(*b)], ts=0.0)]
    assert sorted(ids_first) == [1, 2]
    # same positions, swapped order -> ids stay with their centroids
    tracks = tr.update([D(*b), D(*a)], ts=0.2)
    by_id = {t.id: t for t in tracks}
    assert sorted(by_id) == [1, 2]
    for t in tracks:
        assert t.velocity == (0.0, 0.0)


def test_missed_track_still_active_until_max_age():
    tr = ByteTracker(max_age=3)
    tr.update([D(0.5, 0.5)], ts=0.0)
    tracks = tr.update([], ts=0.2)
    assert [t.id for t in tracks] == [1]
    assert tracks[0].misses == 1
    tracks = tr.update([], ts=0.4)
    assert tracks[0].misses == 2


def test_low_conf_detection_ignored():
    tr = ByteTracker()
    tracks = tr.update([D(0.5, 0.5, conf=0.1)], ts=0.0)
    assert tracks == []
