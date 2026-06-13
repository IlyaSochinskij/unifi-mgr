"""FileLock — атомарный inter-process lock через fasteners.

Заменяет TOCTOU-race lock из _legacy/auto_restart_cron.sh.
Используется RestartService и любой cron-командой для защиты от
параллельных запусков.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import TracebackType

import fasteners

_logger = logging.getLogger(__name__)


class LockAcquisitionError(Exception):
    """Не удалось acquire lock в указанный timeout."""


class FileLock:
    """Inter-process file lock.

    Использование:
        with FileLock(Path("/var/lib/unifi-mgr/restart.lock")):
            ...  # work that must not overlap

    Если другой процесс держит lock — raises LockAcquisitionError
    после timeout секунд.
    """

    def __init__(self, path: Path, *, timeout: float = 10.0) -> None:
        self.path = path
        self.timeout = timeout
        self.locked = False
        # fasteners.InterProcessLock сам создаёт файл при acquire
        self._lock = fasteners.InterProcessLock(str(path))

    def __enter__(self) -> FileLock:
        if self.timeout == 0:
            # Non-blocking: try once immediately — avoids poll loop that relies on
            # time.monotonic() (which freezegun patches in tests, causing infinite loops).
            acquired = self._lock.acquire(blocking=False)
        else:
            # Blocking with timeout: poll every 0.1 s up to timeout seconds.
            acquired = self._lock.acquire(timeout=self.timeout, delay=0.1)
        if not acquired:
            raise LockAcquisitionError(f"Could not acquire lock {self.path} within {self.timeout}s")
        self.locked = True
        _logger.debug("Acquired lock %s", self.path)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self.locked:
            self._lock.release()
            self.locked = False
            _logger.debug("Released lock %s", self.path)
