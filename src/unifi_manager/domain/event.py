"""AP UniFi events.

Used by RestartService to analyze EVT_AP_Lost_Contact frequency
in a 24-hour window to decide on restart.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from unifi_manager.utils.time import parse_unifi_utc


class EventKey(StrEnum):
    """Known UniFi event keys (extend as needed).

    Unknown API keys are preserved as raw strings (via str | EventKey union).
    """

    AP_LOST_CONTACT = "EVT_AP_Lost_Contact"
    AP_DISCONNECTED = "EVT_AP_Disconnected"
    AP_CONNECTED = "EVT_AP_Connected"


def _parse_event_key(v: str) -> EventKey | str:
    """Parser: known key -> EventKey enum, otherwise raw string (forward compat)."""
    try:
        return EventKey(v)
    except ValueError:
        return v


def _parse_timestamp(v: str | datetime) -> datetime:
    """Parser: UniFi format 'YYYY-MM-DDTHH:MM:SSZ' -> tz-aware UTC datetime."""
    if isinstance(v, datetime):
        return v
    return parse_unifi_utc(v)


class ApEvent(BaseModel):
    """AP event from /stat/event."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    key: Annotated[EventKey | str, BeforeValidator(_parse_event_key)]
    timestamp: Annotated[datetime, BeforeValidator(_parse_timestamp)] = Field(alias="datetime")
    ap_mac: str = Field(alias="ap")
    ap_name: str | None = None
    msg: str | None = None
