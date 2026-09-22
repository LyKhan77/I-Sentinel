"""Opsi B: node._attach_crop menempelkan embedding bila embedder siap."""
import numpy as np
import pytest

from vision.config import CameraCfg, NodeSettings
from vision.face import FaceEmbedder
from vision.node import CameraWorker


class FakeTransport:
    def publish_event(self, ev):
        pass

    def publish_heartbeat(self, hb):
        pass

    def publish_detections(self, camera_id, boxes):
        self.detections = getattr(self, 'detections', [])
        self.detections.append((camera_id, boxes))

    def close(self):
        pass


class FakeRecorder:
    def __init__(self, path="crops/x.jpg"):
        self.path = path
        self.uploaded = []

    def fetch_frame(self, stream_name):
        return None

    def upload_bytes(self, data, kind, content_type="image/jpeg"):
        self.uploaded.append((kind, data))
        return self.path

    def enqueue(self, ev):
        pass

    def close(self):
        pass


def _worker(recorder, face):
    cfg = CameraCfg(camera_id=1, source_url="test://1", ai_fps=5.0)
    w = CameraWorker(cfg, lambda cid: None, FakeTransport(), None, "test-node",
                     analyzers=[], recorder=recorder)
    w.face = face
    return w


class FakeEmbedder:
    """Embedder siap: satu wajah fixed (menggantikan FaceEmbedder asli)."""

    def embed_jpeg(self, jpeg):
        return {"vector": [0.1] * 512, "det_score": 0.9,
                "bbox": [10.0, 10.0, 100.0, 100.0]}


def _partial():
    return {"payload": {"needs_crop": True, "bbox_norm": [0.4, 0.4, 0.5, 0.6]}}


def _frame():
    class F:
        ts = 1.0
        data = np.zeros((480, 640, 3), np.uint8)
    return F()


def test_attach_crop_adds_embedding():
    rec = FakeRecorder()
    w = _worker(rec, FakeEmbedder())
    partial = _partial()
    w._attach_crop(partial, _frame())
    p = partial["payload"]
    assert p["crop_path"] == "crops/x.jpg"
    assert len(p["embedding"]) == 512
    assert p["face_quality"] == pytest.approx(0.9)
    assert p["face_bbox"] == [10.0, 10.0, 100.0, 100.0]


def test_attach_crop_draws_face_box_before_upload():
    """Crop yang di-upload berisi rect hijau di area bbox (anotasi sebelum upload)."""
    rec = FakeRecorder()
    w = _worker(rec, FakeEmbedder())
    # mainstream_crop mengembalikan jpeg polos putih
    import cv2
    ok, buf = cv2.imencode(".jpg", np.full((240, 320, 3), 255, np.uint8))
    assert ok
    w._mainstream_crop = lambda bbox: buf.tobytes()
    partial = _partial()
    w._attach_crop(partial, _frame())
    assert len(rec.uploaded) == 1
    up = rec.uploaded[0][1]  # (kind, data)
    assert up != buf.tobytes()  # anotasi mengubah bytes
    img = cv2.imdecode(np.frombuffer(up, np.uint8), cv2.IMREAD_COLOR)
    # tepi rect (x=10..100): cari pixel dengan hijau dominan (0,200,0) di dekat garis
    region = img[8:102, 8:102]
    green = ((region[:, :, 1] > 120) & (region[:, :, 0] < 120) &
             (region[:, :, 2] < 120)).sum()
    assert green > 20, "rect hijau tidak terdeteksi pada crop yang di-upload"


def test_attach_crop_fallback_without_embedder():
    rec = FakeRecorder()
    w = _worker(rec, None)
    partial = _partial()
    w._attach_crop(partial, _frame())
    p = partial["payload"]
    assert p["crop_path"] == "crops/x.jpg"  # status quo: crop tetap
    assert "embedding" not in p
    assert "face_quality" not in p


def test_attach_crop_fallback_embedder_unavailable():
    rec = FakeRecorder()
    emb = FaceEmbedder(model_root="/tmp/x")  # insightface tidak terpasang -> _failed
    w = _worker(rec, emb)
    partial = _partial()
    w._attach_crop(partial, _frame())
    p = partial["payload"]
    assert p["crop_path"] == "crops/x.jpg"
    assert "embedding" not in p


def test_settings_face_fields_default():
    cfg = NodeSettings()
    assert cfg.face_embed is True
    assert cfg.face_device == ""
    assert cfg.face_model_dir == ""


def test_node_creates_embedder_when_enabled(tmp_path):
    from vision.node import VisionNode
    cfg = NodeSettings(node_id="n1", cameras_json="[]",
                       face_model_dir=str(tmp_path))
    node = VisionNode(cfg, transport=FakeTransport())
    assert node.face is not None


def test_node_no_embedder_when_disabled(tmp_path):
    from vision.node import VisionNode
    cfg = NodeSettings(node_id="n1", cameras_json="[]", face_embed=False,
                       face_model_dir=str(tmp_path))
    node = VisionNode(cfg, transport=FakeTransport())
    assert node.face is None
