from datetime import date

from pydantic import BaseModel, Field, model_validator

# jenis behavior yang boleh dibersihkan; attendance & system selalu dilindungi cleanup
CLEANUP_TYPES = {"intrusion", "loitering", "running", "idle_zone", "crowd"}


class StorageSettingsPatch(BaseModel):
    """Perubahan parsial pengaturan storage; field kosong = tidak diubah."""
    model_config = {"extra": "forbid"}
    clip_days: int | None = Field(default=None, ge=1, le=3650)
    snapshot_days: int | None = Field(default=None, ge=1, le=3650)
    attendance_days: int | None = Field(default=None, ge=1, le=3650)
    disk_alert_percent: int | None = Field(default=None, ge=50, le=99)


class CleanupIn(BaseModel):
    """Hapus event behavior per rentang tanggal lokal.

    `attendance` dan `system` tidak pernah dihapus; `types` hanya boleh berisi jenis behavior
    (bukan `attendance`/`system`/`person_detect`) — di luar itu 422.
    """
    model_config = {"extra": "forbid"}
    date_from: date
    date_to: date
    camera_ids: list[int] = []
    types: list[str] = []
    dry_run: bool = True  # aman bila klien lupa mengirim

    @model_validator(mode="after")
    def _check(self):
        if self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        if self.date_to > date.today():
            raise ValueError("date_to must not be in the future")
        unknown = set(self.types) - CLEANUP_TYPES
        if unknown:
            raise ValueError(f"unknown event types: {sorted(unknown)}")
        return self
