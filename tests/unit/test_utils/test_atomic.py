"""Тесты для unifi_manager.utils.atomic.atomic_write_json."""

import json
import logging
from pathlib import Path

import pytest


@pytest.mark.fast()
def test_atomic_write_json_roundtrip_cyrillic(tmp_path: Path) -> None:
    """Пишет читаемый JSON (parent создаётся), ensure_ascii=False, без tmp-хвоста."""
    from unifi_manager.utils.atomic import atomic_write_json

    target = tmp_path / "sub" / "state.json"  # parent не существует
    atomic_write_json(target, {"ap-down:Ресторан": "2026-06-14T10:00:00+00:00"})

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "ap-down:Ресторан": "2026-06-14T10:00:00+00:00"
    }
    assert "Ресторан" in target.read_text(encoding="utf-8")  # не \uXXXX
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.fast()
def test_atomic_write_json_overwrites(tmp_path: Path) -> None:
    from unifi_manager.utils.atomic import atomic_write_json

    target = tmp_path / "s.json"
    atomic_write_json(target, {"a": 1})
    atomic_write_json(target, {"b": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"b": 2}


@pytest.mark.fast()
def test_atomic_write_json_oserror_swallowed_and_tmp_cleaned(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """OSError (parent — файл) → логируется и проглатывается (не raise), tmp не оставлен."""
    from unifi_manager.utils.atomic import atomic_write_json

    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    target = blocker / "sub" / "state.json"  # mkdir(parent) упадёт: afile — файл

    with caplog.at_level(logging.ERROR):
        atomic_write_json(target, {"a": 1})  # не должно бросить

    assert any("Failed to save" in r.getMessage() for r in caplog.records)
    assert not list(tmp_path.rglob("*.tmp"))
