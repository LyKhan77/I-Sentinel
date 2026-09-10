"""Disk-backed FIFO event queue: atomic put, drop-oldest over max_bytes. Pure stdlib."""
from __future__ import annotations

import json
import os
import threading


class DiskQueue:
    def __init__(self, directory: str, max_bytes: int = 100 * 1024 * 1024):
        self.dir = str(directory)
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        os.makedirs(self.dir, exist_ok=True)

    def _files(self) -> list[tuple[int, str]]:
        out = []
        for name in os.listdir(self.dir):
            base = name[:-5] if name.endswith(".json") else name[:-9] if name.endswith(".json.tmp") else None
            if base is not None and base.isdigit():
                out.append((int(base), name))
        out.sort()
        return out

    def put(self, item: dict) -> None:
        with self._lock:
            files = self._files()
            seq = (files[-1][0] + 1) if files else 0
            final = os.path.join(self.dir, f"{seq:012d}.json")
            tmp = final + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(item, f)
            os.replace(tmp, final)  # atomic on same filesystem
            self._enforce_max(seq)

    def _enforce_max(self, newest_seq: int) -> None:
        while True:
            files = self._files()
            total = sum(os.path.getsize(os.path.join(self.dir, n)) for _, n in files)
            if total <= self.max_bytes or len(files) <= 1:
                return
            seq, name = files[0]
            if seq >= newest_seq:
                return
            os.remove(os.path.join(self.dir, name))

    def pop(self) -> tuple[int, dict] | None:
        """Peek oldest (file stays until remove(seq))."""
        with self._lock:
            files = self._files()
            if not files:
                return None
            seq, name = files[0]
            with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                return seq, json.load(f)

    def remove(self, seq: int) -> None:
        with self._lock:
            path = os.path.join(self.dir, f"{seq:012d}.json")
            if os.path.exists(path):
                os.remove(path)

    def size(self) -> int:
        with self._lock:
            return len(self._files())
