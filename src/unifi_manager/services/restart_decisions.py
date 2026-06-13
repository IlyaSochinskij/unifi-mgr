"""Pure decision logic для RestartService — без I/O, без state.

Easy для Hypothesis property-based testing.
Используется RestartService для:
- Приоритизации problematic AP (какие рестартить первыми)
- Выбора action (restart vs poe_cycle vs skip)
- Фильтрации по exclude patterns
"""

from __future__ import annotations

from typing import Literal

# UniFi device state codes (из legacy):
# 0  = OFFLINE
# 1  = ONLINE
# 4  = GETTING_READY
# 5  = PENDING_ADOPTION
# 6  = ADOPTING
# 10 = CONNECTION_INTERRUPTED

Action = Literal["restart", "poe_cycle"]


def priority_score(*, state: int, offline_min: float) -> int:
    """Меньшее число = выше приоритет рестарта.

    1: CONNECTION_INTERRUPTED (state=10) или короткое offline (<5 min)
    2: medium offline (5-15 min)
    3: long offline (>15 min) — рестарт менее эффективен
    99: online или unknown — skip
    """
    if state == 10:  # CONNECTION_INTERRUPTED — urgent
        return 1
    if state == 0:
        if offline_min < 5:
            return 1
        if offline_min < 15:
            return 2
        return 3
    return 99  # ONLINE, ADOPTING, etc. — не рестартим


def classify_action(*, state: int, has_uplink: bool) -> tuple[Action | None, str]:
    """Returns (action, reason). action=None → skip.

    Логика из _legacy/auto_restart_problem_aps.py:160-176.
    """
    # ADOPTING/GETTING_READY — wait, не трогаем
    if state in (4, 5, 6):
        return None, f"state={state} — wait (adopting/pending)"

    # ONLINE — не рестартим
    if state == 1:
        return None, "state=1 (online) — no action"

    # OFFLINE or CONNECTION_INTERRUPTED
    if state in (0, 10):
        if has_uplink:
            return "poe_cycle", f"state={state} + uplink known — PoE cycle"
        return "restart", f"state={state}, no uplink info — try restart cmd"

    return None, f"state={state} — unknown, no action"


def should_skip_by_exclude_pattern(name: str, exclude_patterns: list[str]) -> bool:
    """True если name содержит любой из exclude_patterns (case-insensitive)."""
    if not exclude_patterns:
        return False
    name_lower = name.lower()
    return any(pat.lower() in name_lower for pat in exclude_patterns)
