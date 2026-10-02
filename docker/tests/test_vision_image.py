"""Protect locked GPU dependencies and target-GPU engine export."""
import os
from pathlib import Path
import re
import subprocess

DOCKER = Path(__file__).resolve().parents[1]


def test_lock_is_fully_pinned():
    lines = (DOCKER / "vision/requirements.lock").read_text().splitlines()
    for line in lines:
        if line.strip() and not line.startswith("#"):
            assert re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", line), line


def test_lock_pins_gpu_stack():
    packages = {line.split("==")[0].lower().replace("_", "-")
                for line in (DOCKER / "vision/requirements.lock").read_text().splitlines()
                if line and not line.startswith("#")}
    assert {"torch", "tensorrt-cu13", "onnxruntime-gpu", "ultralytics", "insightface"} <= packages


def test_export_engine_dry_run_pins_gpu():
    result = subprocess.run(["bash", str(DOCKER / "scripts/export-engine.sh"), "--dry-run", "1"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "CUDA_VISIBLE_DEVICES=1" in result.stdout
    assert "--workdir /models" in result.stdout
    assert "--profile vision run --rm -T --no-deps" in result.stdout
    assert "python /app/vision/scripts/export_engine.py --model yolo26s.pt" in result.stdout


def test_export_engine_rejects_non_numeric_gpu():
    result = subprocess.run(["bash", str(DOCKER / "scripts/export-engine.sh"), "--dry-run", "gpu1"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "GPU" in result.stderr


def test_export_engine_run_is_non_interactive():
    """Tanpa -T, `compose run` meminta TTY dan gagal bila dijalankan lewat ssh tanpa tty."""
    result = subprocess.run(["bash", str(DOCKER / "scripts/export-engine.sh"), "--dry-run", "0"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert " -T " in result.stdout


def test_image_ships_cuda12_runtime_for_onnxruntime_gpu():
    """onnxruntime-gpu dari PyPI adalah build CUDA 12 (di server dev ia memakai /usr/local/cuda-12.8),
    sedangkan base image dan wheel torch/TensorRT adalah CUDA 13. Tanpa library CUDA 12, provider CUDA
    tidak termuat dan face embedder diam-diam jatuh ke CPU (CPU container 977%)."""
    lock = (DOCKER / "vision/requirements.lock").read_text()
    assert re.search(r"^onnxruntime-gpu==", lock, re.M)
    dockerfile = (DOCKER / "vision/Dockerfile").read_text()
    for package in ["cuda-cudart-12-8", "libcublas-12-8", "libcufft-12-8", "libcurand-12-8", "libcudnn9-cuda-12"]:
        assert package in dockerfile, package

