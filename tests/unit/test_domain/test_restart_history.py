"""Тесты для unifi_manager.domain.restart_history."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from freezegun import freeze_time


@pytest.mark.fast()
def test_restart_history_empty_initially(tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    h = RestartHistory(state_file=tmp_path / "history.json")
    assert h.can_restart("aa:bb:cc:dd:ee:01", cooldown=timedelta(minutes=60))[0] is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_restart_history_records_and_blocks_within_cooldown(tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    h = RestartHistory(state_file=tmp_path / "history.json")
    h.record_restart(mac="aa:bb", name="Restoran", action="restart", reason="test")
    allowed, reason = h.can_restart("aa:bb", cooldown=timedelta(minutes=60))
    assert allowed is False
    assert "cooldown" in reason.lower()


@pytest.mark.fast()
def test_restart_history_allows_after_cooldown_expires(tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    with freeze_time("2026-05-16 10:00:00") as frozen:
        h = RestartHistory(state_file=tmp_path / "history.json")
        h.record_restart(mac="aa:bb", name="x", action="restart", reason="t")

        frozen.tick(delta=timedelta(minutes=61))
        allowed, _ = h.can_restart("aa:bb", cooldown=timedelta(minutes=60))
        assert allowed is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_restart_history_count_increments(tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    h = RestartHistory(state_file=tmp_path / "history.json")
    h.record_restart(mac="aa:bb", name="x", action="restart", reason="t1")
    h.record_restart(mac="aa:bb", name="x", action="restart", reason="t2")

    entry = h.get_entry("aa:bb")
    assert entry is not None
    assert entry.count == 2


@pytest.mark.fast()
def test_restart_history_persists_to_disk(tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    with freeze_time("2026-05-16 10:00:00"):
        h1 = RestartHistory(state_file=state_file)
        h1.record_restart(mac="aa:bb", name="x", action="restart", reason="t")
        h1.save()

    h2 = RestartHistory(state_file=state_file)
    entry = h2.get_entry("aa:bb")
    assert entry is not None
    assert entry.name == "x"


@pytest.mark.fast()
def test_restart_history_loads_legacy_format(fixtures_dir: Path, tmp_path: Path) -> None:
    """Migration test — старый формат `_legacy/auto_restart_problem_aps.py`
    (flat dict без version) читается новым кодом без потерь."""
    from unifi_manager.domain.restart_history import RestartHistory

    legacy_state = fixtures_dir / "restart_history_legacy.json"
    state_file = tmp_path / "history.json"
    state_file.write_bytes(legacy_state.read_bytes())

    h = RestartHistory(state_file=state_file)
    entry1 = h.get_entry("aa:bb:cc:dd:ee:01")
    entry2 = h.get_entry("aa:bb:cc:dd:ee:02")
    assert entry1 is not None
    assert entry1.name == "Restoran"
    assert entry1.action == "restart"
    assert entry1.count == 3
    assert entry2 is not None
    assert entry2.action == "poe_cycle"


@pytest.mark.fast()
def test_restart_history_loads_new_format(fixtures_dir: Path, tmp_path: Path) -> None:
    from unifi_manager.domain.restart_history import RestartHistory

    new_state = fixtures_dir / "restart_history_new.json"
    state_file = tmp_path / "history.json"
    state_file.write_bytes(new_state.read_bytes())

    h = RestartHistory(state_file=state_file)
    entry = h.get_entry("aa:bb:cc:dd:ee:01")
    assert entry is not None
    assert entry.count == 3


@pytest.mark.fast()
def test_restart_history_save_uses_new_format(tmp_path: Path) -> None:
    """save() пишет в new format (version=1, entries dict)."""
    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    h = RestartHistory(state_file=state_file)
    with freeze_time("2026-05-16 10:00:00"):
        h.record_restart(mac="aa:bb", name="x", action="restart", reason="t")
    h.save()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data.get("version") == 1
    assert "entries" in data
    assert "aa:bb" in data["entries"]


@pytest.mark.fast()
def test_restart_history_save_oserror_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """save() при OSError — лог error, не raise (cron-safety)."""
    from unifi_manager.domain.restart_history import RestartHistory

    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    state_file = blocker / "history.json"

    h = RestartHistory(state_file=state_file)
    with caplog.at_level("ERROR"):
        h.save()
    assert any("Failed to save" in r.message for r in caplog.records)


@pytest.mark.fast()
def test_restart_history_handles_corrupt_state(tmp_path: Path) -> None:
    """Битый JSON → start с пустого history (log warning)."""
    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    state_file.write_text("{{not json", encoding="utf-8")

    h = RestartHistory(state_file=state_file)
    assert h.get_entry("anything") is None


@pytest.mark.fast()
def test_corrupt_state_fails_closed(tmp_path: Path) -> None:
    """Битый JSON → can_restart возвращает False для ВСЕХ (fail-closed, не сброс cooldown)."""
    from datetime import timedelta

    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    state_file.write_text("{{ corrupt not json", encoding="utf-8")

    h = RestartHistory(state_file=state_file)
    allowed, reason = h.can_restart("aa:bb:cc:dd:ee:ff", cooldown=timedelta(minutes=60))
    assert allowed is False
    assert "corrupt" in reason.lower()


@pytest.mark.fast()
def test_missing_file_allows_first_run(tmp_path: Path) -> None:
    """Отсутствующий файл (первый запуск) — НЕ corrupt, can_restart True."""
    from datetime import timedelta

    from unifi_manager.domain.restart_history import RestartHistory

    h = RestartHistory(state_file=tmp_path / "subdir" / "history.json")
    allowed, _ = h.can_restart("aa:bb", cooldown=timedelta(minutes=60))
    assert allowed is True


@pytest.mark.fast()
def test_corrupt_state_save_refuses_to_clobber(tmp_path: Path) -> None:
    """save() при corrupt НЕ перезаписывает файл (сохраняем для forensics)."""
    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    original = "{{ corrupt"
    state_file.write_text(original, encoding="utf-8")

    h = RestartHistory(state_file=state_file)
    h.save()
    # Файл не должен быть перезаписан пустым/валидным JSON
    assert state_file.read_text(encoding="utf-8") == original


@pytest.mark.fast()
def test_save_atomic_no_tmp_left(tmp_path: Path) -> None:
    """После save() нет .tmp артефакта, файл — валидный JSON."""
    import json

    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    h = RestartHistory(state_file=state_file)
    h.record_restart(mac="aa:bb", name="X", action="restart", reason="t")
    h.save()

    # нет .tmp рядом
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []
    # валидный JSON
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert "entries" in data
    assert "aa:bb" in data["entries"]


# === Phase 4.5: new safety branch coverage ===


@pytest.mark.fast()
def test_corrupt_non_dict_json_list_fails_closed(tmp_path: Path) -> None:
    """File containing valid JSON array (not dict) → _corrupt=True, fail-closed (lines 69-75)."""
    from datetime import timedelta

    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    state_file.write_text("[1, 2, 3]", encoding="utf-8")

    h = RestartHistory(state_file=state_file)
    assert h._corrupt is True
    allowed, reason = h.can_restart("aa:bb", cooldown=timedelta(minutes=60))
    assert allowed is False
    assert "corrupt" in reason.lower()


@pytest.mark.fast()
def test_corrupt_non_dict_json_string_fails_closed(tmp_path: Path) -> None:
    """File containing valid JSON string (not dict) → _corrupt=True, fail-closed (lines 69-75)."""
    from datetime import timedelta

    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    state_file.write_text('"hello"', encoding="utf-8")

    h = RestartHistory(state_file=state_file)
    assert h._corrupt is True
    allowed, _reason = h.can_restart("any:mac", cooldown=timedelta(minutes=60))
    assert allowed is False


@pytest.mark.fast()
def test_oserror_on_read_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """OSError when reading existing file → _corrupt=True, fail-closed (lines 60-67)."""
    from datetime import timedelta

    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    state_file.write_text("{}", encoding="utf-8")

    # Monkeypatch Path.read_text to raise OSError after is_file() returns True
    original_read_text = state_file.__class__.read_text

    def bad_read_text(self: Path, **kwargs: object) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(state_file.__class__, "read_text", bad_read_text)

    h = RestartHistory(state_file=state_file)
    assert h._corrupt is True
    allowed, reason = h.can_restart("aa:bb", cooldown=timedelta(minutes=60))
    assert allowed is False
    assert "corrupt" in reason.lower()

    # Restore so other tests can read files
    monkeypatch.setattr(state_file.__class__, "read_text", original_read_text)


@pytest.mark.fast()
def test_parse_data_skips_non_dict_entry(tmp_path: Path) -> None:
    """Non-dict value inside entries dict → that entry skipped (line 90)."""
    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    data = {
        "version": 1,
        "entries": {
            "aa:bb": "not-a-dict",  # invalid — should be skipped (line 90)
            "cc:dd": {
                "name": "Valid AP",
                "last_restart": "2026-05-16T10:00:00+00:00",
                "action": "restart",
                "reason": "test",
                "count": 1,
            },
        },
    }
    state_file.write_text(json.dumps(data), encoding="utf-8")

    h = RestartHistory(state_file=state_file)
    assert h.get_entry("aa:bb") is None  # skipped
    assert h.get_entry("cc:dd") is not None  # valid entry loaded


@pytest.mark.fast()
def test_parse_data_skips_invalid_entry_model(tmp_path: Path) -> None:
    """Dict entry with bad field (e.g. invalid datetime) → logged warning, entry skipped (lines 97-98)."""
    from unifi_manager.domain.restart_history import RestartHistory

    state_file = tmp_path / "history.json"
    data = {
        "version": 1,
        "entries": {
            "aa:bb": {
                "name": "AP",
                "last_restart": "not-a-datetime",  # will fail model_validate
                "action": "restart",
                "reason": "test",
            },
        },
    }
    state_file.write_text(json.dumps(data), encoding="utf-8")

    h = RestartHistory(state_file=state_file)
    # Entry with bad timestamp should be silently skipped, not corrupt
    assert h._corrupt is False
    assert h.get_entry("aa:bb") is None


@pytest.mark.fast()
def test_parse_data_non_dict_directly() -> None:
    """_parse_data called with non-dict → returns empty dict (line 82)."""
    from unifi_manager.domain.restart_history import RestartHistory

    result = RestartHistory._parse_data([1, 2, 3])
    assert result == {}

    result2 = RestartHistory._parse_data("hello")
    assert result2 == {}


# === Extended SYSID_MAP (D32) ===


@pytest.mark.fast()
def test_sysid_map_includes_original_overrides() -> None:
    """Наши 4 entry из infra зеркала должны быть в final SYSID_MAP."""
    from unifi_manager.domain.device import SYSID_MAP

    assert SYSID_MAP[58759] == "UAP-AC-IW"
    assert SYSID_MAP[58679] == "UAP-AC-Pro"
    assert SYSID_MAP[58727] == "UAP-AC-M"
    assert SYSID_MAP[58711] == "UAP-AC-M-Pro"


@pytest.mark.fast()
def test_sysid_map_has_extended_coverage() -> None:
    """D32: SYSID_MAP расширен seed-словарём (>10 entries)."""
    from unifi_manager.domain.device import SYSID_MAP

    assert len(SYSID_MAP) >= 10  # минимум 4 наших + 6 seed
