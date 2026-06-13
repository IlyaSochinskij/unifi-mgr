"""Timezone-aware time utilities.

KRITICHNO: fix timezone-baga iz audita.
Staryy kod sravnival tz-naive datetime.now() s UTC vremenem UniFi API,
chto na servere v UTC+3 (Sochi) davalo sdvig okna na 3 chasa.

Vse funktsii zdes vozvrashchayut i rabotayut s tz-aware datetime v UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def parse_unifi_utc(ts_str: str) -> datetime:
    """Parses timestamp in UniFi format ('2026-05-15T22:00:00Z') into tz-aware UTC datetime.

    Args:
        ts_str: ISO-like string ending with 'Z' (UTC marker).

    Raises:
        ValueError: if string is empty, does not match format, or is invalid.
        TypeError: if non-str is passed.
    """
    if not isinstance(ts_str, str):
        raise TypeError(f"expected str, got {type(ts_str).__name__}")
    if not ts_str.strip():
        raise ValueError("empty timestamp string")
    # 'Z' -> '+00:00' for fromisoformat
    normalized = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def now_utc() -> datetime:
    """Current time in UTC (tz-aware).

    Unlike datetime.now() (local), always returns UTC.
    """
    return datetime.now(UTC)


def is_within_window(event_ts: datetime, *, hours: float) -> bool:
    """True if event occurred within last `hours` hours from now_utc().

    Args:
        event_ts: tz-aware datetime of event (usually from parse_unifi_utc).
        hours: window size in hours (positive number).

    Raises:
        ValueError: if event_ts is naive (no tzinfo) -- cannot compare
                    with UTC safely.
    """
    if event_ts.tzinfo is None:
        raise ValueError("event_ts must be tz-aware datetime (parsed via parse_unifi_utc)")
    cutoff = now_utc() - timedelta(hours=hours)
    return event_ts > cutoff
