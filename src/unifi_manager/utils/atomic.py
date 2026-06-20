"""Атомарная запись JSON: tmp рядом + os.replace. Против torn write.

OSError логируется и проглатывается (cron-safety): savers state-файлов (restart
history, alert dedup, telegram throttle) не должны падать из-за сбоя записи.
Атомарность защищает от частично записанного файла, НЕ от RMW-гонки параллельных
процессов (для этого — FileLock, отдельно).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


def atomic_write_json(path: Path, data: Any) -> None:
    """Записать data в path атомарно (tmp + os.replace), ensure_ascii=False.

    OSError → log + cleanup tmp, НЕ raise (вызывающие saver'ы рассчитывают на
    graceful fail в cron).
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        _logger.error("Failed to save %s: %s", path, e)
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
