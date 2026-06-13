"""Testy dlya unifi_manager.services.notify.AlertHistory."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from freezegun import freeze_time


@pytest.mark.fast()
def test_alert_history_empty_initially(tmp_path: Path) -> None:
    """Svezhiy state-fayl — net prior alerts."""
    from unifi_manager.services.notify import AlertHistory

    history = AlertHistory(state_file=tmp_path / "alerts.json")
    assert history.is_new_alert(hash_key="ap-down:aa:bb") is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_records_alert(tmp_path: Path) -> None:
    """Posle zapisi hash bolshe ne schitaetsya novym."""
    from unifi_manager.services.notify import AlertHistory

    history = AlertHistory(state_file=tmp_path / "alerts.json")
    history.record_alert(hash_key="ap-down:aa:bb")
    assert history.is_new_alert(hash_key="ap-down:aa:bb") is False


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_persists_to_disk(tmp_path: Path) -> None:
    """State sokhranyaetsya na disk — novyy AlertHistory chitaet sushchestvuyushchiy state."""
    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    h1 = AlertHistory(state_file=state_file)
    h1.record_alert(hash_key="ap-down:aa:bb")
    h1.save()

    h2 = AlertHistory(state_file=state_file)
    assert h2.is_new_alert(hash_key="ap-down:aa:bb") is False


@pytest.mark.fast()
def test_alert_history_cooldown_expires(tmp_path: Path) -> None:
    """Posle cooldown_minutes alert snova schitaetsya novym (dlya napominaniya)."""
    from unifi_manager.services.notify import AlertHistory

    with freeze_time("2026-05-16 10:00:00") as frozen:
        history = AlertHistory(state_file=tmp_path / "alerts.json", cooldown=timedelta(hours=1))
        history.record_alert(hash_key="ap-down:aa:bb")
        assert history.is_new_alert(hash_key="ap-down:aa:bb") is False

        frozen.move_to("2026-05-16 11:00:30")  # +1h 30s
        assert history.is_new_alert(hash_key="ap-down:aa:bb") is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_different_hashes_independent(tmp_path: Path) -> None:
    """Raznye hash — nezavisimye dedup."""
    from unifi_manager.services.notify import AlertHistory

    history = AlertHistory(state_file=tmp_path / "alerts.json")
    history.record_alert(hash_key="ap-down:aa:bb")
    assert history.is_new_alert(hash_key="ap-down:cc:dd") is True
    assert history.is_new_alert(hash_key="high-temp:ee:ff") is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_state_file_format(tmp_path: Path) -> None:
    """State JSON format — dlya otladki operatorom."""
    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    history = AlertHistory(state_file=state_file)
    history.record_alert(hash_key="ap-down:aa:bb")
    history.save()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert "ap-down:aa:bb" in data
    # ISO timestamp format
    assert "2026-05-16" in data["ap-down:aa:bb"]


@pytest.mark.fast()
def test_alert_history_handles_missing_state_file(tmp_path: Path) -> None:
    """Esli state-fayl ne sushchestvuet — startuem s pustogo history."""
    from unifi_manager.services.notify import AlertHistory

    nonexistent = tmp_path / "subdir" / "alerts.json"
    history = AlertHistory(state_file=nonexistent)
    assert history.is_new_alert(hash_key="anything") is True


@pytest.mark.fast()
def test_alert_history_handles_corrupt_state_file(tmp_path: Path) -> None:
    """Bityy JSON v state-fayle — log warning, startuem s pustogo history."""
    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    state_file.write_text("not valid json {{{", encoding="utf-8")

    history = AlertHistory(state_file=state_file)
    assert history.is_new_alert(hash_key="anything") is True


@pytest.mark.fast()
def test_alert_history_handles_non_dict_state_file(tmp_path: Path) -> None:
    """Validnyy JSON, no ne dict — log warning, startuem s pustogo history."""
    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    state_file.write_text('["not", "a", "dict"]', encoding="utf-8")

    history = AlertHistory(state_file=state_file)
    assert history.is_new_alert(hash_key="anything") is True


@pytest.mark.fast()
def test_alert_history_save_oserror_logged_not_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """save() при OSError (read-only fs) — лог error, не raise."""
    from unifi_manager.services.notify import AlertHistory

    # Mock: state_file в read-only path (используем character device или нет permissions)
    # Простой trick — state_file где parent — это файл, не директория
    state_parent_file = tmp_path / "blocking_file"
    state_parent_file.write_text("not a dir", encoding="utf-8")
    state_file = state_parent_file / "alerts.json"  # parent is a file, mkdir will fail

    history = AlertHistory(state_file=state_file)
    history.record_alert(hash_key="test")

    with caplog.at_level("ERROR"):
        history.save()  # should NOT raise

    assert any("Failed to save" in r.message for r in caplog.records)


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_handles_bad_timestamp_in_state(tmp_path: Path) -> None:
    """Nekorrektnyy timestamp v state — traktuetsya kak novyy alert."""
    import json as _json

    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    state_file.write_text(
        _json.dumps({"ap-down:aa:bb": "not-a-timestamp"}),
        encoding="utf-8",
    )

    history = AlertHistory(state_file=state_file)
    assert history.is_new_alert(hash_key="ap-down:aa:bb") is True
