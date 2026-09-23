"""Node optional face model settings and construction (no GPU)."""
from vision.config import NodeSettings
from vision.node import VisionNode


class FakeTransport:
    def close(self):
        pass


def test_settings_face_fields_default():
    cfg = NodeSettings()
    assert cfg.face_embed is True
    assert cfg.face_device == ""
    assert cfg.face_model_dir == ""


def test_node_creates_embedder_when_enabled(tmp_path):
    cfg = NodeSettings(node_id="n1", cameras_json="[]", face_model_dir=str(tmp_path))
    node = VisionNode(cfg, transport=FakeTransport())
    assert node.face is not None


def test_node_no_embedder_when_disabled(tmp_path):
    cfg = NodeSettings(node_id="n1", cameras_json="[]", face_embed=False,
                       face_model_dir=str(tmp_path))
    node = VisionNode(cfg, transport=FakeTransport())
    assert node.face is None
