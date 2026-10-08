"""IntrusionRegistry, associate, pitch_dev, jpeg_crop, IdentCollector — tanpa GPU/cv2."""
import numpy as np
import pytest

from vision.face import FaceDet
from vision.face_quality import FaceSettings
from vision.intrusion_face import (BEST_K, HEAD_FRAC, IDENT_MIN_QUALITY, IDENT_WINDOW_S, MAX_PITCH,
                                   MIN_CROP_SCORE, REGISTRY_TTL_S, IdentCollector,
                                   IntrusionRegistry, associate, jpeg_crop, pitch_dev)

FRONTAL = [[40, 60], [80, 60], [60, 85], [45, 110], [75, 110]]
FULL_POLY = [{"id": 5, "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}]


def face(cx=960.0, cy=540.0, width=120.0, score=0.9, kps=None, img_w=1920, img_h=1080):
    kps = np.array(kps or FRONTAL, dtype=np.float32)
    kps = (kps - kps.mean(axis=0)) * (width / 60.0) + np.array([cx, cy], dtype=np.float32)
    return FaceDet(bbox=(cx - width / 2, cy - width * 0.6, cx + width / 2, cy + width * 0.6),
                   kps=kps, score=score)


def downslope_kps(nose_y):
    """Kps frontal dengan hidung diturunkan (menghadap bawah)."""
    k = [list(p) for p in FRONTAL]
    k[2][1] = nose_y
    return k


class FakeEncoder:
    def __init__(self):
        self.boxes: list[tuple] = []

    def __call__(self, frame, box):
        self.boxes.append(box)
        return b"jpg-%d" % int((box[2] - box[0]) / 1.6)  # lebar wajah (pad 30% tiap sisi)


class FakeEmbedder:
    def __init__(self, vec=None):
        self.vec = vec or [1.0, 0.0]
        self.embed_calls = 0

    def align(self, img, kps):
        return self.noise

    noise = np.random.default_rng(0).integers(0, 255, (112, 112, 3), dtype=np.uint8)  # blur tinggi

    def embed(self, aligned):
        self.embed_calls += 1
        return self.vec


# --- registry ---

def test_registry_fresh_within_ttl_then_expires():
    r = IntrusionRegistry()
    r.touch(15, 1, (0.1, 0.1, 0.2, 0.9), 10.0)
    assert r.active(10.0 + REGISTRY_TTL_S - 0.1) is True
    assert r.active(10.0 + REGISTRY_TTL_S + 0.1) is False


def test_registry_bind_creates_missing_entry_and_prune_keeps_bound():
    r = IntrusionRegistry()
    r.touch(15, 1, (0.1, 0.1, 0.2, 0.9), 10.0)
    r.touch(15, 2, (0.3, 0.1, 0.4, 0.9), 10.0)
    r.bind(15, 1, "ev-1", 11.0)
    r.bind(15, 9, "ev-2", 11.0)  # entri belum ada → dibuat
    assert (9, "ev-2") in {(e.track_id, e.event_id) for e in r.entries()}
    r.prune(99.0)  # jauh melewati TTL
    assert [(e.track_id, e.event_id) for e in r.entries()] == [(1, "ev-1"), (9, "ev-2")]


def test_registry_release_drops_entry():
    r = IntrusionRegistry()
    r.bind(15, 1, "ev-1", 10.0)
    r.release(15, 1)
    assert r.entries() == []


# --- associate ---

def test_associate_picks_nearest_head_with_two_overlapping_people():
    a = (0.30, 0.30, 0.50, 1.00)
    b = (0.45, 0.35, 0.65, 1.05)
    ents = [IntrusionRegistry._Entry(1, 101, a, 10.0), IntrusionRegistry._Entry(1, 102, b, 10.0)]
    # pusat wajah di kepala A (atas 40% bbox A, diperlebar); kepala B lebih jauh
    assert associate((0.40, 0.42), ents).track_id == 101
    assert associate((0.55, 0.45), ents).track_id == 102


def test_associate_none_for_face_below_head_region():
    ents = [IntrusionRegistry._Entry(1, 101, (0.20, 0.20, 0.40, 0.90), 10.0)]
    assert associate((0.30, 0.70), ents) is None  # torso


# --- pitch_dev ---

def test_pitch_dev_frontal_zero_and_looking_down_positive_and_degenerate():
    assert pitch_dev(np.array(FRONTAL, dtype=np.float32)) == pytest.approx(0.0)
    k = np.array(downslope_kps(100), dtype=np.float32)
    assert pitch_dev(k) == pytest.approx(0.3, abs=1e-6)
    mouth_above_eyes = [[40, 110], [80, 110], [60, 60], [45, 60], [75, 60]]
    assert pitch_dev(np.array(mouth_above_eyes, dtype=np.float32)) >= 1.0


# --- jpeg_crop ---

def test_jpeg_crop_returns_jpeg_of_region_or_none():
    frame = np.full((100, 100, 3), 200, np.uint8)
    out = jpeg_crop(frame, (10, 10, 60, 60))
    assert out is not None and out[:2] == b"\xff\xd8"
    assert jpeg_crop(np.zeros((0, 0, 3), np.uint8), (10, 10, 60, 60)) is None


# --- IdentCollector ---

def _collector(registry, embedder=None, encode=None):
    return IdentCollector(registry, embedder or FakeEmbedder(), FaceSettings(), 363, "n1",
                          encode=encode or FakeEncoder())


BBOX = (0.40, 0.30, 0.60, 1.00)


def _bind_entry(registry, track_id=1, bbox=(0.40, 0.30, 0.60, 1.00), event_id="ev-1", ts=10.0):
    # kepala bbox memuat pusat wajah default face() = (0.5, 0.5), termasuk wajah kecil
    registry.bind(5, track_id, event_id, ts)


def test_collector_emits_best_frames_at_window_end_and_releases_entry():
    registry = IntrusionRegistry()
    collector = _collector(registry)
    _bind_entry(registry)
    for i in range(3):
        registry.touch(5, 1, BBOX, 10.0 + i * 0.1)
        collector.observe([face()], None, 1920, 1080, 10.0 + i * 0.1)
    assert collector.drain(11.0) == []  # belum keluar: masih mencari kandidat terbaik
    registry.touch(5, 1, BBOX, 10.0 + IDENT_WINDOW_S - 0.1)  # orang masih di zona
    msgs = collector.drain(10.0 + IDENT_WINDOW_S)
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg["event_id"] == "ev-1" and msg["camera_id"] == 363 and msg["node_id"] == "n1"
    assert msg["track_id"] == 1 and msg["embedding"] is not None and msg["crop_path"] is None
    assert msg["stats"]["faces"] == 3 and msg["stats"]["frames_used"] == 3
    assert registry.entries() == []  # entri dilepas setelah kirim


def test_collector_waits_for_bind_before_emitting():
    registry = IntrusionRegistry()
    collector = _collector(registry)
    for i in range(3):
        registry.touch(5, 1, BBOX, 10.0 + i)
        collector.observe([face()], None, 1920, 1080, 10.0 + i)
    assert collector.drain(20.0) == []
    registry.bind(5, 1, "ev-1", 10.0)
    msgs = collector.drain(20.0)
    assert len(msgs) == 1 and msgs[0]["event_id"] == "ev-1"


def test_collector_window_expiry_emits_null_embedding_with_reject_counts():
    registry = IntrusionRegistry()
    collector = _collector(registry)
    _bind_entry(registry, ts=10.0)
    registry.touch(5, 1, BBOX, 10.0)
    for i in range(3):
        collector.observe([face(width=40.0)], None, 1920, 1080, 10.0 + i)
    registry.touch(5, 1, BBOX, 17.9)  # entri tetap segar: hanya kondisi jendela yang boleh memicu
    msgs = collector.drain(10.0 + IDENT_WINDOW_S)
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg["embedding"] is None
    assert msg["stats"]["rejects"]["small"] >= 1 and msg["stats"]["frames_used"] == 0
    assert msg["stats"]["faces"] == 3


def test_collector_person_gone_after_bind_emits_partial():
    registry = IntrusionRegistry()
    collector = _collector(registry)
    _bind_entry(registry, ts=10.0)
    registry.touch(5, 1, BBOX, 10.0)
    collector.observe([face()], None, 1920, 1080, 10.0)
    collector.observe([face()], None, 1920, 1080, 10.1)  # 2 frame < min_frames
    msgs = collector.drain(10.0 + REGISTRY_TTL_S + 0.1)  # person hilang
    assert len(msgs) == 1
    assert msgs[0]["embedding"] is not None and msgs[0]["stats"]["frames_used"] == 2


def test_collector_unbound_gone_entry_dropped_without_message():
    registry = IntrusionRegistry()
    collector = _collector(registry)
    registry.touch(5, 1, BBOX, 10.0)
    collector.observe([face()], None, 1920, 1080, 10.0)
    assert collector.drain(10.0 + REGISTRY_TTL_S + 0.1) == []
    assert registry.entries() == []


def test_collector_rejects_by_pitch_and_by_quality():
    registry = IntrusionRegistry()
    collector = _collector(registry)
    _bind_entry(registry, ts=10.0)
    registry.touch(5, 1, BBOX, 10.0)
    # pitch: hidung turun dari posisi frontal → pitch_dev > MAX_PITCH
    down = FRONTAL[2][1] + (FRONTAL[4][1] - FRONTAL[0][1]) * 0.9  # jauh di bawah
    collector.observe([face(kps=downslope_kps(down))], None, 1920, 1080, 10.0)
    # quality: skor 0.62, lebar 80 px, yaw_ratio 0.3 → quality ≈ 0.31 < IDENT_MIN_QUALITY
    yaw30 = [list(p) for p in FRONTAL]
    yaw30[2][0] += 12  # 12/40 (jarak mata) = 0.3
    collector.observe([face(width=80.0, score=0.62, kps=yaw30)], None, 1920, 1080, 10.0)
    msgs = collector.drain(10.0 + IDENT_WINDOW_S)
    assert len(msgs) == 1
    rej = msgs[0]["stats"]["rejects"]
    assert rej["pitch"] == 1 and rej["quality"] == 1
    assert msgs[0]["embedding"] is None and msgs[0]["stats"]["frames_used"] == 0


def test_collector_ignores_face_outside_any_head_region():
    registry = IntrusionRegistry()
    collector = _collector(registry)
    _bind_entry(registry, ts=10.0)
    registry.touch(5, 1, BBOX, 10.0)
    collector.observe([face(cx=100.0)], None, 1920, 1080, 10.0)  # pojok kiri, jauh dari entri
    msgs = collector.drain(10.0 + IDENT_WINDOW_S)
    assert len(msgs) == 1 and msgs[0]["stats"]["faces"] == 0


def test_collector_keeps_best_associated_face_crop_even_when_gate_rejects():
    registry = IntrusionRegistry()
    enc = FakeEncoder()
    collector = _collector(registry, encode=enc)
    _bind_entry(registry, ts=10.0)
    registry.touch(5, 1, BBOX, 10.0)
    collector.observe([face(width=40.0)], None, 1920, 1080, 10.0)   # kecil tapi skor 0.9
    collector.observe([face(width=70.0)], None, 1920, 1080, 10.1)   # terbaik
    collector.observe([face(width=60.0)], None, 1920, 1080, 10.2)   # lebih kecil → diabaikan
    msgs = collector.drain(10.0 + IDENT_WINDOW_S)
    assert len(msgs) == 1
    assert msgs[0]["_crop"] == b"jpg-70"
    assert [int(round((b[2] - b[0]) / 1.6)) for b in enc.boxes] == [40, 70]  # 2× saja: 60 tidak lebih baik


def test_collector_no_crop_when_score_below_min_crop_score_or_not_associated():
    registry = IntrusionRegistry()
    enc = FakeEncoder()
    collector = _collector(registry, encode=enc)
    _bind_entry(registry, ts=10.0)
    registry.touch(5, 1, BBOX, 10.0)
    collector.observe([face(score=0.4)], None, 1920, 1080, 10.0)     # skor < MIN_CROP_SCORE
    collector.observe([face(cx=100.0)], None, 1920, 1080, 10.1)      # di luar kepala
    msgs = collector.drain(10.0 + IDENT_WINDOW_S)
    assert len(msgs) == 1 and msgs[0]["_crop"] is None and enc.boxes == []


def test_collector_stats_counts_are_isolated_from_attendance_funnel():
    """Penolakan identitas memakai dict sendiri (tes lama _funnel attendance tidak boleh berubah)."""
    registry = IntrusionRegistry()
    collector = _collector(registry)
    _bind_entry(registry, ts=10.0)
    registry.touch(5, 1, BBOX, 10.0)
    collector.observe([face(width=40.0)], None, 1920, 1080, 10.0)
    msg = collector.drain(10.0 + IDENT_WINDOW_S)[0]
    assert set(msg["stats"]["rejects"]) == {"small", "score", "yaw", "pitch", "blur", "quality"}


def test_collector_ignores_person_after_result_was_sent():
    """Orang yang masih di zona setelah pesan terkirim tidak dikumpulkan lagi (tanpa embed berulang)."""
    registry = IntrusionRegistry()
    emb = FakeEmbedder()
    collector = _collector(registry, embedder=emb)
    _bind_entry(registry, ts=10.0)
    registry.touch(5, 1, BBOX, 10.0)
    for i in range(3):
        collector.observe([face()], None, 1920, 1080, 10.0 + i * 0.1)
    registry.touch(5, 1, BBOX, 10.0 + IDENT_WINDOW_S - 0.1)
    assert len(collector.drain(10.0 + IDENT_WINDOW_S)) == 1
    calls_after_send = emb.embed_calls
    for i in range(20):  # CameraWorker terus men-touch track yang sama selama orangnya berdiam
        now = 19.0 + i * 0.1
        registry.touch(5, 1, BBOX, now)
        collector.observe([face()], None, 1920, 1080, now)
        assert collector.drain(now) == []
    assert emb.embed_calls == calls_after_send
    assert registry.entries() == []


SCORES_DOWN = [0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.62]


@pytest.mark.parametrize("scores,expected_embeds", [(SCORES_DOWN, BEST_K), (SCORES_DOWN[::-1], 8)])
def test_collector_keeps_only_the_best_k_frames_by_quality(scores, expected_embeds):
    """Frame awal biasanya terburuk (orang masih jauh): yang dipertahankan K terbaik, bukan K pertama."""
    registry = IntrusionRegistry()
    emb = FakeEmbedder()
    collector = _collector(registry, embedder=emb)
    registry.touch(5, 1, BBOX, 10.0)  # belum terikat: masih masa dwell sebelum trigger
    for i, sc in enumerate(scores):
        collector.observe([face(score=sc)], None, 1920, 1080, 10.0 + i * 0.05)
    registry.bind(5, 1, "ev-1", 10.5)
    msg = collector.drain(10.5 + IDENT_WINDOW_S)[0]
    assert emb.embed_calls == expected_embeds  # frame yang tidak mengalahkan K terbaik tidak di-embed
    assert msg["stats"]["frames_used"] == BEST_K and msg["stats"]["faces"] == 8
    assert msg["quality"] == pytest.approx(0.95)


def test_collector_crop_prefers_frontal_face_over_wider_turned_one():
    registry = IntrusionRegistry()
    collector = _collector(registry, encode=FakeEncoder())
    _bind_entry(registry, ts=10.0)
    registry.touch(5, 1, BBOX, 10.0)
    turned = [list(p) for p in FRONTAL]
    turned[2][0] = 80  # hidung bergeser ke samping: yaw ≈ 0,5
    collector.observe([face(width=100.0, kps=turned)], None, 1920, 1080, 10.0)  # lebih lebar, menoleh
    collector.observe([face(width=70.0)], None, 1920, 1080, 10.1)               # lebih sempit, frontal
    msg = collector.drain(10.0 + IDENT_WINDOW_S)[0]
    assert msg["_crop"] == b"jpg-70"


def test_collector_observe_returns_overlay_label_per_associated_face():
    """Overlay debugger: label mengikuti gerbang identitas (kepala orang), bukan status zona."""
    registry = IntrusionRegistry()
    collector = _collector(registry)
    registry.touch(5, 1, BBOX, 10.0)
    good, small, stray = face(width=120.0), face(width=40.0), face(cx=200.0, cy=900.0, width=120.0)
    labels = collector.observe([good, small, stray], None, 1920, 1080, 10.0)
    assert labels[id(good)] == "0.90" and labels[id(small)] == "small"
    assert id(stray) not in labels  # bukan kepala siapa pun: tidak berlabel identitas


def test_collector_flush_emits_bound_entries_without_waiting():
    registry = IntrusionRegistry()
    collector = _collector(registry)
    _bind_entry(registry, ts=10.0)
    registry.touch(5, 1, BBOX, 10.0)
    registry.touch(5, 2, BBOX, 10.0)  # belum terikat: tidak dikirim
    collector.observe([face()], None, 1920, 1080, 10.0)
    msgs = collector.flush()
    assert [m["event_id"] for m in msgs] == ["ev-1"] and msgs[0]["embedding"] is not None


def test_collector_drops_state_of_person_who_left_before_event():
    registry = IntrusionRegistry()
    collector = _collector(registry)
    registry.touch(5, 1, BBOX, 10.0)
    collector.observe([face()], None, 1920, 1080, 10.0)
    assert collector.drain(10.0 + REGISTRY_TTL_S + 0.1) == []
    assert collector._states == {}  # kebocoran memori adalah properti internal kolektor


def test_collector_counts_unexpected_gate_code_instead_of_raising():
    """Pusat wajah di luar frame (kode gate 'zone') tidak boleh melempar KeyError."""
    registry = IntrusionRegistry()
    collector = _collector(registry)
    _bind_entry(registry, ts=10.0)
    registry.touch(5, 1, (-0.30, 0.10, 0.10, 0.95), 10.0)  # area kepala memuat x negatif
    collector.observe([face(cx=-96.0, cy=200.0, width=120.0)], None, 1920, 1080, 10.0)
    msg = collector.drain(10.0 + IDENT_WINDOW_S)[0]
    assert msg["stats"]["rejects"]["zone"] == 1
