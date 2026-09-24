# Pendaftaran Kamera Sederhana Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supervisor mendaftarkan kamera cukup dengan Nama, Lokasi, IP, path mainstream/substream, dan pilihan kredensial; password kamera yang berbeda disimpan di file rahasia server, bukan DB.

**Architecture:** Backend: modul `secret_store` (file JSON 0600 di luar `storage_root`) + referensi `store:cred_<id>` di `CredentialProfile.secret_ref`; profil kredensial menerima `password` write-only; kamera direct-host (tanpa stream source) boleh memakai `credential_override`; probe bisa mengembalikan thumbnail JPEG base64. Frontend: `CameraWizard` dipangkas (path selalu tampil, Node + scan NVR di `<details>` Lanjutan, pilihan kredensial + form inline kredensial baru), halaman Kamera tanpa panel Sumber, menu Lanjutan (Import, Sync go2rtc, Kelola kredensial), kolom Kredensial.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic v2, pytest; React 19 + TypeScript + Carbon, Vitest + Testing Library; ffmpeg/ffprobe (sudah dipakai probe).

**Spec:** `docs/superpowers/specs/2026-09-24-camera-registration-simple-design.md`

## Global Constraints

- Branch `feat/camera-registration-simple` (sudah ada, dari `main` @ `cb695f5`; spec di `2a99bb3`).
- **Tanpa AI attribution** di commit/kode/docs (`AGENTS.md` §9 menimpa trailer default apa pun).
- Tanpa dependensi baru (backend maupun frontend). Tanpa migrasi DB.
- Zero-secret: password kamera tidak pernah ada di DB, response API, log, commit, atau file di `storage_root`.
- File rahasia: setting `camera_secrets_file` (env `CAMERA_SECRETS_FILE`), default `~/.isentinel/camera-secrets.json`, izin file `0600`, direktori `0700`, wajib di luar `storage_root`.
- Semua string UI lewat `frontend/src/app/i18n.tsx`, **kedua** bahasa (`id` dan `en`).
- Mobile 390 px tanpa overflow horizontal (form wizard + modal).
- Setiap task: commit Conventional Commits + satu bullet di `CHANGELOG.md` bagian `### Pendaftaran kamera sederhana (2026-09-24 – …)` (dibuat di Task 1, di atas `### Event clip pre-buffer (2026-09-24)`).
- Baseline `main` `cb695f5`: backend **342 passed**; vision **200 passed, 3 deselected** (tidak disentuh); frontend **121 passed**; build exit 0; lint = set rule+file lama.
- Server `gspe-ai3`: baca bebas; deploy/restart/tulis butuh izin user (Task 8).

## Deviasi dari spec (disengaja)

1. **`secret_ref` tetap ada di response profil** (bukan diganti `has_password`/`source`): isinya hanya referensi (`env:NAMA` / `store:cred_3`), tidak rahasia, dan UI bisa membaca jenisnya dari prefix. Tes lama yang memeriksa `secret_ref` tidak perlu diubah.
2. **Lokasi memakai `<datalist>` native** pada `TextInput` (pilih lokasi yang ada atau ketik baru), bukan Carbon `ComboBox`.
3. **Path file rahasia di dalam `storage_root` ditolak saat dipakai** (`SecretStoreError` → 500 saat simpan / 422 saat resolve), bukan dicek saat startup.
4. **Simpan tanpa tes**: klik Simpan pertama menampilkan peringatan "Koneksi belum dites. Klik Simpan sekali lagi untuk tetap menyimpan."; klik kedua menyimpan (tanpa dialog tambahan).
5. **`CameraSourcesPanel.tsx` dihapus** (spec: tidak dirender). State `sources` di `CamerasPage` ikut dihapus; backend stream-sources tetap.
6. **"Kredensial baru" = form inline** (`NewCredentialForm`) di bawah pilihan kredensial, bukan dialog di atas
   modal wizard: focus trap Carbon `ComposedModal` merebut fokus dari modal kedua sehingga field tak bisa
   diketik. Komponen yang sama dipakai di modal Kelola kredensial.
7. **Temuan kode**: `resolve_stream` mengabaikan `credential_override` bila kamera tidak punya stream source, dan API kamera + probe menolak kombinasi itu (422 "credential override requires a stream source"). Semua 13 kamera di server tanpa source, jadi Task 3 membuka kombinasi ini — tanpanya fitur kredensial per kamera tidak berfungsi.

## Review Focus

1. **Password berisi karakter khusus** (`@ : / #`) harus ter-encode di URL RTSP, bukan memecah host. Tes: Task 3 `test_direct_host_camera_uses_override_profile` (password `p@ss:w/rd#1`).
2. **Ganti kredensial saja saat edit kamera** harus ikut terkirim di PATCH dan memerlukan tes/ack seperti perubahan koneksi lain. Tes: Task 6 `edit: switching credential sends credential_override_id`.
3. **Profil yang sudah dinonaktifkan tetapi masih dipasang di kamera** tetap tampil terpilih saat kamera diedit (tidak diam-diam kembali ke Default). Tes: Task 6 bagian yang sama.
4. **Key `store:` hilang dari file rahasia** (restore server, file terhapus) → probe menjawab 422 "credential reference is unavailable", bukan 500. Tes: Task 3 `test_probe_missing_store_secret_is_422`.
5. **Supervisor menempel URL RTSP lengkap berisi kredensial ke kolom path** → yang terkirim hanya path. Tes: Task 6 `wizard: pasted RTSP URL keeps only the path`.

---

### Task 1: `secret_store` — file rahasia kamera

**Files:**
- Create: `backend/app/services/secret_store.py`
- Modify: `backend/app/core/config.py` (tambah setting setelah `storage_root`)
- Modify: `backend/app/services/stream_endpoint.py` (`_secret`)
- Modify: `.env.example`
- Test: `backend/tests/test_secret_store.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces:
  - `settings.camera_secrets_file: str = "~/.isentinel/camera-secrets.json"`
  - `secret_store.SecretStoreError(RuntimeError)`
  - `secret_store.put(key: str, value: str) -> None`, `secret_store.get(key: str) -> str | None`, `secret_store.delete(key: str) -> None`
  - `stream_endpoint._secret("store:<key>")` → nilai dari store; hilang/gagal → `StreamEndpointError("credential reference is unavailable")`

- [ ] **Step 1: Tulis tes yang gagal**

`backend/tests/test_secret_store.py`:

```python
import os
import stat

import pytest

from app.services import secret_store
from app.services.secret_store import SecretStoreError
from app.services.stream_endpoint import StreamEndpointError, _secret


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(secret_store.settings, "storage_root", str(tmp_path / "media"))
    path = tmp_path / "secrets" / "camera-secrets.json"
    monkeypatch.setattr(secret_store.settings, "camera_secrets_file", str(path))
    return path


def test_put_get_delete_roundtrip(store):
    secret_store.put("cred_1", "p@ss:w/rd#1")
    assert secret_store.get("cred_1") == "p@ss:w/rd#1"
    secret_store.delete("cred_1")
    assert secret_store.get("cred_1") is None


def test_put_keeps_other_keys(store):
    secret_store.put("cred_1", "a")
    secret_store.put("cred_2", "b")
    assert (secret_store.get("cred_1"), secret_store.get("cred_2")) == ("a", "b")


def test_file_and_dir_are_owner_only(store):
    secret_store.put("cred_1", "x")
    assert stat.S_IMODE(os.stat(store).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(store.parent).st_mode) == 0o700


def test_missing_file_reads_as_empty(store):
    assert secret_store.get("cred_1") is None


def test_rejects_path_inside_storage_root(tmp_path, monkeypatch):
    monkeypatch.setattr(secret_store.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(secret_store.settings, "camera_secrets_file", str(tmp_path / "s.json"))
    with pytest.raises(SecretStoreError):
        secret_store.put("cred_1", "x")
    assert not (tmp_path / "s.json").exists()


def test_store_ref_resolves_through_stream_endpoint(store):
    secret_store.put("cred_7", "cam-pass")
    assert _secret("store:cred_7") == "cam-pass"
    with pytest.raises(StreamEndpointError, match="unavailable"):
        _secret("store:cred_missing")
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_secret_store.py -q`
Expected: FAIL — `ImportError: cannot import name 'secret_store'`.

- [ ] **Step 3: Implementasi**

`backend/app/core/config.py` — setelah `storage_root: str = "/data/isentinel"`:

```python
    # Password kamera (profil kredensial "store:") — file 0600, WAJIB di luar storage_root
    camera_secrets_file: str = "~/.isentinel/camera-secrets.json"
```

`backend/app/services/secret_store.py`:

```python
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
```

`backend/app/services/stream_endpoint.py` — tambah import `from app.services import secret_store` (di bawah `from app.core.config import settings`) dan ganti awal `_secret`:

```python
def _secret(secret_ref: str) -> str:
    if secret_ref.startswith("store:"):
        try:
            value = secret_store.get(secret_ref[len("store:"):])
        except secret_store.SecretStoreError as exc:
            raise StreamEndpointError("credential reference is unavailable") from exc
        if value is None:
            raise StreamEndpointError("credential reference is unavailable")
        return value
    if not secret_ref.startswith("env:"):
        raise StreamEndpointError("unsupported credential reference")
```

(sisa fungsi `env:` tidak berubah).

`.env.example` — setelah blok `CAMERA_CREDENTIAL_NVR_A`:

```bash
# Password kamera yang diisi dari UI (Kelola kredensial) disimpan di file ini (0600),
# bukan di DB. WAJIB di luar STORAGE_ROOT. Default: ~/.isentinel/camera-secrets.json
# CAMERA_SECRETS_FILE=/home/isentinel/.isentinel/camera-secrets.json
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest tests/test_secret_store.py tests/test_stream_endpoint.py -q`
Expected: semua passed.

- [ ] **Step 5: CHANGELOG + commit**

Di `CHANGELOG.md`, di atas `### Event clip pre-buffer (2026-09-24)`:

```markdown
### Pendaftaran kamera sederhana (2026-09-24 – …)

- **`secret_store`**: password kamera dari UI disimpan di file rahasia server (`CAMERA_SECRETS_FILE`,
  default `~/.isentinel/camera-secrets.json`, 0600, direktori 0700, tulis atomik, ditolak bila di dalam
  `STORAGE_ROOT`); DB hanya referensi `store:cred_<id>`, di-resolve oleh `stream_endpoint._secret`.
  Backend **<angka> passed**.
```

```bash
git add backend/app/services/secret_store.py backend/app/core/config.py backend/app/services/stream_endpoint.py backend/tests/test_secret_store.py .env.example CHANGELOG.md
git commit -m "feat(camera): secret_store — password kamera di file rahasia, DB hanya referensi"
```

---

### Task 2: Profil kredensial menerima `password`

**Files:**
- Modify: `backend/app/schemas/credential_profile.py`
- Modify: `backend/app/api/credential_profiles.py` (`create_profile`, `update_profile`)
- Test: `backend/tests/test_camera_reference_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `secret_store.put`, `secret_store.SecretStoreError` (Task 1).
- Produces:
  - `POST /api/v1/credential-profiles` body `{name, username?, password}` **atau** `{name, username?, secret_ref: "env:NAMA"}` (tepat satu); response `CredentialProfileOut` (tanpa password; `secret_ref` = `store:cred_<id>` untuk password).
  - `PATCH /api/v1/credential-profiles/{id}` menerima `password` opsional (menimpa store, `secret_ref` → `store:…`, memicu sinkron go2rtc + config push yang sudah ada).
  - Error: 422 bila tidak/keduanya diisi; 500 `"failed to store credential"` bila store gagal (profil tidak dibuat).

- [ ] **Step 1: Tulis tes yang gagal**

Tambahkan di akhir `backend/tests/test_camera_reference_api.py`:

```python
from app.models.credential_profile import CredentialProfile
from app.services import secret_store


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "camera_secrets_file", str(tmp_path / "s" / "cams.json"))


def test_profile_password_goes_to_store_not_db(client, db, secrets):
    h = admin_headers(client)
    r = client.post(
        "/api/v1/credential-profiles",
        json={"name": "zkteco", "username": "admin", "password": "Rahasia#1"},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["secret_ref"] == f"store:cred_{body['id']}"
    assert "Rahasia#1" not in r.text
    assert db.get(CredentialProfile, body["id"]).secret_ref == body["secret_ref"]
    assert secret_store.get(f"cred_{body['id']}") == "Rahasia#1"
    assert "Rahasia#1" not in client.get("/api/v1/credential-profiles", headers=h).text


def test_profile_requires_exactly_one_secret(client, secrets):
    h = admin_headers(client)
    both = client.post(
        "/api/v1/credential-profiles",
        json={"name": "a", "secret_ref": "env:CAMERA_CRED", "password": "x"},
        headers=h,
    )
    neither = client.post("/api/v1/credential-profiles", json={"name": "b"}, headers=h)
    assert both.status_code == 422 and neither.status_code == 422


def test_patch_password_updates_store(client, secrets):
    h = admin_headers(client)
    created = client.post(
        "/api/v1/credential-profiles", json={"name": "zk", "password": "old"}, headers=h
    ).json()
    r = client.patch(
        f"/api/v1/credential-profiles/{created['id']}", json={"password": "new"}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["secret_ref"] == created["secret_ref"]
    assert secret_store.get(f"cred_{created['id']}") == "new"


def test_patch_password_moves_env_profile_to_store(client, secrets):
    h = admin_headers(client)
    created = client.post(
        "/api/v1/credential-profiles", json={"name": "legacy", "secret_ref": "env:CAMERA_CRED"}, headers=h
    ).json()
    r = client.patch(
        f"/api/v1/credential-profiles/{created['id']}", json={"password": "typed"}, headers=h
    )
    assert r.json()["secret_ref"] == f"store:cred_{created['id']}"
    assert secret_store.get(f"cred_{created['id']}") == "typed"


def test_store_write_failure_creates_no_profile(client, db, secrets, monkeypatch):
    def boom(key, value):
        raise secret_store.SecretStoreError("disk full")

    monkeypatch.setattr(secret_store, "put", boom)
    r = client.post(
        "/api/v1/credential-profiles", json={"name": "zk", "password": "x"}, headers=admin_headers(client)
    )
    assert r.status_code == 500
    assert db.query(CredentialProfile).count() == 0
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_camera_reference_api.py -q`
Expected: FAIL — POST dengan `password` → 422 (`secret_ref` wajib).

- [ ] **Step 3: Implementasi**

`backend/app/schemas/credential_profile.py` — ganti seluruh isi:

```python
import re

from pydantic import BaseModel, Field, field_validator, model_validator


_SECRET_REF = re.compile(r"^env:[A-Z][A-Z0-9_]*$")


def validate_secret_ref(value: str | None) -> str | None:
    """Input klien hanya boleh env:NAMA; referensi store: dibuat server."""
    if value is None:
        return None
    value = value.strip()
    if not _SECRET_REF.fullmatch(value):
        raise ValueError("secret_ref must use env:NAME")
    return value


class CredentialProfileOut(BaseModel):
    id: int
    name: str
    username: str
    secret_ref: str  # referensi (env:/store:), bukan rahasia
    enabled: bool

    model_config = {"from_attributes": True}


class CredentialProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    username: str = Field(default="", max_length=128)
    secret_ref: str | None = Field(default=None, min_length=6, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=256)  # write-only
    enabled: bool = True

    _validate_secret_ref = field_validator("secret_ref")(validate_secret_ref)

    @model_validator(mode="after")
    def _exactly_one_secret(self):
        if (self.secret_ref is None) == (self.password is None):
            raise ValueError("provide exactly one of secret_ref or password")
        return self


class CredentialProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    username: str | None = Field(default=None, max_length=128)
    secret_ref: str | None = Field(default=None, min_length=6, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=256)  # write-only
    enabled: bool | None = None

    _validate_secret_ref = field_validator("secret_ref")(validate_secret_ref)

    @model_validator(mode="after")
    def _not_both_secrets(self):
        if self.secret_ref is not None and self.password is not None:
            raise ValueError("provide secret_ref or password, not both")
        return self
```

`backend/app/api/credential_profiles.py`:
- import: tambah `from app.services import secret_store`.
- helper baru (di bawah `_in_use`):

```python
def _store_password(key: str, password: str) -> None:
    try:
        secret_store.put(key, password)
    except secret_store.SecretStoreError as exc:
        logger.error("credential store write failed: %s", exc)
        raise HTTPException(500, "failed to store credential") from exc
```

- `create_profile`, ganti blok `profile = CredentialProfile(...)` sampai `db.refresh(profile)` dengan:

```python
    profile = CredentialProfile(
        **body.model_dump(exclude={"name", "username", "secret_ref", "password"}),
        name=name,
        username=body.username.strip(),
        secret_ref=body.secret_ref or "store:pending",
    )
    db.add(profile)
    db.flush()  # butuh id untuk key store
    if body.password is not None:
        key = f"cred_{profile.id}"
        try:
            _store_password(key, body.password)
        except HTTPException:
            db.rollback()
            raise
        profile.secret_ref = f"store:{key}"
    db.commit()
    db.refresh(profile)
```

- `update_profile`, tepat setelah `data = body.model_dump(exclude_unset=True)`:

```python
    password = data.pop("password", None)
    if password is not None:
        ref = profile.secret_ref or ""
        key = ref[len("store:"):] if ref.startswith("store:") else f"cred_{profile.id}"
        _store_password(key, password)
        data["secret_ref"] = f"store:{key}"
```

(`runtime_changed` yang sudah ada melihat `secret_ref` di `data` → sinkron go2rtc + config push kamera terkait jalan.)

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest tests/test_camera_reference_api.py tests/test_cameras_api.py -q`
Expected: semua passed (tes lama `secret_ref: env:…` tetap lulus).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Profil kredensial menerima `password`** (write-only): disimpan ke `secret_store`, `secret_ref` =
  `store:cred_<id>`; tepat satu dari `password`/`secret_ref: env:` (422 bila tidak); PATCH `password`
  menimpa store (profil `env:` pindah ke `store:`) dan memicu sinkron go2rtc + config push; gagal tulis store
  → 500, profil tidak dibuat. Password tidak pernah muncul di response. Backend **<angka> passed**.
```

```bash
git add backend/app/schemas/credential_profile.py backend/app/api/credential_profiles.py backend/tests/test_camera_reference_api.py CHANGELOG.md
git commit -m "feat(camera): profil kredensial menerima password write-only ke secret_store"
```

---

### Task 3: Kredensial override untuk kamera direct-host

**Files:**
- Modify: `backend/app/services/stream_endpoint.py` (`resolve_stream`, cabang `source is None`)
- Modify: `backend/app/api/cameras.py` (`_prepare_camera_data`: hapus penolakan 422)
- Modify: `backend/app/api/probe.py` (`probe`: hapus penolakan 422)
- Test: `backend/tests/test_stream_endpoint.py`, `backend/tests/test_cameras_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `store:` resolve (Task 1), profil dengan password (Task 2).
- Produces: `resolve_stream(credential_override=profile, legacy_host=...)` memakai kredensial profil; `POST/PATCH /api/v1/cameras` dan `POST /api/v1/cameras/probe` menerima `credential_override_id` tanpa `source_id`.

- [ ] **Step 1: Tulis tes yang gagal**

Tambahkan di akhir `backend/tests/test_stream_endpoint.py`:

```python
def test_direct_host_camera_uses_override_profile(db, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "cam_username", "nvr")
    monkeypatch.setattr(settings, "cam_password", "nvr-pass")
    monkeypatch.setenv("CAMERA_CRED_ZK", "p@ss:w/rd#1")
    profile = CredentialProfile(name="zk", username="admin", secret_ref="env:CAMERA_CRED_ZK")
    zk = Camera(name="ZK", host="192.168.2.179:8554", credential_override=profile, rtsp_main="/stream")
    nvr = Camera(name="NVR-1", host="192.168.2.184", rtsp_main="/Streaming/Channels/101")
    db.add_all([zk, nvr])
    db.commit()

    zk_stream = resolve_camera_stream(zk)
    assert build_rtsp_url(zk_stream, zk_stream.main_path) == (
        "rtsp://admin:p%40ss%3Aw%2Frd%231@192.168.2.179:8554/stream"
    )
    nvr_stream = resolve_camera_stream(nvr)
    assert (nvr_stream.username, nvr_stream.password) == ("nvr", "nvr-pass")
```

Tambahkan di akhir `backend/tests/test_cameras_api.py` (pakai fixture `client` dan helper admin header yang sudah ada di file ini — cek namanya di kepala file, mis. `_admin_headers`):

```python
def test_direct_host_camera_accepts_credential_override(client):
    from unittest.mock import patch  # pola file ini: import lokal

    h = _admin_headers(client)
    profile = client.post(
        "/api/v1/credential-profiles",
        json={"name": "zk", "username": "admin", "secret_ref": "env:CAMERA_CRED_ZK"},
        headers=h,
    ).json()
    with patch("app.api.cameras.sync_camera"), patch("app.api.cameras._config_push"):
        r = client.post(
            "/api/v1/cameras",
            json={"name": "ZK", "host": "192.168.2.179:8554", "main_path": "/stream",
                  "credential_override_id": profile["id"]},
            headers=h,
        )
    assert r.status_code == 200
    assert r.json()["credential_override_id"] == profile["id"]
    assert r.json()["credential_override"]["name"] == "zk"


def test_probe_direct_host_with_credential_override(client, monkeypatch):
    from unittest.mock import patch  # pola file ini: import lokal

    monkeypatch.setenv("CAMERA_CRED_ZK", "zk-pass")
    h = _admin_headers(client)
    profile = client.post(
        "/api/v1/credential-profiles",
        json={"name": "zk", "username": "admin", "secret_ref": "env:CAMERA_CRED_ZK"},
        headers=h,
    ).json()
    seen = {}

    def fake_probe(stream, snapshot=False):
        seen["stream"] = stream
        return {"main": None, "sub": None, "main_path": stream.main_path, "sub_path": stream.sub_path}

    with patch("app.api.probe.probe_exact", side_effect=fake_probe):
        r = client.post(
            "/api/v1/cameras/probe",
            json={"host": "192.168.2.179:8554", "main_path": "/stream",
                  "credential_override_id": profile["id"]},
            headers=h,
        )
    assert r.status_code == 200
    assert (seen["stream"].username, seen["stream"].password) == ("admin", "zk-pass")


def test_probe_missing_store_secret_is_422(client, db, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.credential_profile import CredentialProfile

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "camera_secrets_file", str(tmp_path / "s" / "cams.json"))
    lost = CredentialProfile(name="lost", username="admin", secret_ref="store:cred_999")
    db.add(lost)
    db.commit()
    r = client.post(
        "/api/v1/cameras/probe",
        json={"host": "10.0.0.9", "main_path": "/main", "credential_override_id": lost.id},
        headers=_admin_headers(client),
    )
    assert r.status_code == 422
    assert "unavailable" in r.json()["detail"]
```

(`fake_probe` menerima `snapshot` karena Task 4 menambah argumen itu; di Task 3 probe dipanggil tanpa `snapshot`, jadi default dipakai.)

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_stream_endpoint.py tests/test_cameras_api.py -q`
Expected: FAIL — override diabaikan (kredensial `nvr`), POST/probe → 422 "credential override requires a stream source".

- [ ] **Step 3: Implementasi**

`backend/app/services/stream_endpoint.py`, di `resolve_stream` ganti cabang `if source is None:`:

```python
    if source is None:
        if not legacy_host:
            raise StreamEndpointError("camera host is empty")
        host, port = split_host_port(legacy_host)
        if credential_override is not None:
            username, password = _profile_credentials(credential_override)
        else:
            username = settings.cam_username or None
            password = settings.cam_password or None
```

`backend/app/api/cameras.py` (`_prepare_camera_data`) — hapus dua baris:

```python
    if source is None and credential is not None:
        raise HTTPException(422, "credential override requires a stream source")
```

`backend/app/api/probe.py` (`probe`) — hapus dua baris yang sama.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`
Expected: semua passed. Bila ada tes lama yang mengharapkan 422 "credential override requires a stream source", ubah menjadi ekspektasi sukses dan sebutkan di ringkasan (kombinasi ini sekarang fitur).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Kredensial per kamera direct-host**: `resolve_stream` memakai `credential_override` walau kamera tanpa
  stream source (13 kamera server semuanya direct-host); API kamera + probe tidak lagi menolak kombinasi itu.
  Password khusus ter-encode di URL RTSP; referensi `store:` yang hilang → probe 422. Backend **<angka> passed**.
```

```bash
git add backend/app/services/stream_endpoint.py backend/app/api/cameras.py backend/app/api/probe.py backend/tests/test_stream_endpoint.py backend/tests/test_cameras_api.py CHANGELOG.md
git commit -m "feat(camera): kredensial override berlaku untuk kamera direct-host"
```

---

### Task 4: Probe mengembalikan thumbnail

**Files:**
- Modify: `backend/app/services/probe.py` (fungsi baru `snapshot_jpeg_b64`, argumen `snapshot` di `probe_exact`)
- Modify: `backend/app/api/probe.py` (`ProbeIn.snapshot`, teruskan ke `probe_exact`)
- Test: `backend/tests/test_probe.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces:
  - `snapshot_jpeg_b64(url: str, timeout: float = 6.0) -> str | None`
  - `probe_exact(stream: EffectiveStream, snapshot: bool = False) -> dict` — bila `snapshot`, dict memuat `snapshot_jpeg_b64: str | None` (frame dari SUB, atau MAIN bila SUB kosong; `None` bila stream tak terbaca/ffmpeg gagal).
  - `POST /api/v1/cameras/probe` body `snapshot: bool = False`.

- [ ] **Step 1: Tulis tes yang gagal**

Tambahkan di `backend/tests/test_probe.py`:

```python
import base64
import subprocess

from app.services.probe import probe_exact, snapshot_jpeg_b64
from app.services.stream_endpoint import EffectiveStream

OK = {"res": "640x480", "fps": 25.0, "codec": "h264"}


def test_snapshot_returns_base64_jpeg():
    with patch("app.services.probe.subprocess.run") as m:
        m.return_value.returncode = 0
        m.return_value.stdout = b"\xff\xd8jpeg"
        assert snapshot_jpeg_b64("rtsp://x") == base64.b64encode(b"\xff\xd8jpeg").decode()
    cmd = m.call_args[0][0]
    assert cmd[0] == "ffmpeg" and cmd[cmd.index("-frames:v") + 1] == "1"


def test_snapshot_failure_returns_none():
    with patch("app.services.probe.subprocess.run") as m:
        m.return_value.returncode = 1
        m.return_value.stdout = b""
        assert snapshot_jpeg_b64("rtsp://x") is None
    with patch("app.services.probe.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 6)):
        assert snapshot_jpeg_b64("rtsp://x") is None


def test_probe_exact_snapshot_uses_sub_then_main():
    stream = EffectiveStream(host="10.0.0.5", port=554, username="u", password="p",
                             main_path="/main", sub_path="/sub")
    with patch("app.services.probe.probe_url", return_value=OK), \
         patch("app.services.probe.snapshot_jpeg_b64", return_value="QUJD") as snap:
        r = probe_exact(stream, snapshot=True)
    assert r["snapshot_jpeg_b64"] == "QUJD"
    assert snap.call_args[0][0] == "rtsp://u:p@10.0.0.5/sub"

    main_only = EffectiveStream(host="10.0.0.5", port=554, username=None, password=None,
                                main_path="/main", sub_path=None)
    with patch("app.services.probe.probe_url", return_value=OK), \
         patch("app.services.probe.snapshot_jpeg_b64", return_value="QUJD") as snap:
        probe_exact(main_only, snapshot=True)
    assert snap.call_args[0][0] == "rtsp://10.0.0.5/main"


def test_probe_exact_without_snapshot_or_unreadable_stream():
    stream = EffectiveStream(host="10.0.0.5", port=554, username=None, password=None,
                             main_path="/main", sub_path="/sub")
    with patch("app.services.probe.probe_url", return_value=OK):
        assert "snapshot_jpeg_b64" not in probe_exact(stream)
    with patch("app.services.probe.probe_url", return_value=None), \
         patch("app.services.probe.snapshot_jpeg_b64") as snap:
        assert probe_exact(stream, snapshot=True)["snapshot_jpeg_b64"] is None
    snap.assert_not_called()
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_probe.py -q`
Expected: FAIL — `ImportError: cannot import name 'snapshot_jpeg_b64'`.

- [ ] **Step 3: Implementasi**

`backend/app/services/probe.py` — tambah `import base64` di kepala, lalu fungsi di bawah `probe_url`:

```python
def snapshot_jpeg_b64(url, timeout=6.0):
    """Satu frame JPEG (lebar 480) dari RTSP sebagai base64; None bila gagal. Tidak ditulis ke disk."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-rtsp_transport", "tcp", "-i", url,
             "-frames:v", "1", "-vf", "scale=480:-1", "-f", "image2", "-c:v", "mjpeg", "pipe:1"],
            capture_output=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    return base64.b64encode(r.stdout).decode("ascii")
```

Ganti `probe_exact`:

```python
def probe_exact(stream: EffectiveStream, snapshot: bool = False):
    """Probe only the selected paths; never infer a vendor path."""
    def probe_path(path):
        url = build_rtsp_url(stream, path)
        return probe_url(url) if url else None

    result = {
        "main": probe_path(stream.main_path),
        "sub": probe_path(stream.sub_path),
        "main_path": stream.main_path,
        "sub_path": stream.sub_path,
    }
    if snapshot:
        # thumbnail dari stream deteksi (SUB), atau MAIN bila SUB kosong
        path, ok = (stream.sub_path, result["sub"]) if stream.sub_path else (stream.main_path, result["main"])
        url = build_rtsp_url(stream, path) if ok else None
        result["snapshot_jpeg_b64"] = snapshot_jpeg_b64(url) if url else None
    return result
```

`backend/app/api/probe.py`: di `ProbeIn` tambah `snapshot: bool = False`; ganti `result = probe_exact(stream)` menjadi `result = probe_exact(stream, snapshot=body.snapshot)`.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest tests/test_probe.py tests/test_cameras_api.py -q`
Expected: semua passed.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Probe thumbnail**: `POST /cameras/probe` dengan `snapshot: true` mengembalikan `snapshot_jpeg_b64`
  (1 frame SUB, atau MAIN bila SUB kosong, lebar 480, ffmpeg timeout 6 s, tidak ditulis ke disk; gagal →
  `null`). Backend **<angka> passed**.
```

```bash
git add backend/app/services/probe.py backend/app/api/probe.py backend/tests/test_probe.py CHANGELOG.md
git commit -m "feat(camera): probe mengembalikan thumbnail substream (snapshot_jpeg_b64)"
```

---

### Task 5: Frontend — API client + form "Kredensial baru"

**Files:**
- Modify: `frontend/src/api/credentialProfiles.ts`
- Modify: `frontend/src/api/cameras.ts` (`ProbePayload`, `ProbeResult`)
- Create: `frontend/src/features/config/NewCredentialForm.tsx`
- Modify: `frontend/src/app/i18n.tsx` (key `cameras.cred.*`, id + en)
- Test: `frontend/src/__tests__/new-credential-form.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: API Task 2 (`password`), Task 4 (`snapshot`).
- Produces:
  - `CredentialProfilePayload = { name: string; username?: string; secret_ref?: string; password?: string; enabled?: boolean }`
  - `ProbePayload.snapshot?: boolean`; `ProbeResult.snapshot_jpeg_b64?: string | null`
  - `NewCredentialForm({ onCancel: () => void; onCreated: (p: CredentialProfile) => void })` — fieldset inline (bukan modal)
  - i18n: `cameras.cred.title`, `cameras.cred.name`, `cameras.cred.username`, `cameras.cred.password`, `cameras.cred.save`, `cameras.cred.saveError`, `cameras.cred.duplicate`

- [ ] **Step 1: Tulis tes yang gagal**

`frontend/src/__tests__/new-credential-form.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import NewCredentialForm from '../features/config/NewCredentialForm'

function renderForm(onCreated = vi.fn(), onCancel = vi.fn()) {
  render(
    <I18nProvider>
      <NewCredentialForm onCancel={onCancel} onCreated={onCreated} />
    </I18nProvider>,
  )
  return { onCreated, onCancel }
}

function stub(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => ({ ok: status < 400, status, json: () => Promise.resolve(body) }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

test('saves name, username and password, then hands the profile back', async () => {
  const created = { id: 5, name: 'ZKteco', username: 'admin', secret_ref: 'store:cred_5', enabled: true }
  const fetchMock = stub(200, created)
  const { onCreated } = renderForm()

  const save = screen.getByRole('button', { name: 'Simpan kredensial' })
  expect(save).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Nama kredensial'), 'ZKteco')
  await userEvent.type(screen.getByLabelText('Username'), 'admin')
  expect(save).toBeDisabled() // password wajib
  await userEvent.type(screen.getByLabelText('Password', { selector: 'input' }), 'Rahasia#1')
  await userEvent.click(save)

  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created))
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
  expect(url).toMatch(/\/credential-profiles$/)
  expect(JSON.parse(String(init.body))).toEqual({ name: 'ZKteco', username: 'admin', password: 'Rahasia#1' })
})

test('duplicate name shows a specific message', async () => {
  stub(409, { detail: 'credential profile name already exists' })
  const { onCreated } = renderForm()
  await userEvent.type(screen.getByLabelText('Nama kredensial'), 'ZKteco')
  await userEvent.type(screen.getByLabelText('Password', { selector: 'input' }), 'x')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan kredensial' }))
  expect(await screen.findByText('Nama kredensial sudah dipakai')).toBeInTheDocument()
  expect(onCreated).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/new-credential-modal.test.tsx`
Expected: FAIL — modul `NewCredentialForm` tidak ada.

- [ ] **Step 3: Implementasi**

`frontend/src/api/credentialProfiles.ts` — ganti tipe payload:

```ts
export type CredentialProfilePayload = {
  name: string
  username?: string
  secret_ref?: string // env:NAMA (lama)
  password?: string   // write-only → file rahasia server
  enabled?: boolean
}
```

`frontend/src/api/cameras.ts`: di `ProbePayload` tambah `snapshot?: boolean`; di `ProbeResult` tambah `snapshot_jpeg_b64?: string | null`.

`frontend/src/features/config/NewCredentialForm.tsx`:

```tsx
import { useState } from 'react'
import { Button, InlineNotification, PasswordInput, TextInput } from '@carbon/react'
import { useT } from '../../app/i18n'
import { createCredentialProfile, type CredentialProfile } from '../../api/credentialProfiles'

type Props = {
  onCancel: () => void
  onCreated: (profile: CredentialProfile) => void
}

// Form inline (bukan modal: modal bertumpuk di atas wizard berebut fokus). Supervisor mengisi
// username/password kamera sekali, lalu memilih namanya di form kamera.
export default function NewCredentialForm({ onCancel, onCreated }: Props) {
  const { t } = useT()
  const [name, setName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const canSave = name.trim() !== '' && password !== '' && !busy

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      onCreated(await createCredentialProfile({ name: name.trim(), username: username.trim(), password }))
    } catch (e) {
      setError(t(e instanceof Error && e.message.endsWith(': 409') ? 'cameras.cred.duplicate' : 'cameras.cred.saveError'))
      setBusy(false)
    }
  }

  return (
    <fieldset data-testid="new-credential-form"
      style={{ border: '1px solid var(--cds-border-subtle)', padding: 12, marginTop: 8, minWidth: 0 }}>
      <legend style={{ fontSize: 12, padding: '0 4px' }}>{t('cameras.cred.title')}</legend>
      <TextInput id="cred-name" labelText={t('cameras.cred.name')} placeholder="ZKteco" value={name}
        onChange={(e) => setName(e.target.value)} />
      <TextInput id="cred-username" labelText={t('cameras.cred.username')} value={username} autoComplete="off"
        onChange={(e) => setUsername(e.target.value)} style={{ marginTop: 12 }} />
      <PasswordInput id="cred-password" labelText={t('cameras.cred.password')} value={password} autoComplete="new-password"
        onChange={(e) => setPassword(e.target.value)} style={{ marginTop: 12 }} />
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <Button size="sm" disabled={!canSave} onClick={() => void save()}>{t('cameras.cred.save')}</Button>
        <Button size="sm" kind="ghost" onClick={onCancel}>{t('common.cancel')}</Button>
      </div>
      {error && <InlineNotification kind="error" lowContrast hideCloseButton title={error} style={{ marginTop: 12 }} />}
    </fieldset>
  )
}
```

`frontend/src/app/i18n.tsx` — tambah di blok `id` (dekat key `cameras.wizard.*`):

```ts
    'cameras.cred.title': 'Kredensial baru',
    'cameras.cred.name': 'Nama kredensial',
    'cameras.cred.username': 'Username',
    'cameras.cred.password': 'Password',
    'cameras.cred.save': 'Simpan kredensial',
    'cameras.cred.saveError': 'Gagal menyimpan kredensial',
    'cameras.cred.duplicate': 'Nama kredensial sudah dipakai',
```

dan di blok `en`:

```ts
    'cameras.cred.title': 'New credentials',
    'cameras.cred.name': 'Credential name',
    'cameras.cred.username': 'Username',
    'cameras.cred.password': 'Password',
    'cameras.cred.save': 'Save credentials',
    'cameras.cred.saveError': 'Failed to save credentials',
    'cameras.cred.duplicate': 'Credential name already used',
```

(Tombol batal memakai `common.cancel` yang sudah ada. Carbon `PasswordInput` merender tombol "Show password", karena itu tes memakai `getByLabelText('Password', { selector: 'input' })`.)

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd frontend && npx vitest run src/__tests__/new-credential-form.test.tsx && npx tsc -b`
Expected: 2 passed; tsc tanpa error.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Form "Kredensial baru"** (`NewCredentialForm`, inline): Nama, Username, Password → `POST /credential-profiles`
  (password write-only); nama duplikat → pesan khusus. API client: `password` di payload profil, `snapshot`
  di probe. Frontend **<angka> passed**.
```

```bash
git add frontend/src/api/credentialProfiles.ts frontend/src/api/cameras.ts frontend/src/features/config/NewCredentialForm.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/new-credential-form.test.tsx CHANGELOG.md
git commit -m "feat(camera): form kredensial baru + API client password/snapshot"
```

---

### Task 6: `CameraWizard` sederhana

**Files:**
- Modify: `frontend/src/features/config/CameraWizard.tsx` (tulis ulang komponen; helper `safePath`, `streamText`, `channelLabel`, `savedProbe` dipertahankan, `safeHost` dihapus)
- Modify: `frontend/src/features/config/CamerasPage.tsx` (hanya mount wizard: prop baru)
- Modify: `frontend/src/app/i18n.tsx` (key `cameras.wizard.*`, id + en)
- Test: `frontend/src/__tests__/cameras.test.tsx`, `frontend/src/__tests__/camera-sources.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `NewCredentialForm` + `CredentialProfile` (Task 5), probe `snapshot` (Task 4), `credential_override_id` direct-host (Task 3).
- Produces: `CameraWizard` props `{ camera?: Camera; profiles: CredentialProfile[]; locations: string[]; onProfilesChanged: () => void; onClose: () => void; onSaved: () => void }`.

- [ ] **Step 1: Perbarui dan tambah tes (gagal)**

Di `frontend/src/__tests__/cameras.test.tsx`:
- Semua `getByLabelText('IP / Host')` / `findByLabelText('IP / Host')` → `'IP kamera'`.
- Semua tombol `'Probe stream'` → `'Tes koneksi'`.
- Tambah respons profil **dan** stream-sources di setiap `stubFetch` yang membuka wizard: `if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }` dan `if (call.url.endsWith('/stream-sources')) return { status: 200, body: [] }` — `refreshReferences` di `CamerasPage` masih memuat keduanya lewat `Promise.all` sampai Task 7, dan satu 404 membuat daftar profil kosong. Tes baru di bawah juga harus memuat stub `/stream-sources` ini (letakkan di baris sebelum `/credential-profiles`). Konstanta di kepala file:

```tsx
const PROFILES = [
  { id: 31, name: 'zkteco', username: 'admin', secret_ref: 'store:cred_31', enabled: true },
  { id: 32, name: 'lama', username: 'x', secret_ref: 'store:cred_32', enabled: false },
]
```

- Tes `wizard: auto-detect scan enables Simpan with selected channel paths`: ganti `'IP / Host'` → `'IP kamera'`; sebelum klik `Deteksi otomatis`, buka Lanjutan dengan `await userEvent.click(within(screen.getByTestId('wiz-advanced')).getByText('Lanjutan'))` (import `within` dari `@testing-library/react`; `within` perlu karena Task 7 menambah tombol halaman bernama "Lanjutan"); tambahkan `expect(payload.credential_override_id).toBeNull()` di blok payload.
- Ganti tes `wizard: scan without result offers manual paths, Simpan stays disabled` dengan:

```tsx
test('wizard: untested camera needs a second Simpan click', async () => {
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
    if (call.url.endsWith('/cameras') && call.init?.method === 'POST') return { status: 200, body: CAMS[0] }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: [] }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click(await screen.findByText('+ Tambah kamera'))
  await userEvent.type(await screen.findByLabelText('Nama kamera'), 'CAM-07')
  await userEvent.type(screen.getByLabelText('IP kamera'), '10.0.0.99')
  const save = screen.getByRole('button', { name: 'Simpan' })
  expect(save).toBeDisabled() // path mainstream wajib
  await userEvent.type(screen.getByLabelText('Path mainstream'), '/Streaming/Channels/101')
  expect(save).toBeEnabled()

  await userEvent.click(save)
  expect(await screen.findByText('Koneksi belum dites. Klik Simpan sekali lagi untuk tetap menyimpan.')).toBeInTheDocument()
  expect(calls.some((c) => c.init?.method === 'POST' && c.url.endsWith('/cameras'))).toBe(false)

  await userEvent.click(save)
  await waitFor(() => expect(calls.some((c) => c.init?.method === 'POST' && c.url.endsWith('/cameras'))).toBe(true))
})
```

- Tes `edit: connection change needs a fresh probe before save`: ganti

```tsx
  const saveBtn = screen.getByRole('button', { name: 'Simpan' })
  expect(saveBtn).toBeDisabled()
```

dengan

```tsx
  const saveBtn = screen.getByRole('button', { name: 'Simpan' })
  await userEvent.click(saveBtn)
  expect(screen.getByText('Koneksi belum dites. Klik Simpan sekali lagi untuk tetap menyimpan.')).toBeInTheDocument()
  expect(calls.some((c) => c.init?.method === 'PATCH')).toBe(false)
```

  lalu ubah ekspektasi body probe menjadi:

```tsx
    expect(JSON.parse(String(probeCall!.init!.body))).toEqual({
      host: '192.168.1.109',
      main_path: '/Streaming/Channels/101',
      sub_path: '/Streaming/Channels/102',
      snapshot: true,
    })
```

  dan tambahkan `expect(payload.credential_override_id).toBeNull()`.

Tambahkan tes baru di `cameras.test.tsx`:

```tsx
test('wizard: main form is short; Node and NVR scan live under Lanjutan', async () => {
  stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: CAMS }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click(await screen.findByText('+ Tambah kamera'))
  await screen.findByLabelText('Nama kamera')
  for (const label of ['Lokasi', 'IP kamera', 'Path mainstream', 'Path substream', 'Kredensial']) {
    expect(screen.getByLabelText(label)).toBeInTheDocument()
  }
  expect(screen.getByTestId('wiz-advanced')).not.toHaveAttribute('open')
  expect(screen.queryByLabelText('Node')).not.toBeInTheDocument() // hanya 1 node
  const options = [...(screen.getByLabelText('Kredensial') as HTMLSelectElement).options].map((o) => o.text)
  expect(options).toEqual(['Default (NVR)', 'zkteco', '+ Kredensial baru…']) // profil nonaktif disembunyikan
})

test('wizard: new credential from the inline form is selected and sent', async () => {
  const created = { id: 33, name: 'Gudang', username: 'admin', secret_ref: 'store:cred_33', enabled: true }
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/credential-profiles') && call.init?.method === 'POST') return { status: 200, body: created }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
    if (call.url.endsWith('/cameras/probe')) {
      return { status: 200, body: { main: { res: '1920x1080', fps: 25, codec: 'h264' }, sub: null,
        main_path: '/stream', sub_path: null, snapshot_jpeg_b64: 'QUJD' } }
    }
    if (call.url.endsWith('/cameras') && call.init?.method === 'POST') return { status: 200, body: CAMS[0] }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: [] }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click(await screen.findByText('+ Tambah kamera'))
  await userEvent.type(await screen.findByLabelText('Nama kamera'), 'Gudang')
  await userEvent.type(screen.getByLabelText('IP kamera'), '192.168.2.179:8554')
  await userEvent.type(screen.getByLabelText('Path mainstream'), '/stream')
  await userEvent.selectOptions(screen.getByLabelText('Kredensial'), 'new')
  await userEvent.type(await screen.findByLabelText('Nama kredensial'), 'Gudang')
  await userEvent.type(screen.getByLabelText('Password', { selector: 'input' }), 'Rahasia#1')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan kredensial' }))
  await waitFor(() => expect((screen.getByLabelText('Kredensial') as HTMLSelectElement).value).toBe('33'))

  await userEvent.click(screen.getByRole('button', { name: 'Tes koneksi' }))
  expect(await screen.findByTestId('probe-thumb')).toHaveAttribute('src', 'data:image/jpeg;base64,QUJD')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
  await waitFor(() => {
    const probe = calls.find((c) => c.url.endsWith('/cameras/probe'))
    expect(JSON.parse(String(probe!.init!.body))).toMatchObject({ credential_override_id: 33, snapshot: true })
    const create = calls.find((c) => c.url.endsWith('/cameras') && c.init?.method === 'POST')
    const saved = JSON.parse(String(create!.init!.body))
    expect(saved.host).toBe('192.168.2.179:8554')
    expect(saved.credential_override_id).toBe(33)
  })
})

test('wizard: pasted RTSP URL keeps only the path and warns when sub equals main', async () => {
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
    if (call.url.endsWith('/cameras/probe')) return { status: 200, body: { main: null, sub: null, main_path: null, sub_path: null } }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: [] }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click(await screen.findByText('+ Tambah kamera'))
  await userEvent.type(await screen.findByLabelText('IP kamera'), '10.0.0.5')
  await userEvent.type(screen.getByLabelText('Path mainstream'), 'rtsp://admin:rahasia@10.0.0.5/Streaming/Channels/101')
  await userEvent.type(screen.getByLabelText('Path substream'), '/Streaming/Channels/101')
  expect(screen.getByText('Substream sama dengan mainstream — AI akan memproses resolusi penuh.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Tes koneksi' }))
  await waitFor(() => {
    const probe = calls.find((c) => c.url.endsWith('/cameras/probe'))
    const body = String(probe!.init!.body)
    expect(JSON.parse(body).main_path).toBe('/Streaming/Channels/101')
    expect(body).not.toContain('rahasia')
  })
})

test('edit: switching credential sends credential_override_id; disabled profile stays selected', async () => {
  const withDisabled = [{ ...CAMS[0], credential_override_id: 32, credential_override: { id: 32, name: 'lama', username: 'x', enabled: false } }]
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
    if (call.url.endsWith('/cameras/1') && call.init?.method === 'PATCH') return { status: 200, body: CAMS[0] }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: withDisabled }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click((await screen.findAllByRole('button', { name: 'Ubah' }))[0])
  const select = (await screen.findByLabelText('Kredensial')) as HTMLSelectElement
  expect(select.value).toBe('32')

  await userEvent.selectOptions(select, '31')
  const save = screen.getByRole('button', { name: 'Simpan' })
  await userEvent.click(save) // belum dites → peringatan
  await userEvent.click(save)
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/cameras/1') && c.init?.method === 'PATCH')
    expect(JSON.parse(String(patch!.init!.body)).credential_override_id).toBe(31)
  })
})
```

Di `frontend/src/__tests__/camera-sources.test.tsx`:
- Hapus tes `sources panel collapsed by default; expand shows source and profile forms` (panel dihapus di Task 7; bila Task 7 belum jalan, tes ini tetap dihapus di Task 7 — biarkan di Task 6).
- Ganti tes `wizard shows no password, source, group, or credential fields` dengan:

```tsx
test('wizard shows a credential select but no password, source, or group fields', async () => {
  stubFetch((call) => baseResponse(call) ?? { status: 404 })
  renderPage()
  await userEvent.click(await screen.findByText('+ Tambah kamera'))
  await screen.findByLabelText('Nama kamera')
  expect(screen.getByLabelText('Kredensial')).toBeInTheDocument()
  expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Sumber stream')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Grup lokasi')).not.toBeInTheDocument()
})
```

- Tes `creating a direct-host camera with manual paths sends host and paths`: hapus langkah scan + `Isi path manual`; label `'IP / Host'` → `'IP kamera'`, `'Path MAIN (utama)'` → `'Path mainstream'`, `'Path SUB (deteksi)'` → `'Path substream'`, `'Probe stream'` → `'Tes koneksi'`; ekspektasi body probe menjadi `{ host: '10.0.0.5', main_path: '/vendor/high?profile=recording', sub_path: '/vendor/low?profile=ai', snapshot: true }`.
- Tes `editing one exact path retains the other path`: label `'Path MAIN (utama)'` → `'Path mainstream'`, tombol `'Probe stream'` → `'Tes koneksi'`.

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/cameras.test.tsx src/__tests__/camera-sources.test.tsx`
Expected: FAIL — label `IP kamera`/`Kredensial` tidak ada.

- [ ] **Step 3: Implementasi**

`frontend/src/features/config/CameraWizard.tsx` — ganti isi file (helper `safePath`, `streamText`, `channelLabel`, `savedProbe` tetap sama seperti sekarang; `safeHost` dihapus):

```tsx
import { useEffect, useRef, useState } from 'react'
import {
  ComposedModal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Button,
  TextInput,
  Select,
  SelectItem,
  InlineLoading,
  InlineNotification,
} from '@carbon/react'
import { useT } from '../../app/i18n'
import {
  createCamera,
  updateCamera,
  listNodes,
  probeCamera,
  scanCamera,
  type Camera,
  type CameraNode,
  type ProbeResult,
  type ScanChannel,
} from '../../api/cameras'
import type { CredentialProfile } from '../../api/credentialProfiles'
import NewCredentialForm from './NewCredentialForm'

type Props = {
  camera?: Camera
  profiles: CredentialProfile[]
  locations: string[]
  onProfilesChanged: () => void
  onClose: () => void
  onSaved: () => void
}

const NEW_CREDENTIAL = 'new'

// ... safePath, streamText, channelLabel, savedProbe: salin apa adanya dari versi lama ...

export default function CameraWizard({ camera, profiles, locations, onProfilesChanged, onClose, onSaved }: Props) {
  const { t } = useT()
  const isEdit = camera != null
  const [nodes, setNodes] = useState<CameraNode[]>([])
  const [name, setName] = useState(camera?.name ?? '')
  const [location, setLocation] = useState(camera?.location ?? '')
  const [host, setHost] = useState(camera?.host ?? '')
  const [nodeId, setNodeId] = useState<number | ''>(camera?.node_id ?? '')
  const [mainPath, setMainPath] = useState(camera?.main_path ?? safePath(camera?.rtsp_main) ?? '')
  const [subPath, setSubPath] = useState(camera?.sub_path ?? safePath(camera?.rtsp_sub) ?? '')
  const [credentialId, setCredentialId] = useState<number | null>(camera?.credential_override_id ?? null)
  const [created, setCreated] = useState<CredentialProfile | null>(null)
  const [newCredential, setNewCredential] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scans, setScans] = useState<ScanChannel[]>([])
  const [scanSelected, setScanSelected] = useState<ScanChannel | null>(null)
  const [scanEmpty, setScanEmpty] = useState(false)
  const [connectionTouched, setConnectionTouched] = useState(false)
  const [probing, setProbing] = useState(false)
  const [probe, setProbe] = useState<ProbeResult | null>(() => savedProbe(camera))
  const [probeFailed, setProbeFailed] = useState(false)
  const [unverifiedAck, setUnverifiedAck] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const probeSeq = useRef(0)

  useEffect(() => {
    listNodes()
      .then((ns) => {
        setNodes(ns)
        if (!isEdit && ns.length > 0) setNodeId(ns[0].id)
      })
      .catch(() => {})
  }, [isEdit])

  const found = (probe?.main ? 1 : 0) + (probe?.sub ? 1 : 0)
  const needsProbe = !isEdit || connectionTouched
  const verified = !needsProbe || found >= 1
  const endpointHost = host.trim()
  const canSave = name.trim() !== '' && endpointHost !== '' && mainPath.trim() !== '' && !saving
  const subSameAsMain = safePath(subPath) != null && safePath(subPath) === safePath(mainPath)
  // profil nonaktif hanya tampil bila masih terpasang di kamera ini
  const profileOptions = [
    ...profiles.filter((p) => p.enabled || p.id === credentialId),
    ...(created && !profiles.some((p) => p.id === created.id) ? [created] : []),
  ]

  const clearProbe = () => {
    probeSeq.current += 1
    setProbing(false)
    setProbe(null)
    setProbeFailed(false)
    setUnverifiedAck(false)
    setConnectionTouched(true)
  }

  const invalidate = () => {
    clearProbe()
    setScanSelected(null)
    setScans([])
    setScanEmpty(false)
  }

  // runScan dan selectScan: salin apa adanya dari versi lama

  const runProbe = async () => {
    if (!endpointHost || !mainPath.trim()) return
    const seq = ++probeSeq.current
    setProbing(true)
    setProbe(null)
    setProbeFailed(false)
    setError(null)
    try {
      const result = await probeCamera({
        host: endpointHost,
        main_path: safePath(mainPath),
        sub_path: safePath(subPath),
        ...(credentialId != null ? { credential_override_id: credentialId } : {}),
        snapshot: true,
      })
      if (seq !== probeSeq.current) return
      setProbe(result)
      setMainPath(safePath(result.main_path) ?? mainPath)
      setSubPath(safePath(result.sub_path) ?? subPath)
    } catch {
      if (seq === probeSeq.current) setProbeFailed(true)
    } finally {
      if (seq === probeSeq.current) setProbing(false)
    }
  }

  const save = async () => {
    if (!verified && !unverifiedAck) {
      setUnverifiedAck(true) // klik kedua = simpan tanpa tes
      return
    }
    setSaving(true)
    setError(null)
    const connection = {
      host: endpointHost,
      node_id: nodeId === '' ? null : nodeId,
      rtsp_main: probe?.main_path ?? (safePath(mainPath) || null),
      rtsp_sub: probe?.sub_path ?? (safePath(subPath) || null),
      credential_override_id: credentialId,
    }
    const probeMeta = {
      probe_main: probe?.main ?? null,
      probe_sub: probe?.sub ?? null,
      status: probe?.main || probe?.sub ? 'online' : 'offline',
    }
    try {
      if (camera) {
        await updateCamera(
          camera.id,
          connectionTouched
            ? { name: name.trim(), location: location.trim() || null, ...connection, ...probeMeta }
            : { name: name.trim(), location: location.trim() || null },
        )
      } else {
        await createCamera({ name: name.trim(), location: location.trim() || null, ...connection, ...probeMeta })
      }
      onSaved()
    } catch (e) {
      setError(e instanceof Error && e.message === 'duplicate' ? t('cameras.wizard.duplicate') : t('cameras.saveError'))
      setSaving(false)
    }
  }

  return (
    <ComposedModal open onClose={onClose} size="sm" preventCloseOnClickOutside>
      <ModalHeader title={t(isEdit ? 'cameras.wizard.editTitle' : 'cameras.wizard.title')} closeModal={onClose} />
      <ModalBody>
        <TextInput id="wiz-name" labelText={t('cameras.wizard.name')} placeholder="Lorong Manager"
          value={name} onChange={(e) => setName(e.target.value)} />
        <TextInput id="wiz-location" labelText={t('cameras.wizard.location')} placeholder="LT 2" list="wiz-locations"
          value={location} onChange={(e) => setLocation(e.target.value)} style={{ marginTop: 12 }} />
        <datalist id="wiz-locations">
          {locations.map((l) => <option key={l} value={l} />)}
        </datalist>
        <TextInput id="wiz-host" labelText={t('cameras.wizard.host')} helperText={t('cameras.wizard.hostHint')}
          placeholder="192.168.1.108" value={host} style={{ marginTop: 12 }}
          onChange={(e) => { setHost(e.target.value); invalidate() }} />
        <TextInput id="wiz-main-path" labelText={t('cameras.wizard.mainPath')} placeholder="/Streaming/Channels/101"
          value={mainPath} style={{ marginTop: 12 }}
          onChange={(e) => { setMainPath(e.target.value); clearProbe() }} />
        <TextInput id="wiz-sub-path" labelText={t('cameras.wizard.subPath')} helperText={t('cameras.wizard.subHint')}
          placeholder="/Streaming/Channels/102" value={subPath} style={{ marginTop: 12 }}
          onChange={(e) => { setSubPath(e.target.value); clearProbe() }} />
        {subSameAsMain && (
          <InlineNotification kind="warning" lowContrast hideCloseButton title={t('cameras.wizard.subSameAsMain')}
            style={{ marginTop: 8 }} />
        )}
        <Select id="wiz-credential" labelText={t('cameras.wizard.credential')} value={credentialId ?? ''}
          style={{ marginTop: 12 }}
          onChange={(e) => {
            if (e.target.value === NEW_CREDENTIAL) {
              setNewCredential(true)
              return
            }
            setCredentialId(e.target.value === '' ? null : Number(e.target.value))
            clearProbe()
          }}>
          <SelectItem value="" text={t('cameras.wizard.credentialDefault')} />
          {profileOptions.map((p) => <SelectItem key={p.id} value={p.id} text={p.name} />)}
          <SelectItem value={NEW_CREDENTIAL} text={t('cameras.wizard.credentialNew')} />
        </Select>
        {newCredential && (
          <NewCredentialForm
            onCancel={() => setNewCredential(false)}
            onCreated={(p) => {
              setNewCredential(false)
              setCreated(p)
              setCredentialId(p.id)
              clearProbe()
              onProfilesChanged()
            }}
          />
        )}

        <Button kind="secondary" size="sm" onClick={runProbe} disabled={probing || !endpointHost || !mainPath.trim()}
          style={{ marginTop: 12 }}>
          {t('cameras.wizard.probe')}
        </Button>
        <div data-testid="probe-box"
          style={{ border: '1px dashed var(--cds-border-subtle)', padding: 12, marginTop: 12, fontSize: 12, minHeight: 84 }}>
          {probing ? (
            <InlineLoading description={t('cameras.wizard.probing')} />
          ) : probe || probeFailed ? (
            <>
              <div style={{ color: probe?.main ? '#42be65' : '#fa4d56' }}>
                MAIN: {streamText(probe?.main ?? null, probe?.main_path ?? null, t('cameras.wizard.probeFail'))}
              </div>
              <div style={{ color: probe?.sub ? '#42be65' : '#fa4d56' }}>
                SUB: {streamText(probe?.sub ?? null, probe?.sub_path ?? null, t('cameras.wizard.probeFail'))}
              </div>
              {probe?.snapshot_jpeg_b64 && (
                <img data-testid="probe-thumb" alt="" src={`data:image/jpeg;base64,${probe.snapshot_jpeg_b64}`}
                  style={{ display: 'block', width: '100%', maxWidth: 320, marginTop: 8 }} />
              )}
            </>
          ) : (
            t('cameras.wizard.probeHint')
          )}
        </div>

        <details data-testid="wiz-advanced" style={{ marginTop: 14 }}>
          <summary style={{ cursor: 'pointer', fontSize: 13 }}>{t('cameras.wizard.advanced')}</summary>
          {nodes.length > 1 && (
            <Select id="wiz-node" labelText={t('cameras.wizard.node')} value={nodeId} style={{ marginTop: 12 }}
              onChange={(e) => { setNodeId(Number(e.target.value)); if (isEdit) clearProbe() }}>
              {nodes.map((n) => <SelectItem key={n.id} value={n.id} text={n.name} />)}
            </Select>
          )}
          {/* tombol "Deteksi otomatis", InlineLoading scanning, pesan scanEmpty, dan Select wiz-scan:
              salin apa adanya dari versi lama (blok di bawah Node) */}
        </details>

        {unverifiedAck && !verified && (
          <InlineNotification kind="warning" lowContrast hideCloseButton title={t('cameras.wizard.unverified')}
            style={{ marginTop: 12 }} />
        )}
        {error && (
          <InlineNotification kind="error" lowContrast subtitle={error} title={t('cameras.wizard.saveFailed')}
            onCloseButtonClick={() => setError(null)} style={{ marginTop: 12 }} />
        )}
      </ModalBody>
      <ModalFooter>
        <Button kind="ghost" onClick={onClose}>{t('common.cancel')}</Button>
        <Button onClick={save} disabled={!canSave}>{t('common.save')}</Button>
      </ModalFooter>
    </ComposedModal>
  )
}
```

Catatan: blok `// ... salin apa adanya` merujuk ke kode di `CameraWizard.tsx` versi `main` (helper baris 33–73; `runScan`/`selectScan` baris 129–156; tombol scan + hasil baris 276–308). Blok `manual` + tombol `Isi path manual` dihapus (path selalu tampil).

`frontend/src/features/config/CamerasPage.tsx` — mount wizard:

```tsx
        <CameraWizard
          camera={editing ?? undefined}
          profiles={profiles}
          locations={[...new Set(cams.map((c) => c.location).filter((l): l is string => !!l))].sort()}
          onProfilesChanged={() => void refreshReferences()}
          onClose={() => {
```

`frontend/src/app/i18n.tsx` — ubah/tambah di blok `id`:

```ts
    'cameras.wizard.host': 'IP kamera',
    'cameras.wizard.hostHint': 'Port opsional, mis. 192.168.1.108:8554',
    'cameras.wizard.mainPath': 'Path mainstream',
    'cameras.wizard.subPath': 'Path substream',
    'cameras.wizard.subHint': 'Kosong = pakai mainstream',
    'cameras.wizard.probe': 'Tes koneksi',
    'cameras.wizard.probeHint': 'Isi IP dan path, lalu klik "Tes koneksi".',
    'cameras.wizard.scanEmpty': 'Tidak ada channel NVR terdeteksi. Isi path secara manual.',
    'cameras.wizard.credential': 'Kredensial',
    'cameras.wizard.credentialDefault': 'Default (NVR)',
    'cameras.wizard.credentialNew': '+ Kredensial baru…',
    'cameras.wizard.advanced': 'Lanjutan',
    'cameras.wizard.subSameAsMain': 'Substream sama dengan mainstream — AI akan memproses resolusi penuh.',
    'cameras.wizard.unverified': 'Koneksi belum dites. Klik Simpan sekali lagi untuk tetap menyimpan.',
```

dan blok `en`:

```ts
    'cameras.wizard.host': 'Camera IP',
    'cameras.wizard.hostHint': 'Port optional, e.g. 192.168.1.108:8554',
    'cameras.wizard.mainPath': 'Mainstream path',
    'cameras.wizard.subPath': 'Substream path',
    'cameras.wizard.subHint': 'Empty = use mainstream',
    'cameras.wizard.probe': 'Test connection',
    'cameras.wizard.probeHint': 'Fill the IP and paths, then click "Test connection".',
    'cameras.wizard.scanEmpty': 'No NVR channel detected. Fill the paths manually.',
    'cameras.wizard.credential': 'Credentials',
    'cameras.wizard.credentialDefault': 'Default (NVR)',
    'cameras.wizard.credentialNew': '+ New credentials…',
    'cameras.wizard.advanced': 'Advanced',
    'cameras.wizard.subSameAsMain': 'Substream equals mainstream — AI will process full resolution.',
    'cameras.wizard.unverified': 'Connection not tested. Click Save again to save anyway.',
```

Hapus key yatim `cameras.wizard.port` dan `cameras.wizard.manualToggle` di kedua blok (cek `grep -rn "wizard.port\|manualToggle" src` kosong).

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd frontend && npx vitest run && npx tsc -b`
Expected: semua passed; tsc bersih.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Form kamera sederhana**: Nama, Lokasi (datalist), IP kamera (port opsional), Path mainstream, Path
  substream, Kredensial (Default (NVR) / profil / "+ Kredensial baru…") + Tes koneksi dengan thumbnail;
  peringatan sub = main; simpan tanpa tes = klik Simpan dua kali; Node (hanya bila > 1 node) + scan NVR di
  "Lanjutan". Frontend **<angka> passed**.
```

```bash
git add frontend/src/features/config/CameraWizard.tsx frontend/src/features/config/CamerasPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/cameras.test.tsx frontend/src/__tests__/camera-sources.test.tsx CHANGELOG.md
git commit -m "feat(camera): form tambah kamera sederhana + pilihan kredensial + thumbnail tes"
```

---

### Task 7: Halaman Kamera — Lanjutan, Kelola kredensial, kolom Kredensial

**Files:**
- Modify: `frontend/src/features/config/CamerasPage.tsx`
- Create: `frontend/src/features/config/CredentialProfilesModal.tsx`
- Delete: `frontend/src/features/config/CameraSourcesPanel.tsx`
- Modify: `frontend/src/app/i18n.tsx` (key baru; hapus key `cameras.sources.*` yang yatim)
- Test: `frontend/src/__tests__/camera-sources.test.tsx`, `frontend/src/__tests__/cameras.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `NewCredentialForm` (Task 5), `updateCredentialProfile(id, { username?, password?, enabled? })`.
- Produces: `CredentialProfilesModal({ profiles: CredentialProfile[]; onClose: () => void; onChanged: () => void })`; testid `camera-advanced-toggle`, `camera-manage-credentials`, `credential-profiles-modal`.

- [ ] **Step 1: Tulis/ubah tes (gagal)**

`frontend/src/__tests__/camera-sources.test.tsx`:
- Hapus tes `sources panel collapsed by default; expand shows source and profile forms` (bila belum dihapus di Task 6).
- Tes `viewer cannot mutate sources, groups, or credential profiles`: tambah `expect(screen.queryByTestId('camera-advanced-toggle')).not.toBeInTheDocument()`.
- Tambah:

```tsx
test('advanced menu holds import, sync and credential management; sources panel is gone', async () => {
  stubFetch((call) => baseResponse(call) ?? { status: 404 })
  renderPage()
  expect(await screen.findByText('CAM-A')).toBeInTheDocument()
  expect(screen.queryByTestId('camera-sources-toggle')).not.toBeInTheDocument()
  expect(screen.queryByTestId('go2rtc-sync')).not.toBeInTheDocument()
  await userEvent.click(screen.getByTestId('camera-advanced-toggle'))
  expect(screen.getByTestId('camera-import-btn')).toBeInTheDocument()
  expect(screen.getByTestId('go2rtc-sync')).toBeInTheDocument()
  expect(screen.getByTestId('camera-manage-credentials')).toBeInTheDocument()
})

test('camera table shows which credentials each camera uses', async () => {
  const withProfile = { ...CAMERA, id: 2, name: 'CAM-B', credential_override_id: PROFILE.id,
    credential_override: { id: PROFILE.id, name: PROFILE.name, username: PROFILE.username, enabled: true } }
  stubFetch((call) => baseResponse(call, [CAMERA, withProfile]) ?? { status: 404 })
  renderPage()
  const rowA = (await screen.findByText('CAM-A')).closest('tr')!
  const rowB = screen.getByText('CAM-B').closest('tr')!
  expect(rowA).toHaveTextContent('Default (NVR)')
  expect(rowB).toHaveTextContent('nvr-main')
})

test('manage credentials: change password and blocked disable', async () => {
  const calls = stubFetch((call) => {
    const fallback = baseResponse(call)
    if (fallback) return fallback
    if (call.url.endsWith(`/credential-profiles/${PROFILE.id}`) && call.init?.method === 'PATCH') {
      const body = JSON.parse(String(call.init.body))
      if ('enabled' in body) return { status: 409, body: { detail: 'in use' } }
      return { status: 200, body: PROFILE }
    }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click(await screen.findByTestId('camera-advanced-toggle'))
  await userEvent.click(screen.getByTestId('camera-manage-credentials'))
  const modal = await screen.findByTestId('credential-profiles-modal')
  expect(modal).toHaveTextContent('nvr-main')

  await userEvent.click(screen.getByRole('button', { name: 'Ubah nvr-main' }))
  await userEvent.type(screen.getByLabelText('Password baru', { selector: 'input' }), 'BaruSekali1')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan kredensial' }))
  await waitFor(() => {
    const patch = calls.find((c) => c.init?.method === 'PATCH' && c.url.endsWith(`/credential-profiles/${PROFILE.id}`))
    expect(JSON.parse(String(patch!.init!.body))).toEqual({ username: 'viewer', password: 'BaruSekali1' })
  })

  await userEvent.click(screen.getByRole('button', { name: 'Nonaktifkan nvr-main' }))
  expect(await screen.findByText('Masih dipakai kamera aktif — pindahkan kameranya dulu.')).toBeInTheDocument()
})
```

`frontend/src/__tests__/cameras.test.tsx` — tes `tombol Sync go2rtc memanggil endpoint dan menampilkan hasil`: sebelum klik `go2rtc-sync`, tambahkan `await userEvent.click(await screen.findByTestId('camera-advanced-toggle'))`.

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/camera-sources.test.tsx src/__tests__/cameras.test.tsx`
Expected: FAIL — `camera-advanced-toggle` tidak ada.

- [ ] **Step 3: Implementasi**

`frontend/src/features/config/CredentialProfilesModal.tsx`:

```tsx
import { useState } from 'react'
import { Button, InlineNotification, Modal, PasswordInput, Tag, TextInput } from '@carbon/react'
import { useT } from '../../app/i18n'
import { updateCredentialProfile, type CredentialProfile } from '../../api/credentialProfiles'
import NewCredentialForm from './NewCredentialForm'

type Props = {
  profiles: CredentialProfile[]
  onClose: () => void
  onChanged: () => void
}

// Daftar profil kredensial kamera: ubah username/password, (non)aktifkan, tambah baru.
export default function CredentialProfilesModal({ profiles, onClose, onChanged }: Props) {
  const { t } = useT()
  const [editing, setEditing] = useState<CredentialProfile | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const startEdit = (p: CredentialProfile) => {
    setEditing(p)
    setUsername(p.username)
    setPassword('')
    setError(null)
  }

  const saveEdit = async () => {
    if (!editing) return
    try {
      await updateCredentialProfile(editing.id, { username: username.trim(), ...(password ? { password } : {}) })
      setEditing(null)
      onChanged()
    } catch {
      setError(t('cameras.cred.saveError'))
    }
  }

  const toggle = async (p: CredentialProfile) => {
    setError(null)
    try {
      await updateCredentialProfile(p.id, { enabled: !p.enabled })
      onChanged()
    } catch (e) {
      setError(t(e instanceof Error && e.message.endsWith(': 409') ? 'cameras.cred.inUse' : 'cameras.cred.saveError'))
    }
  }

  return (
    <Modal open passiveModal size="sm" modalHeading={t('cameras.manageCredentials')} onRequestClose={onClose}
      data-testid="credential-profiles-modal">
      <p style={{ fontSize: 12, marginBottom: 12 }}>{t('cameras.cred.hint')}</p>
      {profiles.length === 0 && <p>{t('cameras.cred.empty')}</p>}
      {profiles.map((p) => (
        <div key={p.id} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', padding: '6px 0' }}>
          <strong style={{ minWidth: 120 }}>{p.name}</strong>
          <span style={{ color: 'var(--cds-text-secondary)' }}>{p.username || '—'}</span>
          {!p.enabled && <Tag size="sm" type="gray">{t('cameras.cred.disabled')}</Tag>}
          <span style={{ flex: 1 }} />
          <Button kind="ghost" size="sm" aria-label={`${t('cameras.edit')} ${p.name}`} onClick={() => startEdit(p)}>
            {t('cameras.edit')}
          </Button>
          <Button kind="ghost" size="sm"
            aria-label={`${t(p.enabled ? 'cameras.cred.disable' : 'cameras.cred.enable')} ${p.name}`}
            onClick={() => void toggle(p)}>
            {t(p.enabled ? 'cameras.cred.disable' : 'cameras.cred.enable')}
          </Button>
        </div>
      ))}
      {editing && (
        <div style={{ borderTop: '1px solid var(--cds-border-subtle)', marginTop: 8, paddingTop: 12 }}>
          <TextInput id="cred-edit-username" labelText={t('cameras.cred.username')} value={username} autoComplete="off"
            onChange={(e) => setUsername(e.target.value)} />
          <PasswordInput id="cred-edit-password" labelText={t('cameras.cred.newPassword')}
            helperText={t('cameras.cred.keepPassword')} value={password} autoComplete="new-password"
            onChange={(e) => setPassword(e.target.value)} style={{ marginTop: 12 }} />
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <Button size="sm" onClick={() => void saveEdit()}>{t('cameras.cred.save')}</Button>
            <Button size="sm" kind="ghost" onClick={() => setEditing(null)}>{t('common.cancel')}</Button>
          </div>
        </div>
      )}
      <Button kind="ghost" size="sm" onClick={() => setAdding(true)} style={{ marginTop: 12 }}>
        {t('cameras.wizard.credentialNew')}
      </Button>
      {error && <InlineNotification kind="error" lowContrast hideCloseButton title={error} style={{ marginTop: 12 }} />}
      {adding && (
        <NewCredentialForm onCancel={() => setAdding(false)} onCreated={() => { setAdding(false); onChanged() }} />
      )}
    </Modal>
  )
}
```

`frontend/src/features/config/CamerasPage.tsx`:
- Hapus `import CameraSourcesPanel ...`, `import { listStreamSources, type StreamSource } ...`, state `sources`, dan render `<CameraSourcesPanel … />`. `refreshReferences` menjadi:

```tsx
  const refreshReferences = useCallback(async () => {
    try {
      setProfiles(await listCredentialProfiles())
    } catch {
      setError(t('cameras.sources.loadError'))
    }
  }, [t])
```
- Tambah import `CredentialProfilesModal` dan state `const [advancedOpen, setAdvancedOpen] = useState(false)`, `const [credentialsOpen, setCredentialsOpen] = useState(false)`.
- Ganti blok tombol header admin (input file tetap dirender; hanya tombol yang dipindah):

```tsx
      {isAdmin && (
        <>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 8 }}>
            <input ref={importInput} type="file" accept=".txt,text/plain" data-testid="camera-import-input"
              style={{ display: 'none' }} onChange={onImportFile} />
            <Button kind="ghost" data-testid="camera-advanced-toggle" aria-expanded={advancedOpen}
              onClick={() => setAdvancedOpen((v) => !v)}>
              {t('cameras.advanced')}
            </Button>
            <Button onClick={() => setWizardOpen(true)}>{t('cameras.add')}</Button>
          </div>
          {advancedOpen && (
            <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 8, marginBottom: 14 }}>
              <Button kind="ghost" size="sm" disabled={importBusy} data-testid="camera-import-btn"
                onClick={() => importInput.current?.click()}>
                {t('cameras.import.button')}
              </Button>
              <Button kind="ghost" size="sm" disabled={syncBusy} data-testid="go2rtc-sync" onClick={syncStreams}
                title={t('cameras.sync.hint')}>
                {t('cameras.sync.btn')}
              </Button>
              <Button kind="ghost" size="sm" data-testid="camera-manage-credentials" onClick={() => setCredentialsOpen(true)}>
                {t('cameras.manageCredentials')}
              </Button>
            </div>
          )}
        </>
      )}
```

- Kolom tabel: di `headers` sisipkan `{ key: 'credential', header: t('cameras.col.credential') }` sebelum `node`; di baris, sebelum sel node:

```tsx
                        <TableCell>{cam.credential_override?.name ?? t('cameras.wizard.credentialDefault')}</TableCell>
```

- Di dekat mount wizard:

```tsx
      {credentialsOpen && (
        <CredentialProfilesModal profiles={profiles} onClose={() => setCredentialsOpen(false)}
          onChanged={() => void refreshReferences()} />
      )}
```

- Hapus file `frontend/src/features/config/CameraSourcesPanel.tsx`.

`frontend/src/app/i18n.tsx` — tambah di blok `id`:

```ts
    'cameras.advanced': 'Lanjutan',
    'cameras.manageCredentials': 'Kelola kredensial',
    'cameras.col.credential': 'Kredensial',
    'cameras.cred.hint': 'Username/password kamera yang berbeda dari default NVR. Password tidak pernah ditampilkan.',
    'cameras.cred.empty': 'Belum ada kredensial khusus — semua kamera memakai Default (NVR).',
    'cameras.cred.disabled': 'Nonaktif',
    'cameras.cred.disable': 'Nonaktifkan',
    'cameras.cred.enable': 'Aktifkan',
    'cameras.cred.newPassword': 'Password baru',
    'cameras.cred.keepPassword': 'Kosongkan bila tidak diganti',
    'cameras.cred.inUse': 'Masih dipakai kamera aktif — pindahkan kameranya dulu.',
```

dan blok `en`:

```ts
    'cameras.advanced': 'Advanced',
    'cameras.manageCredentials': 'Manage credentials',
    'cameras.col.credential': 'Credentials',
    'cameras.cred.hint': 'Camera username/password that differ from the NVR default. Passwords are never shown.',
    'cameras.cred.empty': 'No custom credentials yet — all cameras use Default (NVR).',
    'cameras.cred.disabled': 'Disabled',
    'cameras.cred.disable': 'Disable',
    'cameras.cred.enable': 'Enable',
    'cameras.cred.newPassword': 'New password',
    'cameras.cred.keepPassword': 'Leave empty to keep the current password',
    'cameras.cred.inUse': 'Still used by an enabled camera — move that camera first.',
```

Hapus key `cameras.sources.*` yang tidak lagi dipakai di mana pun (`grep -rn "cameras.sources\." src --include=*.tsx` hanya boleh menyisakan pemakaian nyata).

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: semua passed; build 0; lint = set rule+file lama (bandingkan pasangan rule+file dengan output `npm run lint` di `main`).

Cek 390 px: `npm run dev`, buka `/configuration?tab=cameras`, viewport 390 (mis. `node temp/tools/cdp-viewport.mjs` bila tersedia atau DevTools) → `document.documentElement.scrollWidth <= 390` dengan wizard terbuka dan modal Kelola kredensial terbuka.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Halaman Kamera dirapikan**: panel "Sumber & kredensial" dihapus (`CameraSourcesPanel`); tombol
  **Lanjutan** berisi Import CSV, Sync go2rtc, dan **Kelola kredensial** (ubah username/password — kosong =
  tidak diganti, nonaktifkan dengan pesan bila masih dipakai, tambah baru); kolom **Kredensial** di tabel
  (Default (NVR) / nama profil). Frontend **<angka> passed**, build 0, lint set sama; 390 px tanpa overflow.
```

```bash
git add -A frontend/src/features/config frontend/src/app/i18n.tsx frontend/src/__tests__/camera-sources.test.tsx frontend/src/__tests__/cameras.test.tsx CHANGELOG.md
git commit -m "feat(camera): menu Lanjutan, kelola kredensial, kolom kredensial; hapus panel sumber"
```

---

### Task 8: Dokumen, suite penuh, deploy + verifikasi (langkah ⚠ butuh izin user)

**Files:**
- Modify: `README.md` (bagian kamera/konfigurasi bila menyebut wizard/kredensial), `ROADMAP.md` (baris baru), `docs/runbooks/` (runbook kredensial kamera bila ada runbook kamera; bila tidak, bagian singkat di README)
- Create: `docs/evidence/camera-registration-*.png|txt`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Dokumen**

- `ROADMAP.md` tabel ringkasan, sebelum baris `| E | Edge Jetson …`: `| CR | Pendaftaran kamera sederhana (IP + path + kredensial per profil) | [~] lokal selesai, PENDING deploy + verifikasi | — | spec + plan 2026-09-24 | |`.
- README / runbook: jelaskan (1) form tambah kamera, (2) kredensial default dari `.env` `CAM_USERNAME/CAM_PASSWORD`, (3) kredensial khusus lewat Lanjutan → Kelola kredensial disimpan di `CAMERA_SECRETS_FILE` (0600, di luar `STORAGE_ROOT`), (4) **backup**: file rahasia harus ikut dibackup bersama DB — tanpa file itu kamera berkredensial khusus gagal konek ("credential reference is unavailable"), (5) rollback: kamera berprofil `store:` dikembalikan ke Default sebelum `git revert`.

- [ ] **Step 2: Suite penuh**

```bash
cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1; cd ..
backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu" | tail -1
cd frontend && npx vitest run | tail -3 && npm run build > /dev/null; echo build=$?; npm run lint | tail -2; cd ..
```

Expected: backend > 342 semua passed; vision 200 passed, 3 deselected; frontend > 121 semua passed; build 0; lint set sama.

- [ ] **Step 3: Commit dokumen**

```bash
git add README.md ROADMAP.md docs/runbooks CHANGELOG.md
git commit -m "docs(camera): pendaftaran kamera sederhana + kredensial per profil"
```

- [ ] **Step 4 ⚠: Deploy (minta izin user dulu)**

```bash
git push -u origin feat/camera-registration-simple
ssh gspe-ai3 'cd /home/gspe-ai3/project_cv/I-Sentinel && git fetch -q && git checkout -q feat/camera-registration-simple && git pull -q && kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs); sleep 8; curl -s localhost:8000/api/v1/health'
```

Expected: `{"status":"ok"}`. Frontend Vite (`isentinel-web`) ikut tanpa restart. Tidak ada migrasi.

- [ ] **Step 5: Verifikasi (bersama user)**

1. User membuka `http://192.168.2.133:5173/configuration?tab=cameras` → form Tambah kamera hanya berisi field utama; Lanjutan tertutup.
2. User mencoba **Tes koneksi** pada kamera yang sudah ada (Ubah → Tes koneksi) → res/fps + thumbnail muncul.
3. Bila ada kamera berkredensial berbeda: buat lewat "+ Kredensial baru…", Tes koneksi berhasil, Simpan, kamera muncul di Live View.
4. Cek server (baca-saja): `ssh gspe-ai3 'ls -l ~/.isentinel/camera-secrets.json'` → `-rw-------`; response `GET /api/v1/credential-profiles` tidak memuat password (cek lewat API login seperti di checkpoint, tanpa mencetak password).
5. Screenshot form + modal (390 px dan desktop) ke `docs/evidence/camera-registration-*.png`.

- [ ] **Step 6: CHANGELOG + ROADMAP + commit**

Bullet "Deploy + verifikasi" dengan hasil nyata; ROADMAP baris CR → `[x]` bila user OK.

```bash
git add docs/evidence/camera-registration-* CHANGELOG.md ROADMAP.md
git commit -m "docs(camera): evidence deploy + verifikasi pendaftaran kamera"
```

Setelah user E2E OK: merge `--no-ff` ke `main` (butuh izin), server kembali ke `main`.
