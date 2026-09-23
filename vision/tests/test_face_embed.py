"""FaceEmbedder lazy loading, SCRFD and ArcFace contracts without GPU."""
import sys
import types

import numpy as np
import pytest

from vision.face import FaceEmbedder


def test_embedder_unavailable_without_insightface(monkeypatch):
    import sys
    # dev/CI env tidak punya insightface — paksa jalur ImportError deterministik
    monkeypatch.setitem(sys.modules, "insightface", None)
    monkeypatch.setitem(sys.modules, "insightface.app", None)
    emb = FaceEmbedder(model_root="/tmp/x")
    assert emb.available() is False
    assert emb.detect_faces(np.zeros((8, 8, 3), np.uint8)) == []
    assert emb._failed is True  # kegagalan di-cache, tidak retry tiap call


def test_embedder_not_retried_after_failure(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "insightface", None)
    emb = FaceEmbedder(model_root="/tmp/x")
    assert emb.detect_faces(np.zeros((8, 8, 3), np.uint8)) == []
    assert emb.detect_faces(np.zeros((8, 8, 3), np.uint8)) == []  # kedua kalinya: cache, bukan retry


@pytest.mark.parametrize("device, expected_first", [
    ("cuda:2", ("CUDAExecutionProvider", {"device_id": 2})),
    ("cpu", "CPUExecutionProvider"),
])
def test_device_pin_reaches_onnxruntime_session(monkeypatch, device, expected_first):
    """insightface mengabaikan ctx_id >= 0: tanpa device_id di provider, sesi jatuh ke GPU 0
    (terbukti di server — model wajah mendarat di RTX 4090, bukan cuda:2)."""
    seen = {}

    class FakeFaceAnalysis:
        def __init__(self, name, root, providers, allowed_modules=None):
            seen["providers"] = providers

        def prepare(self, ctx_id, det_size):
            pass

    mod = types.ModuleType("insightface.app")
    mod.FaceAnalysis = FakeFaceAnalysis
    monkeypatch.setitem(sys.modules, "insightface", types.ModuleType("insightface"))
    monkeypatch.setitem(sys.modules, "insightface.app", mod)
    assert FaceEmbedder(model_root="/tmp/x", device=device).available() is True
    assert seen["providers"][0] == expected_first


class FakeDetModel:
    def detect(self, img, max_num=0, metric="default"):
        boxes = np.array([[10.0, 20.0, 110.0, 140.0, 0.9]])
        kps = np.array([[[40, 60], [80, 60], [60, 85], [45, 110], [75, 110]]], dtype=np.float32)
        return boxes, kps


class FakeRecModel:
    def get_feat(self, imgs):
        return np.full((1, 512), 2.0, dtype=np.float32)  # insightface returns unnormalized features


class FakeDetRecApp:
    det_model = FakeDetModel()
    models = {"recognition": FakeRecModel()}


def test_detect_faces_returns_pixel_box_landmarks_and_score():
    emb = FaceEmbedder(model_root="/tmp/x")
    emb._app = FakeDetRecApp()
    faces = emb.detect_faces(np.zeros((240, 320, 3), np.uint8))
    assert len(faces) == 1
    assert faces[0].bbox == (10.0, 20.0, 110.0, 140.0)
    assert faces[0].score == pytest.approx(0.9)
    assert faces[0].kps.shape == (5, 2)
    assert np.array_equal(faces[0].kps[0], [40, 60])
    assert emb.detect_n == 1


def test_embed_returns_unit_vector():
    emb = FaceEmbedder(model_root="/tmp/x")
    emb._app = FakeDetRecApp()
    vec = emb.embed(np.zeros((112, 112, 3), np.uint8))
    assert len(vec) == 512
    assert float(np.linalg.norm(vec)) == pytest.approx(1.0)
    assert emb.embed_n == 1


def test_align_uses_insightface_landmark_crop(monkeypatch):
    calls = {}
    kps = np.array([[40, 60], [80, 60], [60, 85], [45, 110], [75, 110]])
    frame = np.zeros((240, 320, 3), np.uint8)
    aligned = np.ones((112, 112, 3), np.uint8)

    def norm_crop(img, landmark, image_size):
        calls.update(img=img, landmark=landmark, image_size=image_size)
        return aligned

    mod = types.ModuleType("insightface.utils")
    mod.face_align = types.SimpleNamespace(norm_crop=norm_crop)
    monkeypatch.setitem(sys.modules, "insightface", types.ModuleType("insightface"))
    monkeypatch.setitem(sys.modules, "insightface.utils", mod)
    emb = FaceEmbedder(model_root="/tmp/x")
    assert emb.align(frame, kps) is aligned
    assert calls == {"img": frame, "landmark": kps, "image_size": 112}


def test_detect_and_embed_degrade_when_insightface_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "insightface", None)
    monkeypatch.setitem(sys.modules, "insightface.app", None)
    emb = FaceEmbedder(model_root="/tmp/x")
    assert emb.detect_faces(np.zeros((8, 8, 3), np.uint8)) == []
    assert emb.embed(np.zeros((112, 112, 3), np.uint8)) is None
    assert emb.loaded() is False


def test_loader_limits_modules_to_detection_and_recognition(monkeypatch):
    seen = {}

    class FakeFaceAnalysis:
        def __init__(self, name, root, providers, allowed_modules=None):
            seen["allowed_modules"] = allowed_modules

        def prepare(self, ctx_id, det_size):
            pass

    mod = types.ModuleType("insightface.app")
    mod.FaceAnalysis = FakeFaceAnalysis
    monkeypatch.setitem(sys.modules, "insightface", types.ModuleType("insightface"))
    monkeypatch.setitem(sys.modules, "insightface.app", mod)
    emb = FaceEmbedder(model_root="/tmp/x", device="cuda:2")
    assert emb.loaded() is False  # lazy load
    assert emb.available() is True
    assert seen["allowed_modules"] == ["detection", "recognition"]
