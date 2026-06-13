"""Тесты для unifi_manager.domain.event."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.mark.fast()
def test_event_key_enum_values() -> None:
    from unifi_manager.domain.event import EventKey

    assert EventKey.AP_LOST_CONTACT.value == "EVT_AP_Lost_Contact"
    assert EventKey.AP_DISCONNECTED.value == "EVT_AP_Disconnected"
    assert EventKey.AP_CONNECTED.value == "EVT_AP_Connected"


@pytest.mark.fast()
def test_ap_event_basic_parse() -> None:
    from unifi_manager.domain.event import ApEvent, EventKey

    evt = ApEvent.model_validate(
        {
            "key": "EVT_AP_Lost_Contact",
            "datetime": "2026-05-15T22:00:00Z",
            "ap": "aa:bb:cc:dd:ee:01",
            "ap_name": "Restoran",
        }
    )
    assert evt.key == EventKey.AP_LOST_CONTACT
    assert evt.timestamp == datetime(2026, 5, 15, 22, 0, 0, tzinfo=UTC)
    assert evt.ap_mac == "aa:bb:cc:dd:ee:01"
    assert evt.ap_name == "Restoran"


@pytest.mark.fast()
def test_ap_event_timestamp_is_tz_aware() -> None:
    """ApEvent.timestamp всегда tz-aware (фикс audit-бага)."""
    from unifi_manager.domain.event import ApEvent

    evt = ApEvent.model_validate(
        {
            "key": "EVT_AP_Lost_Contact",
            "datetime": "2026-05-15T22:00:00Z",
            "ap": "aa:bb:cc:dd:ee:01",
        }
    )
    assert evt.timestamp.tzinfo is not None


@pytest.mark.fast()
def test_ap_event_unknown_key_preserved_as_string() -> None:
    """Если UniFi выдаёт новый event key — не падаем, сохраняем raw строку."""
    from unifi_manager.domain.event import ApEvent

    evt = ApEvent.model_validate(
        {
            "key": "EVT_SOME_NEW_EVENT",
            "datetime": "2026-05-15T22:00:00Z",
            "ap": "aa:bb:cc:dd:ee:01",
        }
    )
    # key либо EventKey enum, либо raw string (Literal или str union)
    assert evt.key == "EVT_SOME_NEW_EVENT" or str(evt.key) == "EVT_SOME_NEW_EVENT"


@pytest.mark.fast()
def test_ap_event_optional_ap_name() -> None:
    from unifi_manager.domain.event import ApEvent

    evt = ApEvent.model_validate(
        {
            "key": "EVT_AP_Disconnected",
            "datetime": "2026-05-15T23:00:00Z",
            "ap": "aa:bb:cc:dd:ee:01",
        }
    )
    assert evt.ap_name is None


@pytest.mark.fast()
def test_full_event_response_parses(fixtures_dir: Path) -> None:
    from unifi_manager.domain.event import ApEvent

    raw = json.loads((fixtures_dir / "ap_event_sample.json").read_text(encoding="utf-8"))
    events = [ApEvent.model_validate(e) for e in raw["data"]]
    assert len(events) == 3
    assert events[0].ap_name == "Restoran"
    assert events[2].ap_name is None
