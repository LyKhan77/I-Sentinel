"""R5b end-to-end di GPU server: SCRFD + ArcFace asli pada foto enrollment.

Jalankan di server GPU (gspe-ai3):
    cd /home/gspe-ai3/project_cv/I-Sentinel && set -a && . ./vision.env && set +a \
    && /home/gspe-ai3/vision-venv/bin/python -m pytest vision/tests/test_face_worker_gpu.py -q -m gpu

Prasyarat: `VISION_FACE_MODEL_DIR` menunjuk direktori model wajah (SCRFD + ArcFace)
dan folder `../faces/<employee>/*_crop.jpg` berisi foto enrollment asli.
"""
import glob
import os

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.gpu

ROOT = os.environ.get("VISION_FACE_MODEL_DIR", "")
PHOTOS = sorted(glob.glob(os.path.join(os.path.dirname(ROOT), "faces", "*", "*_crop.jpg")))


@pytest.mark.skipif(not ROOT or not PHOTOS, reason="butuh VISION_FACE_MODEL_DIR + foto enrollment")
def test_real_models_embed_enrollment_photo_consistently():
    from vision.face import FaceEmbedder

    emb = FaceEmbedder(ROOT, "cuda:2")
    img = cv2.imread(PHOTOS[0])
    faces = emb.detect_faces(img)
    assert faces, "SCRFD tidak menemukan wajah di foto enrollment"
    f = max(faces, key=lambda d: d.bbox[2] - d.bbox[0])
    v1 = np.array(emb.embed(emb.align(img, f.kps)))
    v2 = np.array(emb.embed(emb.align(cv2.GaussianBlur(img, (3, 3), 0), f.kps)))
    assert float(v1 @ v2) > 0.9  # foto yang sama, sedikit diburamkan -> tetap orang yang sama
