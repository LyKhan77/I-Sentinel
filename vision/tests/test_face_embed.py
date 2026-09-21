"""Opsi B: FaceEmbedder di node — lazy import, fallback, embed_jpeg."""
import numpy as np
import pytest

from vision.face import FaceEmbedder


def _jpeg_bytes(w=320, h=240):
    import cv2
    img = np.zeros((h, w, 3), np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


class FakeApp:
    """Fake insightface FaceAnalysis: satu 'wajah' fixed."""

    def get(self, img):
        class F:
            det_score = 0.9
            bbox = np.array([10.0, 10.0, 100.0, 100.0])
            normed_embedding = np.ones(512) / np.sqrt(512)
        return [F()]


def test_embedder_unavailable_without_insightface(monkeypatch):
    import sys
    # dev/CI env tidak punya insightface — paksa jalur ImportError deterministik
    monkeypatch.setitem(sys.modules, "insightface", None)
    monkeypatch.setitem(sys.modules, "insightface.app", None)
    emb = FaceEmbedder(model_root="/tmp/x")
    assert emb.available() is False
    assert emb.embed_jpeg(_jpeg_bytes()) is None
    assert emb._failed is True  # kegagalan di-cache, tidak retry tiap call


def test_embedder_not_retried_after_failure(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "insightface", None)
    emb = FaceEmbedder(model_root="/tmp/x")
    assert emb.embed_jpeg(_jpeg_bytes()) is None
    assert emb.embed_jpeg(_jpeg_bytes()) is None  # kedua kalinya: cache, bukan retry


def test_embed_jpeg_returns_vector_and_quality():
    emb = FaceEmbedder(model_root="/tmp/x")
    emb._app = FakeApp()  # inject, skip load
    res = emb.embed_jpeg(_jpeg_bytes())
    assert res is not None
    assert len(res["vector"]) == 512
    assert res["det_score"] == pytest.approx(0.9)


def test_embed_jpeg_no_face_returns_none():
    emb = FaceEmbedder(model_root="/tmp/x")
    emb._app = FakeApp()
    emb._app.get = lambda img: []
    assert emb.embed_jpeg(_jpeg_bytes()) is None


def test_embed_jpeg_bad_jpeg_returns_none():
    emb = FaceEmbedder(model_root="/tmp/x")
    emb._app = FakeApp()
    assert emb.embed_jpeg(b"notjpeg") is None
