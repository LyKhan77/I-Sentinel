"""Password kamera di file rahasia server, bukan di DB.

DB hanya menyimpan referensi `store:cred_<id>` (CredentialProfile.secret_ref). File JSON
0600 (direktori 0700), ditulis atomik, dan wajib di luar storage_root karena storage_root
disajikan lewat /api/v1/media. API berjalan sebagai satu proses → satu lock cukup.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading

from app.core.config import settings

_lock = threading.Lock()


class SecretStoreError(RuntimeError):
    """File rahasia tidak aman atau tidak bisa dibaca/ditulis."""


def _path() -> str:
    path = os.path.realpath(os.path.expanduser(settings.camera_secrets_file))
    root = os.path.realpath(settings.storage_root)
    if path == root or path.startswith(root + os.sep):
        raise SecretStoreError("camera_secrets_file must be outside storage_root")
    return path


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise SecretStoreError(f"cannot read secret store: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _write(path: str, data: dict) -> None:
    folder = os.path.dirname(path)
    try:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".secrets-")
    except OSError as exc:
        raise SecretStoreError(f"cannot write secret store: {exc}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise SecretStoreError(f"cannot write secret store: {exc}") from exc


def put(key: str, value: str) -> None:
    with _lock:
        path = _path()
        data = _load(path)
        data[key] = value
        _write(path, data)


def get(key: str) -> str | None:
    with _lock:
        value = _load(_path()).get(key)
    return value if isinstance(value, str) else None


def delete(key: str) -> None:
    with _lock:
        path = _path()
        data = _load(path)
        if data.pop(key, None) is not None:
            _write(path, data)
