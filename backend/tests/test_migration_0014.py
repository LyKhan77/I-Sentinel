"""Logika murni migration 0014 (zone.behaviors) — tanpa menjalankan alembic.

Migrasi asli dijalankan di Postgres saat deploy (Task 10); di sini yang diuji
adalah pemetaan data lama -> behaviors supaya backfill tidak salah tafsir.
"""
import importlib.util
import pathlib

_PATH = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0014_zone_behaviors.py"
_spec = importlib.util.spec_from_file_location("mig0014", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_absensi_becomes_attendance_with_trigger():
    assert mig.new_type("absensi") == "attendance"
    assert mig.zone_behaviors("absensi", dwell=3, loiter=0, speed=0) == [
        {"kind": "attendance", "trigger_seconds": 3},
    ]


def test_restricted_becomes_intrusion_plus_loiter_plus_running():
    assert mig.new_type("restricted") == "behavior"
    assert mig.zone_behaviors("restricted", dwell=2, loiter=30, speed=1.5) == [
        {"kind": "intrusion", "trigger_seconds": 2},
        {"kind": "loitering", "trigger_seconds": 30},
        {"kind": "running", "trigger_seconds": 2, "speed_limit_mps": 1.5},
    ]


def test_free_zone_has_no_behavior():
    assert mig.new_type("free") == "behavior"
    assert mig.zone_behaviors("free", dwell=9, loiter=9, speed=9) == []


def test_new_values_are_idempotent():
    assert mig.new_type("behavior") == "behavior"
    assert mig.new_type("attendance") == "attendance"
    assert mig.zone_behaviors("behavior", dwell=0, loiter=0, speed=0) == []


def test_attendance_type_is_idempotent_on_rerun():
    """Migrasi terulang setelah type berubah: attendance tidak kehilangan trigger."""
    assert mig.zone_behaviors("attendance", dwell=3, loiter=0, speed=0) == [
        {"kind": "attendance", "trigger_seconds": 3},
    ]


def test_old_type_mapping_back_to_legacy():
    assert mig._old_type("attendance") == "absensi"
    assert mig._old_type("behavior") == "restricted"
    assert mig._old_type("free") == "free"
