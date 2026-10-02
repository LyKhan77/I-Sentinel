"""Daily local-time scheduling and resilience after a failed sweep."""
from datetime import datetime
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/retention_loop.py"


def load_loop():
    assert SCRIPT.exists(), "retention_loop.py is missing"
    spec = importlib.util.spec_from_file_location("retention_loop", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("hour,minute,want", [(2, 0, 3600), (3, 0, 86400), (23, 30, 12600), (4, 0, 82800)])
def test_seconds_until(hour, minute, want):
    seconds = load_loop().seconds_until(datetime(2026, 10, 2, hour, minute))
    assert seconds == want
    assert seconds > 0


def test_loop_survives_failed_sweep():
    module = load_loop()
    outcomes = iter([1, 0])
    sleeps = []
    calls = []

    def run():
        calls.append(True)
        return next(outcomes)

    module.main(run=run, sleep=sleeps.append, max_runs=2)
    assert len(calls) == 2
    assert len(sleeps) == 2
    assert all(value > 0 for value in sleeps)
