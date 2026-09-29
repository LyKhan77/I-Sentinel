"""GPU hardware probe via NVML. Graceful fallback: no NVIDIA/pynvml -> {}.

Vulkan/CUDA index order is assumed identical to NVML index order
(# ponytail: PCI order mismatch rare; fail-fast pin check would need
torch.cudaDeviceCount which drags torch import into heartbeat path).
"""
from __future__ import annotations

import logging
import os
import re
import shutil

log = logging.getLogger(__name__)

_prev_cpu: tuple[int, int] | None = None  # (busy, total) jiffies sampel sebelumnya


def _cpu_pct(proc_root: str) -> float | None:
    global _prev_cpu
    try:
        with open(os.path.join(proc_root, "stat")) as f:
            parts = f.readline().split()
        vals = [int(v) for v in parts[1:9]]  # user nice system idle iowait irq softirq steal
    except (OSError, ValueError, IndexError):
        return None
    idle = vals[3] + vals[4]
    total = sum(vals)
    prev, _prev_cpu = _prev_cpu, (total - idle, total)
    if prev is None or total <= prev[1]:
        return None
    return round((total - idle - prev[0]) / (total - prev[1]) * 100, 1)


def _ram_mb(proc_root: str) -> tuple[int | None, int | None]:
    info = {}
    try:
        with open(os.path.join(proc_root, "meminfo")) as f:
            for line in f:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0])
    except (OSError, ValueError, IndexError):
        return None, None
    if "MemTotal" not in info or "MemAvailable" not in info:
        return None, None
    total = round(info["MemTotal"] / 1024)
    return round((info["MemTotal"] - info["MemAvailable"]) / 1024), total


def host_stats(data_dir: str, proc_root: str = "/proc") -> dict:
    """CPU % (selisih antar panggilan), RAM, disk data_dir. Stdlib saja; field tak tersedia → None."""
    used, total = _ram_mb(proc_root)
    disk_pct = disk_free = None
    try:
        path = os.path.expanduser(data_dir)
        u = shutil.disk_usage(path if os.path.isdir(path) else os.path.dirname(path) or ".")
        disk_pct = round(u.used / u.total * 100, 1) if u.total else None
        disk_free = round(u.free / 1024 ** 3, 1)
    except OSError:
        pass
    return {"cpu_pct": _cpu_pct(proc_root), "ram_used_mb": used, "ram_total_mb": total,
            "disk_used_pct": disk_pct, "disk_free_gb": disk_free}


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
            temp_c = power_w = None
            try:
                temp_c = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                pass
            try:
                power_w = round(pynvml.nvmlDeviceGetPowerUsage(h) / 1000, 1)  # mW → W
            except Exception:
                pass
            gpus.append({
                "idx": i,
                "name": name,
                "vram_used_mb": round(mem.used / 2**20),
                "vram_total_mb": round(mem.total / 2**20),
                "util_pct": util.gpu,
                "temp_c": temp_c,
                "power_w": power_w,
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
