"""Tests for unifi_manager.utils.time.

KRITICHNO: these functions are a fix for the timezone bug found in audit 2026-05-16.
UniFi API returns time in UTC ("2026-05-15T22:00:00Z"), while old code
compared with datetime.now() (local time without TZ). On server in UTC+3
this caused a 3-hour window shift.
"""

from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from hypothesis import given
from hypothesis import strategies as st


@pytest.mark.fast()
def test_parse_unifi_utc_basic() -> None:
    from unifi_manager.utils.time import parse_unifi_utc

    result = parse_unifi_utc("2026-05-15T22:00:00Z")
    assert result == datetime(2026, 5, 15, 22, 0, 0, tzinfo=UTC)


@pytest.mark.fast()
def test_parse_unifi_utc_result_is_timezone_aware() -> None:
    """Result is ALWAYS tz-aware (main bug fix)."""
    from unifi_manager.utils.time import parse_unifi_utc

    result = parse_unifi_utc("2026-05-15T22:00:00Z")
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)


@pytest.mark.fast()
def test_parse_unifi_utc_invalid_raises() -> None:
    from unifi_manager.utils.time import parse_unifi_utc

    with pytest.raises(ValueError, match="Invalid isoformat string"):
        parse_unifi_utc("not-a-date")


@pytest.mark.fast()
@pytest.mark.parametrize("input_str", ["", "  ", None])
def test_parse_unifi_utc_empty_raises(input_str: str | None) -> None:
    from unifi_manager.utils.time import parse_unifi_utc

    with pytest.raises((ValueError, TypeError)):
        parse_unifi_utc(input_str)  # type: ignore[arg-type]


@pytest.mark.fast()
def test_now_utc_returns_tz_aware() -> None:
    from unifi_manager.utils.time import now_utc

    n = now_utc()
    assert n.tzinfo is not None
    assert n.utcoffset() == timedelta(0)


@pytest.mark.fast()
@freeze_time("2026-05-16 07:00:00")
def test_now_utc_returns_utc_not_local() -> None:
    """now_utc() returns tz-aware UTC, not naive local time.

    freeze_time fixes UTC at 07:00. Old naive datetime.now() on a UTC+3 server
    would return local 10:00 without tzinfo, causing 3-hour comparison errors.
    now_utc() must return the correct UTC value.
    """
    from unifi_manager.utils.time import now_utc

    n = now_utc()
    assert n == datetime(2026, 5, 16, 7, 0, 0, tzinfo=UTC)


@pytest.mark.fast()
@freeze_time("2026-05-16 07:00:00")
def test_is_within_window_event_within() -> None:
    """Event 1 hour ago is within 2-hour window.

    UTC now = 07:00. Event 1 hour ago = 06:00 UTC -> in 2h window.
    """
    from unifi_manager.utils.time import is_within_window, parse_unifi_utc

    event_ts = parse_unifi_utc("2026-05-16T06:00:00Z")
    assert is_within_window(event_ts, hours=2) is True


@pytest.mark.fast()
@freeze_time("2026-05-16 07:00:00")
def test_is_within_window_event_outside() -> None:
    """Event 3 hours ago is outside 2-hour window.

    UTC now = 07:00. Event 3 hours ago = 04:00 UTC -> outside 2h window.
    """
    from unifi_manager.utils.time import is_within_window, parse_unifi_utc

    event_ts = parse_unifi_utc("2026-05-16T04:00:00Z")
    assert is_within_window(event_ts, hours=2) is False


@pytest.mark.fast()
@freeze_time("2026-05-16 07:00:00")
def test_is_within_window_old_24h_audit_case() -> None:
    """Direct test reproducing audit bug scenario.

    Old code: cutoff = datetime.now() - timedelta(hours=24)   (naive, local)
    + ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ")   (naive, UTC)
    On UTC+3 server, if local=10:00 -> naive cutoff=yesterday 10:00 local,
    but event was parsed as UTC=yesterday 08:00 which is actually yesterday 11:00 local.
    This caused events in the window to appear outside (3h drift).

    New logic: UTC now = 07:00 (2026-05-16). Cutoff 24h ago = 2026-05-15 07:00 UTC.
    Event at 2026-05-15 08:00 UTC (23h ago) -- must be IN window.
    """
    from unifi_manager.utils.time import is_within_window, parse_unifi_utc

    event_ts = parse_unifi_utc("2026-05-15T08:00:00Z")
    assert is_within_window(event_ts, hours=24) is True


@pytest.mark.fast()
def test_is_within_window_rejects_naive_datetime() -> None:
    """is_within_window requires tz-aware datetime -- naive must fail."""
    from unifi_manager.utils.time import is_within_window

    naive = datetime(2026, 5, 16, 10, 0, 0)  # no tzinfo
    with pytest.raises(ValueError, match="tz-aware"):
        is_within_window(naive, hours=2)


# === Hypothesis property-based tests ===


@pytest.mark.fast()
@given(
    year=st.integers(min_value=2020, max_value=2030),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
    second=st.integers(min_value=0, max_value=59),
)
def test_parse_unifi_utc_roundtrip(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> None:
    """parse_unifi_utc(formatted) == datetime(...) for any valid UTC."""
    from unifi_manager.utils.time import parse_unifi_utc

    ts_str = f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"
    result = parse_unifi_utc(ts_str)
    expected = datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    assert result == expected


@pytest.mark.fast()
@given(
    hours=st.integers(min_value=1, max_value=1000),
    offset_hours=st.integers(min_value=-12, max_value=12),
)
def test_is_within_window_monotonic(hours: int, offset_hours: int) -> None:
    """If event is within X hours window, it is also within X+1 hours window.

    Property: window monotonicity -- larger window => more events included.
    """
    from unifi_manager.utils.time import is_within_window, now_utc

    event_ts = now_utc() - timedelta(hours=hours - offset_hours)
    if is_within_window(event_ts, hours=hours):
        assert is_within_window(event_ts, hours=hours + 1)
