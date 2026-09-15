"""Unduh model wajah buffalo_l ke face_model_dir (bring-up server, bukan bagian test/CI).

InsightFace mengunduh otomatis saat FaceAnalysis(name=..., root=...) diinisialisasi.
"""
import argparse
import os

from app.core.config import settings


def main() -> None:
    ap = argparse.ArgumentParser(description="Download InsightFace buffalo_l models")
    ap.add_argument("--dir", default=settings.face_model_dir, help="target model dir (default: face_model_dir)")
    args = ap.parse_args()

    root = os.path.expanduser(args.dir)
    os.makedirs(root, exist_ok=True)

    from insightface.app import FaceAnalysis

    app = FaceAnalysis(name="buffalo_l", root=root, providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    print(f"buffalo_l siap di {root}")
    for d in sorted(os.listdir(root)):
        print(f"  {d}")


if __name__ == "__main__":
    main()
