"""Тесты для unifi_manager.services.restart_decisions."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

# === priority_score ===


@pytest.mark.fast()
def test_priority_score_connection_interrupted_highest() -> None:
    """state=10 (CONNECTION_INTERRUPTED) — наивысший приоритет (1)."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=10, offline_min=0) == 1


@pytest.mark.fast()
def test_priority_score_offline_short_high() -> None:
    """state=0, offline < 5 min — priority 1."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=0, offline_min=3) == 1


@pytest.mark.fast()
def test_priority_score_offline_medium() -> None:
    """state=0, 5 <= offline < 15 — priority 2."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=0, offline_min=10) == 2


@pytest.mark.fast()
def test_priority_score_offline_long() -> None:
    """state=0, offline >= 15 — priority 3."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=0, offline_min=20) == 3


@pytest.mark.fast()
def test_priority_score_online_lowest() -> None:
    """state=1 (online) — priority 99 (effectively skip)."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=1, offline_min=0) >= 99


@pytest.mark.fast()
@given(
    state=st.integers(min_value=0, max_value=20), offline_min=st.floats(min_value=0, max_value=1000)
)
def test_priority_score_always_positive(state: int, offline_min: float) -> None:
    """Property: priority always >= 1 (никогда не 0 или отрицательный)."""
    from unifi_manager.services.restart_decisions import priority_score

    assert priority_score(state=state, offline_min=offline_min) >= 1


# === classify_action ===


@pytest.mark.fast()
def test_classify_action_state10_with_uplink_is_poe_cycle() -> None:
    """state=10 + uplink → poe_cycle."""
    from unifi_manager.services.restart_decisions import classify_action

    action, _ = classify_action(state=10, has_uplink=True)
    assert action == "poe_cycle"


@pytest.mark.fast()
def test_classify_action_state10_no_uplink_is_restart() -> None:
    """state=10 без uplink → restart (попробуем оживить через API)."""
    from unifi_manager.services.restart_decisions import classify_action

    action, _ = classify_action(state=10, has_uplink=False)
    assert action == "restart"


@pytest.mark.fast()
def test_classify_action_offline_with_uplink_is_poe_cycle() -> None:
    from unifi_manager.services.restart_decisions import classify_action

    action, _ = classify_action(state=0, has_uplink=True)
    assert action == "poe_cycle"


@pytest.mark.fast()
def test_classify_action_adopting_is_skip() -> None:
    """state=4,5,6 (GETTING_READY/ADOPTING) — skip (wait)."""
    from unifi_manager.services.restart_decisions import classify_action

    for s in (4, 5, 6):
        action, _ = classify_action(state=s, has_uplink=True)
        assert action is None


@pytest.mark.fast()
def test_classify_action_online_is_skip() -> None:
    from unifi_manager.services.restart_decisions import classify_action

    action, _ = classify_action(state=1, has_uplink=True)
    assert action is None


# === should_skip_by_exclude_pattern ===


@pytest.mark.fast()
def test_should_skip_pattern_match() -> None:
    """Имя содержит exclude pattern → skip."""
    from unifi_manager.services.restart_decisions import should_skip_by_exclude_pattern

    assert should_skip_by_exclude_pattern("Spasatel vagon", ["Spasatel", "test"]) is True


@pytest.mark.fast()
def test_should_skip_pattern_no_match() -> None:
    from unifi_manager.services.restart_decisions import should_skip_by_exclude_pattern

    assert should_skip_by_exclude_pattern("Restoran", ["Spasatel", "test"]) is False


@pytest.mark.fast()
def test_should_skip_empty_patterns() -> None:
    from unifi_manager.services.restart_decisions import should_skip_by_exclude_pattern

    assert should_skip_by_exclude_pattern("anything", []) is False


@pytest.mark.fast()
def test_should_skip_case_insensitive() -> None:
    from unifi_manager.services.restart_decisions import should_skip_by_exclude_pattern

    assert should_skip_by_exclude_pattern("TEST-AP", ["test"]) is True
