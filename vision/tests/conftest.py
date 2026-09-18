import types

import pytest


@pytest.fixture
def fake_nvml(monkeypatch):
    """Install a fake pynvml with `n` GPUs. Returns a registrar gpus([...])."""

    class _Env:
        gpus = []

    class FakeNVML:
        @staticmethod
        def nvmlInit():
            pass

        @staticmethod
        def nvmlDeviceGetCount():
            return len(_Env.gpus)

        @staticmethod
        def nvmlDeviceGetHandleByIndex(i):
            return ("h", i)

        @staticmethod
        def nvmlDeviceGetName(h):
            return _Env.gpus[h[1]]["name"]

        @staticmethod
        def nvmlDeviceGetMemoryInfo(h):
            g = _Env.gpus[h[1]]
            return types.SimpleNamespace(used=g["used"] * 2**20, total=g["total"] * 2**20)

        @staticmethod
        def nvmlDeviceGetUtilizationRates(h):
            return types.SimpleNamespace(gpu=_Env.gpus[h[1]]["util"], memory=0)

        @staticmethod
        def nvmlDeviceGetComputeRunningProcesses(h):
            return [types.SimpleNamespace(pid=p["pid"], usedGpuMemory=p["mem"] * 2**20)
                    for p in _Env.gpus[h[1]]["procs"]]

        @staticmethod
        def nvmlSystemGetProcessName(pid):
            for g in _Env.gpus:
                for p in g["procs"]:
                    if p["pid"] == pid:
                        return p["name"]
            return None

    monkeypatch.setitem(__import__("sys").modules, "pynvml", FakeNVML)

    def install(gpus):
        """gpus: list of dicts {name, used, total, util, procs} or tuple shortcuts."""
        _Env.gpus = [
            dict(g) if isinstance(g, dict) else
            {"name": g[0], "used": g[1], "total": g[2], "util": g[3],
             "procs": [{"pid": p, "name": n, "mem": m} for p, n, m in g[4]]}
            for g in gpus
        ]
        return _Env

    return install
