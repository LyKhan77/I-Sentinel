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

    `attendance` tidak pernah dihapus oleh mode `events`; `system` (log node offline) hanya bila
    dipilih di `types`; `types` hanya boleh berisi jenis behavior atau `system` — di luar itu 422.
    `attendance_data` menghapus riwayat/rekap absensi permanen untuk karyawan terpilih — lihat
    validasi khusus di bawah.
    """
    model_config = {"extra": "forbid"}
    date_from: date
    date_to: date
    camera_ids: list[int] = []
    types: list[str] = []
    employee_ids: list[int] = []  # hanya untuk mode=attendance_data
    all_employees: bool = False  # hanya untuk mode=attendance_data
    dry_run: bool = True  # aman bila klien lupa mengirim
    # events = hapus event behavior + media; attendance_media = hanya foto/crop absensi (rekap tetap);
    # attendance_data = hapus permanen riwayat + rekap + entri Inbox + media absensi karyawan terpilih
    mode: Literal["events", "attendance_media", "attendance_data"] = "events"

    @model_validator(mode="after")
    def _check(self):
        if self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        if self.mode == "attendance_data":
            # shift hari ini mungkin masih berjalan → hari ini tidak boleh, maksimum kemarin
            if self.date_to >= date.today():
                raise ValueError("date_to must be before today for mode=attendance_data")
        elif self.date_to > date.today():
            raise ValueError("date_to must not be in the future")
        if self.mode in ("attendance_media", "attendance_data") and self.types:
            raise ValueError(f"types is not allowed with mode={self.mode}")
        if self.mode == "attendance_data":
            if self.camera_ids:
                raise ValueError("camera_ids is not allowed with mode=attendance_data")
            if bool(self.employee_ids) == self.all_employees:
                raise ValueError("exactly one of employee_ids or all_employees must be set")
        elif self.employee_ids or self.all_employees:
            raise ValueError("employee_ids/all_employees are only allowed with mode=attendance_data")
        unknown = set(self.types) - CLEANUP_TYPES
        if unknown:
            raise ValueError(f"unknown event types: {sorted(unknown)}")
        return self
