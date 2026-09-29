from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# jenis yang boleh dipilih di cleanup; attendance tidak pernah; "system" (log node offline) hanya bila dipilih
CLEANUP_TYPES = {"intrusion", "loitering", "running", "idle_zone", "crowd", "system"}


class StorageSettingsPatch(BaseModel):
    """Perubahan parsial pengaturan storage; field kosong = tidak diubah."""
    model_config = {"extra": "forbid"}
    clip_days: int | None = Field(default=None, ge=1, le=3650)
    snapshot_days: int | None = Field(default=None, ge=1, le=3650)
    attendance_days: int | None = Field(default=None, ge=1, le=3650)
    disk_alert_percent: int | None = Field(default=None, ge=50, le=99)


class CleanupIn(BaseModel):
    """Hapus event behavior per rentang tanggal lokal.

    `attendance` tidak pernah dihapus; `system` (log node offline) hanya bila dipilih di `types`;
    `types` hanya boleh berisi jenis behavior atau `system` — di luar itu 422.
    """
    model_config = {"extra": "forbid"}
    date_from: date
    date_to: date
    camera_ids: list[int] = []
    types: list[str] = []
    dry_run: bool = True  # aman bila klien lupa mengirim
    # events = hapus event behavior + media; attendance_media = hanya foto/crop absensi (rekap tetap)
    mode: Literal["events", "attendance_media"] = "events"

    @model_validator(mode="after")
    def _check(self):
        if self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        if self.date_to > date.today():
            raise ValueError("date_to must not be in the future")
        if self.mode == "attendance_media" and self.types:
            raise ValueError("types is not allowed with mode=attendance_media")
        unknown = set(self.types) - CLEANUP_TYPES
        if unknown:
            raise ValueError(f"unknown event types: {sorted(unknown)}")
        return self
