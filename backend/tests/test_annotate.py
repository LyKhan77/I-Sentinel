from PIL import Image

from app.services.annotate import ORANGE, annotate_snapshot


def _jpeg(path, size=(640, 480)):
    Image.new("RGB", size, (255, 255, 255)).save(path, "JPEG")


def test_annotate_snapshot_draws_label_above_box(tmp_path):
    p = tmp_path / "snap.jpg"
    _jpeg(p)
    annotate_snapshot(str(p), "Budi Santoso", [0.4, 0.4, 0.6, 0.7])
    img = Image.open(p).convert("RGB")
    # area label tepat di atas kotak (y = 0.4 * 480 = 192) tidak lagi putih
    crop = img.crop((256 + 2, 192 - 16, 256 + 40, 192 - 4))
    assert any(px != (255, 255, 255) for px in crop.getdata())


def test_annotate_snapshot_without_bbox_uses_top_left(tmp_path):
    p = tmp_path / "snap.jpg"
    _jpeg(p)
    annotate_snapshot(str(p), "Unknown", None, color=ORANGE)
    assert any(px != (255, 255, 255) for px in Image.open(p).convert("RGB").crop((0, 0, 60, 30)).getdata())


def test_annotate_snapshot_missing_file_is_noop(tmp_path):
    annotate_snapshot(str(tmp_path / "missing.jpg"), "X", None)  # tidak raise
