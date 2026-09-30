"""CPU/RAM host API dari /proc (stdlib).

# ponytail: logika sama dengan vision/vision/hardware.py host_stats — sengaja diduplikasi kecil karena vision
# tidak boleh bergantung pada backend dan sebaliknya; satukan bila ada paket bersama.
"""
from __future__ import annotations

import os

_prev_cpu: tuple[int, int] | None = None


def cpu_pct(proc_root: str = "/proc") -> float | None:
    global _prev_cpu
    try:
        with open(os.path.join(proc_root, "stat")) as f:
            vals = [int(v) for v in f.readline().split()[1:9]]
    except (OSError, ValueError, IndexError):
        return None
    idle, total = vals[3] + vals[4], sum(vals)
    prev, _prev_cpu = _prev_cpu, (total - idle, total)
    if prev is None or total <= prev[1]:
        return None
    return round((total - idle - prev[0]) / (total - prev[1]) * 100, 1)


def ram_mb(proc_root: str = "/proc") -> tuple[int | None, int | None]:
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
    return round((info["MemTotal"] - info["MemAvailable"]) / 1024), round(info["MemTotal"] / 1024)
