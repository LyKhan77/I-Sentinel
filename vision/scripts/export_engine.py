"""Export YOLO26s ke TensorRT FP16 (nms=False e2e head) — jalan di server GPU.

Usage (di gspe-ai3, venv vision dengan ultralytics terpasang):
    python vision/scripts/export_engine.py [--model yolo26s.pt] [--imgsz 640]

Output: <model>-engine.engine di cwd vision/scripts/../ (tidak di-commit).
"""
import argparse
import time
from pathlib import Path

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo26s.pt")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--half", action="store_true", default=True)
    args = ap.parse_args()

    from ultralytics import YOLO

    print(f"[export] loading {args.model} ...")
    model = YOLO(args.model)

    print(f"[export] exporting TensorRT engine (imgsz={args.imgsz}, half={args.half}, nms=False) ...")
    t0 = time.time()
    path = model.export(
        format="engine",
        imgsz=args.imgsz,
        half=args.half,
        nms=False,          # e2e one-to-one head: NMS-free, output (N,300,6)
        device=0,
        workspace=4,
    )
    print(f"[export] done in {time.time()-t0:.1f}s -> {path}")

    # smoke: inferensi satu frame sintetis + latency
    print("[smoke] running 20 warmup + 50 measured inferences ...")
    frame = np.random.randint(0, 255, (args.imgsz, args.imgsz, 3), dtype=np.uint8)
    for _ in range(20):
        model.predict(frame, imgsz=args.imgsz, verbose=False)
    t0 = time.time()
    for _ in range(50):
        r = model.predict(frame, imgsz=args.imgsz, verbose=False)
    dt = (time.time() - t0) / 50 * 1000
    print(f"[smoke] latency: {dt:.1f} ms/frame (batch 1, includes pre/post)")
    print(f"[smoke] output: {type(r[0].boxes).__name__}, engine file: {path}")
    eng = Path(str(path))
    print(f"[smoke] engine size: {eng.stat().st_size/1e6:.0f} MB")


if __name__ == "__main__":
    main()
