"""Run retention at 03:00 local time; a failed sweep must not end the loop."""
from datetime import datetime, timedelta
import logging
import subprocess
import sys
import time

LOG = logging.getLogger(__name__)


def seconds_until(now: datetime, at: str = "03:00") -> float:
    """Return a positive delay to the next local wall-clock sweep time."""
    hour, minute = map(int, at.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def sweep() -> int:
    """Invoke the existing backend retention script from /app."""
    return subprocess.run([sys.executable, "scripts/retention_sweep.py"], check=False).returncode


def main(run=sweep, sleep=time.sleep, max_runs=None) -> None:
    """Sleep before each sweep and keep scheduling after nonzero exits."""
    runs = 0
    while max_runs is None or runs < max_runs:
        delay = seconds_until(datetime.now())
        LOG.info("Next retention sweep in %.0f seconds", delay)
        sleep(delay)
        result = run()
        if result:
            LOG.error("Retention sweep failed: exit %s", result)
        else:
            LOG.info("Retention sweep completed")
        runs += 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
