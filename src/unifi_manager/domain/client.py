"""Wireless network clients (used by the export command)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WirelessClient(BaseModel):
    """Connected Wi-Fi client."""

    model_config = ConfigDict(extra="allow")

    mac: str
    hostname: str | None = None
    ip: str | None = None
    ap_mac: str | None = None  # MAC of AP the client is connected to
    signal: int | None = None  # dBm, usually negative
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    first_seen: int | None = None
    last_seen: int | None = None
