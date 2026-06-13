"""Тесты для unifi_manager.services.lock.FileLock."""

import multiprocessing as mp
from pathlib import Path

import pytest

from tests.unit.test_services.conftest import lock_held_by_other_process


@pytest.mark.fast()
def test_lock_acquires_and_releases(tmp_path: Path) -> None:
    """Lock как context manager — acquire/release при входе/выходе."""
    from unifi_manager.services.lock import FileLock

    lock_path = tmp_path / "test.lock"
    with FileLock(lock_path) as lock:
        assert lock.locked is True
    assert lock.locked is False


@pytest.mark.fast()
def test_lock_creates_file(tmp_path: Path) -> None:
    """Lock file создаётся на диске при acquire."""
    from unifi_manager.services.lock import FileLock

    lock_path = tmp_path / "test.lock"
    assert not lock_path.exists()

    with FileLock(lock_path):
        assert lock_path.exists()


@pytest.mark.fast()
def test_lock_blocks_concurrent_acquisition(tmp_path: Path) -> None:
    """Второй FileLock на тот же путь НЕ может acquire пока первый держит.

    Uses a real subprocess so the test is valid on POSIX (fcntl locks are
    per-process; same-process double-acquire is a no-op on Linux).
    """
    from unifi_manager.services.lock import FileLock, LockAcquisitionError

    lock_path = tmp_path / "test.lock"
    with lock_held_by_other_process(lock_path, tmp_path):
        with pytest.raises(LockAcquisitionError):
            with FileLock(lock_path, timeout=0):
                pytest.fail("should not have acquired a lock held by another process")


@pytest.mark.fast()
def test_lock_releases_after_exception(tmp_path: Path) -> None:
    """Если в with-блоке raise — lock всё равно release."""
    from unifi_manager.services.lock import FileLock

    lock_path = tmp_path / "test.lock"
    with pytest.raises(RuntimeError, match="test error"):
        with FileLock(lock_path):
            raise RuntimeError("test error")

    # После исключения — lock доступен для нового acquire
    with FileLock(lock_path):
        pass  # успешно acquire


def _child_process_acquire(lock_path: str, result_queue: mp.Queue) -> None:
    """Helper для multiprocessing-теста — попытаться acquire lock из child процесса."""
    from unifi_manager.services.lock import FileLock, LockAcquisitionError

    try:
        with FileLock(Path(lock_path), timeout=0):
            result_queue.put("acquired")
    except LockAcquisitionError:
        result_queue.put("blocked")


@pytest.mark.slow()  # slow — multiprocessing overhead
def test_lock_blocks_across_processes(tmp_path: Path) -> None:
    """Lock из разных процессов реально блокирует (atomicity via fasteners)."""
    from unifi_manager.services.lock import FileLock

    lock_path = tmp_path / "test.lock"
    result_queue: mp.Queue = mp.Queue()

    with FileLock(lock_path):
        # Запускаем child процесс который пытается acquire
        proc = mp.Process(target=_child_process_acquire, args=(str(lock_path), result_queue))
        proc.start()
        proc.join(timeout=5)
        assert proc.exitcode == 0

    result = result_queue.get(timeout=1)
    assert result == "blocked"


@pytest.mark.fast()
def test_lock_timeout_parameter(tmp_path: Path) -> None:
    """timeout=0 — не ждать, сразу raise если lock занят.

    Uses a real subprocess so the test is valid on POSIX (fcntl locks are
    per-process; same-process double-acquire is a no-op on Linux).
    """
    from unifi_manager.services.lock import FileLock, LockAcquisitionError

    lock_path = tmp_path / "test.lock"
    with lock_held_by_other_process(lock_path, tmp_path):
        # timeout=0 → non-blocking acquire → immediately raises
        with pytest.raises(LockAcquisitionError):
            with FileLock(lock_path, timeout=0):
                pass
