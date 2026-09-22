"""Motion gate: inferensi hanya saat ada gerakan (+ interval paksa)."""
import numpy as np

from vision.motion import FrameMotionGate


def _static(n=6):
    return np.zeros((180, 320, 3), dtype=np.uint8)


def _with_block(x=40):
    f = np.zeros((180, 320, 3), dtype=np.uint8)
    f[60:120, x:x + 60] = 255
    return f


def test_first_frame_allowed_then_static_blocked():
    gate = FrameMotionGate(force_interval_s=100.0)
    assert gate.update(_static(), 0.0) is True      # frame pertama: tak ada pembanding
    assert gate.update(_static(), 0.2) is False     # statis → tahan
    assert gate.update(_static(), 0.4) is False


def test_moving_block_allows_detection():
    gate = FrameMotionGate(force_interval_s=100.0)
    gate.update(_with_block(40), 0.0)
    assert gate.update(_with_block(90), 0.2) is True
    assert gate.update(_with_block(140), 0.4) is True


def test_force_interval_rechecks_static_scene():
    gate = FrameMotionGate(force_interval_s=2.0)
    assert gate.update(_static(), 0.0) is True
    assert gate.update(_static(), 1.0) is False
    assert gate.update(_static(), 2.1) is True      # objek diam tetap dicek berkala


def test_small_noise_below_min_area_blocked():
    gate = FrameMotionGate(force_interval_s=100.0)
    gate.update(_static(), 0.0)
    noisy = _static()
    noisy[10:14, 10:14] = 255                        # blob kecil (16 px dari 5760)
    assert gate.update(noisy, 0.2) is False


def test_none_frame_allows_detection():
    assert FrameMotionGate().update(None, 0.0) is True


# --- integrasi worker: gate benar-benar menahan inferensi --------------------

class CountingDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, frame, ts=None):
        self.calls += 1
        return []


def _run_worker(frames, motion: dict | None):
    import threading
    from vision.config import CameraCfg
    from vision.node import CameraWorker
    from vision.pipeline.source import FrameSource

    cfg = CameraCfg(camera_id=1, source_url="test://1", ai_fps=5.0)
    det = CountingDetector()
    w = CameraWorker(cfg, lambda cid: det, object(), threading.Event(), "test-node",
                     analyzers=[], recorder=None, motion=motion)
    w.source = FrameSource.from_frames(frames, fps=5.0)
    w.start()
    w.join(timeout=10)
    return det


def test_worker_skips_inference_on_static_scene():
    frames = [np.zeros((180, 320, 3), dtype=np.uint8) for _ in range(10)]
    det = _run_worker(frames, {"enabled": True, "force_interval_s": 100.0})
    assert det.calls == 1                     # hanya frame pertama (tanpa pembanding)


def test_worker_without_gate_detects_every_frame():
    frames = [np.zeros((180, 320, 3), dtype=np.uint8) for _ in range(10)]
    det = _run_worker(frames, {"enabled": False})
    assert det.calls == 10


def test_worker_motion_missing_means_no_gate():
    frames = [np.zeros((180, 320, 3), dtype=np.uint8) for _ in range(3)]
    assert _run_worker(frames, None).calls == 3   # cfg pra-R5: tanpa motion = seperti dulu
