"""Shared fixtures and helpers for test_services tests."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Python snippet run in a child process to hold a FileLock.
# Writes a ready-file once the lock is acquired, then sleeps until killed.
_HOLDER_SRC = (
    "import sys, time\n"
    "from unifi_manager.services.lock import FileLock\n"
    "lock_path, ready_path = sys.argv[1], sys.argv[2]\n"
    "with FileLock(lock_path):\n"
    "    open(ready_path, 'w').close()\n"
    "    time.sleep(30)\n"
)


@contextmanager
def lock_held_by_other_process(lock_path: Path, tmp_path: Path) -> Iterator[None]:
    """Spawn a separate process that holds FileLock(lock_path); yield while held.

    Mimics a real cron instance still running.  Cross-process exclusion works on
    both Linux (fcntl) and Windows (handle-based), unlike same-process
    double-acquire which is a no-op on POSIX.

    The caller must ensure lock_path.parent exists before calling this.
    """
    ready = tmp_path / "holder.ready"
    proc = subprocess.Popen([sys.executable, "-c", _HOLDER_SRC, str(lock_path), str(ready)])
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            if proc.poll() is not None:
                raise RuntimeError(
                    f"lock-holder subprocess exited (rc={proc.returncode}) before acquiring"
                )
            if time.monotonic() > deadline:
                proc.terminate()
                proc.wait(timeout=5)
                raise RuntimeError("lock-holder subprocess did not acquire within 10s")
            time.sleep(0.05)
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
