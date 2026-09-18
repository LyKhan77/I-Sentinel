"""GPU hardware probe via NVML. Graceful fallback: no NVIDIA/pynvml -> {}.

Vulkan/CUDA index order is assumed identical to NVML index order
(# ponytail: PCI order mismatch rare; fail-fast pin check would need
torch.cudaDeviceCount which drags torch import into heartbeat path).
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


def collect_gpu_info() -> dict:
    """Probe all GPUs: name, VRAM used/total, util %, per-process consumers.

    Never raises — returns {} when pynvml is missing or NVML init fails
    (JVM edge node / WSL / driver absent), so the heartbeat keeps flowing.
    """
    try:
        import pynvml

        pynvml.nvmlInit()
        gpus = []
        my_pid = None
        try:
            import os

            my_pid = os.getpid()
        except Exception:
            pass
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(h)
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            procs = []
            for p in pynvml.nvmlDeviceGetComputeRunningProcesses(h):
                pname = None
                try:
                    pname = pynvml.nvmlSystemGetProcessName(p.pid)
                    if isinstance(pname, bytes):
                        pname = pname.decode("utf-8", "replace")
                except Exception:
                    pass  # cross-user/permission: show pid only
                procs.append({
                    "pid": p.pid,
                    "name": pname or f"pid {p.pid}",
                    "user": None,  # NVML does not expose owner; UI hides when null
                    "mem_mb": round(p.usedGpuMemory / 2**20) if p.usedGpuMemory else None,
                })
            gpus.append({
                "idx": i,
                "name": name,
                "vram_used_mb": round(mem.used / 2**20),
                "vram_total_mb": round(mem.total / 2**20),
                "util_pct": util.gpu,
                "processes": procs,
            })
        own = sum(
            p["mem_mb"] or 0
            for g in gpus for p in g["processes"] if p["pid"] == my_pid
        )
        return {"gpus": gpus, "python_vram_mb": own or None}
    except Exception:
        log.debug("GPU probe unavailable (no pynvml/NVIDIA?)", exc_info=True)
        return {}


def gpu_count() -> int:
    return len(collect_gpu_info().get("gpus", []))


_CUDA_PIN_RE = re.compile(r"^cuda:(\d+)$")


def validate_device_pin(pin: str) -> str | None:
    """Return an error message when a VISION_DETECTOR_DEVICE pin is invalid.

    Empty/None pin = auto -> always valid. Valid cuda:N requires NVML to see
    at least N+1 GPUs. Non-cuda values ("cpu", "mps", ...) pass through:
    ultralytics owns their validation.
    """
    if not pin:
        return None
    m = _CUDA_PIN_RE.match(pin.strip())
    if not m:
        return None
    n = gpu_count()
    if n <= int(m.group(1)):
        return f"detector device pin {pin!r} invalid: only {n} GPU visible"
    return None
