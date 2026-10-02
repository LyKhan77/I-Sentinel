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
