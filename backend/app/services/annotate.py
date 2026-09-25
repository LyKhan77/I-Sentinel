"""Anotasi identitas pada file crop attendance (R1). Best-effort, overwrite di tempat."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from . import face

# warna aksen hijau Carbon-ish; konsisten dengan bbox hijau dari vision node
GREEN = (0, 160, 0)
ORANGE = (230, 130, 0)


def annotate_face_crop(image_path: str, name: str, score: float,
                       bbox: list[float] | None = None) -> None:
    """Gambar nama + match score pada file crop (overwrite).

    bbox = koordinat wajah relatif crop (dari node) — bila ada, digambar rect
    di situ; tanpa bbox cukup border + teks. Best-effort: file hilang/corrupt
    → log + lanjut (attendance tidak boleh gagal karena anotasi).
    """
    try:
        img = Image.open(image_path)
        img.load()
    except Exception:
        face.logger.warning("annotate: tidak bisa buka crop %s", image_path, exc_info=True)
        return
    try:
        d = ImageDraw.Draw(img)
        w, h = img.size
        if bbox and len(bbox) == 4:
            d.rectangle([int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
                        outline=GREEN, width=3)
        else:
            d.rectangle([0, 0, w - 1, h - 1], outline=GREEN, width=3)
        d.text((6, h - 22), f"{name} {score:.2f}", fill=GREEN)
        img.save(image_path)
    except Exception:
        face.logger.warning("annotate: gambar gagal %s", image_path, exc_info=True)


def annotate_snapshot(image_path: str, label: str, bbox_norm: list[float] | None,
                      color=GREEN) -> None:
    """Label (nama karyawan / Unknown) di atas kotak wajah pada snapshot frame penuh (overwrite).

    bbox_norm relatif frame (payload node). Best-effort: file hilang/corrupt → log + lanjut.
    """
    try:
        img = Image.open(image_path)
        img.load()
    except Exception:
        face.logger.warning("annotate: tidak bisa buka snapshot %s", image_path, exc_info=True)
        return
    try:
        img = img.convert("RGB")
        d = ImageDraw.Draw(img)
        w, h = img.size
        x, y = 8, 8
        if bbox_norm and len(bbox_norm) == 4:
            x, y = int(bbox_norm[0] * w), int(bbox_norm[1] * h)
        size = max(14, w // 45)
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:  # Pillow lama tanpa argumen size
            font = ImageFont.load_default()
        tw = int(d.textlength(label, font=font))
        top = max(0, y - size - 8)
        d.rectangle([x, top, x + tw + 10, top + size + 6], fill=color)
        d.text((x + 5, top + 2), label, fill=(255, 255, 255), font=font)
        img.save(image_path, "JPEG", quality=90)
    except Exception:
        face.logger.warning("annotate: label snapshot gagal %s", image_path, exc_info=True)
