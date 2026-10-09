"""Gerbang kualitas wajah R5b: fungsi murni, tanpa GPU."""
import numpy as np
import pytest

from vision.face import FaceDet
from vision.face_quality import (FaceSettings, aggregate, blur_score, crop_box, gate_code,
                                 quality, yaw_ratio, zone_of)

FRONTAL = np.array([[40, 60], [80, 60], [60, 85], [45, 110], [75, 110]], dtype=np.float32)
TURNED = FRONTAL.copy()
TURNED[2, 0] = 78.0
ZONE = {"id": 9, "direction": "entry",
        "polygon": [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]}
W, H = 1920, 1080


def face(cx=960.0, cy=540.0, width=120.0, score=0.9, base=FRONTAL):
    """Wajah lebar `width` px berpusat di (cx, cy); landmark ikut diskalakan."""
    x1, y1 = cx - width / 2, cy - width * 0.6
    kps = (base - base.mean(axis=0)) * (width / 60.0) + np.array([cx, cy], dtype=np.float32)
    return FaceDet(bbox=(x1, y1, x1 + width, y1 + width * 1.2), kps=kps, score=score)


def test_yaw_ratio_frontal_is_zero_and_turned_is_large():
    assert yaw_ratio(FRONTAL) == pytest.approx(0.0)
    assert yaw_ratio(TURNED) == pytest.approx(0.45)


def test_yaw_ratio_degenerate_eyes_is_rejected():
    kps = FRONTAL.copy()
    kps[1] = kps[0]
    assert yaw_ratio(kps) == 1.0


def test_blur_score_sharp_noise_vs_flat():
    sharp = np.random.default_rng(0).integers(0, 255, (112, 112, 3), dtype=np.uint8)
    assert blur_score(sharp) > 120
    assert blur_score(np.zeros((112, 112, 3), np.uint8)) == 0.0


def test_quality_formula():
    assert quality(0.9, 56.0, 0.2) == pytest.approx(0.9 * 0.5 * 0.8)
    assert quality(0.9, 224.0, 0.0) == pytest.approx(0.9)


def test_gate_code_reports_first_failing_gate():
    s = FaceSettings()
    assert gate_code(face(cx=100.0), W, H, [ZONE], s) == ("zone", None)
    assert gate_code(face(width=60.0), W, H, [ZONE], s)[0] == "small"
    assert gate_code(face(score=0.5), W, H, [ZONE], s)[0] == "score"
    assert gate_code(face(base=TURNED), W, H, [ZONE], s)[0] == "yaw"
    assert gate_code(face(), W, H, [ZONE], s) == (None, ZONE)


def test_zone_of_picks_zone_containing_face_center():
    entry = {"id": 1, "direction": "entry", "polygon": [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]}
    exit_ = {"id": 2, "direction": "exit", "polygon": [[0.5, 0], [1, 0], [1, 1], [0.5, 1]]}
    assert zone_of((0.8, 0.5), [entry, exit_]) is exit_
    assert zone_of((0.2, 0.5), [entry, exit_]) is entry


def _unit(i):
    v = [0.0] * 512
    v[i] = 1.0
    return v


def test_aggregate_is_weighted_and_unit_length():
    # Cosine antara vektor >0,5 agar keduanya lolos filter outlier.
    nearby = [0.8, 0.6] + [0.0] * 510
    out = np.array(aggregate([_unit(0), nearby], [3.0, 1.0]))
    assert float(np.linalg.norm(out)) == pytest.approx(1.0)
    assert out[0] / out[1] == pytest.approx(3.8 / 0.6)


def test_aggregate_drops_outlier_from_swapped_track():
    neg = [-v for v in _unit(0)]
    out = aggregate([_unit(0), _unit(0), neg], [1.0, 1.0, 1.0])
    assert out[0] == pytest.approx(1.0)


def test_aggregate_cancelling_vectors_fall_back_to_heaviest():
    neg = [-v for v in _unit(0)]
    assert aggregate([_unit(0), neg], [1.0, 1.0]) == _unit(0)


def test_crop_box_pads_30_percent():
    assert crop_box((900.0, 468.0, 1020.0, 612.0), W, H) == (864, 424, 1056, 655)


def test_crop_box_is_clamped_at_frame_edges():
    x1, y1, x2, y2 = crop_box((0.0, 0.0, 100.0, 120.0), W, H)
    assert (x1, y1) == (0, 0) and x2 > 100 and y2 > 120
    x1, y1, x2, y2 = crop_box((1850.0, 980.0, 1920.0, 1080.0), W, H)
    assert (x2, y2) == (W, H) and x1 < 1850 and y1 < 980


def test_face_settings_defaults_and_partial_config():
    assert FaceSettings.from_config(None) == FaceSettings()
    s = FaceSettings.from_config({"device": "cuda:2", "min_frames": 5})
    assert s.min_frames == 5 and s.min_width_px == 80.0 and s.blur_min == 120.0


def test_ident_settings_defaults_and_partial_config():
    from vision.face_quality import IdentSettings

    assert IdentSettings.from_config(None) == IdentSettings()
    s = IdentSettings.from_config({"best_k": 3})
    assert s.best_k == 3 and isinstance(s.best_k, int)
    assert (s.min_width_px, s.max_pitch, s.window_s) == (60.0, 0.30, 8.0)


def test_face_settings_reads_ident_block_and_compares_unequal():
    from vision.face_quality import IdentSettings

    s = FaceSettings.from_config({"ident": {"window_s": 3.0, "best_k": "4"}})
    assert s.ident == IdentSettings(window_s=3.0, best_k=4)
    assert isinstance(s.ident.best_k, int)
    assert FaceSettings.from_config({"ident": {"window_s": 3.0}}) != FaceSettings()
    assert FaceSettings.from_config({"ident": {}}) == FaceSettings()


def test_best_k_keeps_top_ranks_and_ties_do_not_beat():
    from vision.face_quality import BestK

    k = BestK(2)
    assert k.beats(0.1) is True  # belum penuh
    k.add(3.0, 0.9, _unit(0))
    k.add(1.0, 0.5, _unit(1))
    k.add(2.0, 0.7, _unit(2))
    assert [rank for rank, _, _ in k.items] == [3.0, 2.0]
    assert len(k) == 2
    assert k.items[1] == (2.0, 0.7, _unit(2))
    assert k.beats(1.9) is False
    assert k.beats(2.0) is False  # sama tidak mengalahkan
    assert k.beats(2.1) is True
    assert BestK(1).beats(-5.0) is True  # kapasitas satu selalu menerima yang pertama


def test_face_settings_attendance_mode_from_config_and_defaults():
    assert (FaceSettings().attendance_mode, FaceSettings().attendance_window_s) == ("legacy", 1.5)
    s = FaceSettings.from_config({"attendance_mode": "unified", "attendance_window_s": 2.5})
    assert (s.attendance_mode, s.attendance_window_s) == ("unified", 2.5)
    assert FaceSettings.from_config({"attendance_mode": "x"}).attendance_mode == "legacy"
    assert FaceSettings.from_config({}).attendance_mode == "legacy"
    assert FaceSettings.from_config({"attendance_mode": "unified"}) != FaceSettings()
