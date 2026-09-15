"""Face recognition: InsightFace (SCRFD + ArcFace) wrapper, in-memory gallery, cosine match.

insightface/onnxruntime tidak dipasang di venv dev/CI. Import ada di dalam
FaceEngine._ensure_loaded supaya modul ini (dan test) jalan tanpa dependency itu —
test memakai monkeypatch FaceEngine.embed.
"""
import logging
import os
from dataclasses import dataclass

from app.core.config import settings
from app.models.face_embedding import FaceEmbedding

logger = logging.getLogger(__name__)

# buffalo_l: SCRFD-10GF detector + w600k_r50 ArcFace recognizer → 512-d L2-normed vector.
# Panjang vektor tidak di-hardcode di sini: gallery/cosine menerima panjang apa pun.


@dataclass
class FaceResult:
    vector: list[float]
    det_score: float
    bbox: list[float]
    quality: float


@dataclass
class MatchResult:
    employee_id: int | None
    score: float | None
    quality: float | None
    reason: str


def cosine(a, b) -> float:
    """Cosine similarity via dot product (vektor ArcFace sudah L2-normed). Guard zero-norm."""
    if len(a) != len(b):
        raise ValueError(f"cosine: length mismatch {len(a)} != {len(b)}")
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _best_face(faces: list[FaceResult]) -> FaceResult:
    """Wajah dengan area bbox terbesar — crop CCTV sering memuat beberapa orang."""
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))


class FaceEngine:
    """Wrapper tipis FaceAnalysis. Lazy: import + muat model hanya saat dipakai."""

    def __init__(self):
        self._app = None
        self._available = None

    def _model_root(self) -> str:
        return os.path.expanduser(settings.face_model_dir)

    def _ensure_loaded(self):
        """Lazy import insightface + muat buffalo_l. Raise RuntimeError bila tidak bisa."""
        if self._app is not None:
            return self._app
        try:
            from insightface.app import FaceAnalysis
        except ImportError as e:
            raise RuntimeError(f"insightface tidak terpasang: {e}") from e

        root = self._model_root()
        last = None
        # CUDA dulu (kalau ada), fallback CPU. ctx_id=0 diabaikan provider CPU.
        for providers in (
            ["CUDAExecutionProvider", "CPUExecutionProvider"],
            ["CPUExecutionProvider"],
        ):
            try:
                app = FaceAnalysis(name="buffalo_l", root=root, providers=providers)
                app.prepare(ctx_id=0, det_size=(640, 640))
            except Exception as e:  # onnxruntime error, model korup, provider tidak ada
                last = e
                continue
            self._app = app
            return app
        raise RuntimeError(f"model wajah gagal dimuat dari {root}: {last}")

    def available(self) -> bool:
        """True bila insightface bisa dimuat dan model dir terisi. Hasil di-cache; log sekali."""
        if self._available is not None:
            return self._available
        root = self._model_root()
        if not os.path.isdir(root) or not os.listdir(root):
            self._available = False
            logger.info("Face engine tidak tersedia: model dir kosong (%s)", root)
            return False
        try:
            self._ensure_loaded()
        except Exception:
            self._available = False
            logger.info("Face engine tidak tersedia: import/model gagal", exc_info=True)
            return False
        self._available = True
        return True

    def embed(self, image_path: str) -> list[FaceResult]:
        """Deteksi + embedding semua wajah di image_path. Raise RuntimeError bila engine tidak siap."""
        app = self._ensure_loaded()
        try:
            import cv2
        except ImportError as e:
            raise RuntimeError(f"opencv tidak terpasang: {e}") from e

        img = cv2.imread(image_path)
        if img is None:
            return []

        out: list[FaceResult] = []
        for f in app.get(img):
            normed = getattr(f, "normed_embedding", None)
            if normed is None:  # recognition model tidak dimuat → tidak bisa dipakai
                continue
            x1, y1, x2, y2 = (float(v) for v in f.bbox)
            det = float(f.det_score)
            # quality: deteksi yakin × wajah cukup besar (96 px ≈ minimum ArcFace)
            quality = det * min(1.0, max(0.0, x2 - x1) / 96.0)
            out.append(
                FaceResult(
                    vector=[float(v) for v in normed],
                    det_score=det,
                    bbox=[x1, y1, x2, y2],
                    quality=quality,
                )
            )
        return out


class FaceGallery:
    """In-memory employee_id → list[vector]. Vector disimpan sebagai list[float] biasa (tanpa numpy)."""

    def __init__(self):
        self._by_employee: dict[int, list[list[float]]] = {}

    def load(self, db) -> None:
        grouped: dict[int, list[list[float]]] = {}
        for row in db.query(FaceEmbedding).all():
            grouped.setdefault(row.employee_id, []).append([float(x) for x in row.vector])
        self._by_employee = grouped

    def refresh(self, db) -> None:
        self.load(db)

    def match(self, vector) -> tuple[int, float] | None:
        """Skor tertinggi antar semua embedding; None bila < settings.face_match_threshold."""
        best_id = None
        best_score = -1.0
        for employee_id, vectors in self._by_employee.items():
            for v in vectors:
                s = cosine(vector, v)
                if s > best_score:
                    best_id, best_score = employee_id, s
        if best_id is None or best_score < settings.face_match_threshold:
            return None
        return best_id, best_score

    def size(self) -> int:
        """Jumlah employee terdaftar (bukan jumlah vektor)."""
        return len(self._by_employee)

    def remove(self, employee_id: int) -> None:
        self._by_employee.pop(employee_id, None)


engine = FaceEngine()
gallery = FaceGallery()


def refresh_gallery(db) -> FaceGallery:
    """Muat ulang gallery dari DB. Panggil di startup, setelah enroll, setelah delete/purge."""
    gallery.refresh(db)
    return gallery


def match_crop(db, image_path: str) -> MatchResult:
    """Embed satu crop lalu cocokkan ke gallery. reason: not_configured|no_face|low_quality|matched|no_match."""
    try:
        faces = engine.embed(image_path)
    except RuntimeError:
        logger.info("match_crop: face engine tidak tersedia", exc_info=True)
        return MatchResult(None, None, None, "not_configured")

    if not faces:
        return MatchResult(None, None, None, "no_face")

    face = _best_face(faces)
    if face.quality < settings.face_min_quality:
        return MatchResult(None, None, face.quality, "low_quality")

    hit = gallery.match(face.vector)
    if hit is None:
        return MatchResult(None, None, face.quality, "no_match")

    employee_id, score = hit
    return MatchResult(employee_id, score, face.quality, "matched")


def enroll_embedding(db, employee_id: int, image_path: str) -> FaceEmbedding:
    """Embed wajah pertama di image_path dan simpan row. ValueError bila tidak ada wajah / kualitas rendah.

    Tidak refresh gallery — caller yang tahu kapan (lihat refresh_gallery).
    """
    faces = engine.embed(image_path)
    if not faces:
        raise ValueError("no_face")

    face = _best_face(faces)
    if face.quality < settings.face_min_quality:
        raise ValueError("low_quality")

    row = FaceEmbedding(
        employee_id=employee_id,
        vector=[float(x) for x in face.vector],
        quality=face.quality,
        source_image_path=image_path,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
