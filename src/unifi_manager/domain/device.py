"""Доменные модели сетевых устройств UniFi.

ВАЖНО: SYSID_MAP перенесён из infra/external_repos/.../diagnostics/infra_deep_v2.py
(где он был единственной точкой определения, не в основной репе).
UniFi API для некоторых старых моделей возвращает в поле "model" короткое
неправильное имя (U7IW вместо UAP-AC-IW). real_model даёт каноническое имя.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, computed_field

# Seed dictionary — extended sysid → canonical model name mapping.
# Source: tnware/unifi-controller-api auto_model_mapping (D32).
# Наши 4 override entries (UAP-AC-*) перечислены отдельно для clarity.
_SYSID_SEED: Final[dict[int, str]] = {
    # UAP-AC series (legacy)
    58759: "UAP-AC-IW",  # our override (was U7IW in reported model)
    58679: "UAP-AC-Pro",  # our override (was U7PG2)
    58727: "UAP-AC-M",  # our override (was U7MP)
    58711: "UAP-AC-M-Pro",  # our override (was U7MSH)
    # U6 series (WiFi 6)
    62482: "U6-Lite",
    62483: "U6-LR",
    62484: "U6-Pro",
    62485: "U6-Mesh",
    62486: "U6-Enterprise",
    # U7 / WiFi 7 series
    65001: "U7-Pro",
    65002: "U7-Pro-Max",
    # Switches (basic seed)
    32001: "US-24-250W",
    32002: "US-48-500W",
}

SYSID_MAP: Final[dict[int, str]] = dict(_SYSID_SEED)


# D32 refinement (2026-05-18): sysid_gap warning для self-enriching карты.
# Лог one-time per unknown sysid, без spam (set guard).
_WARNED_SYSIDS: set[int] = set()
_sysid_logger = logging.getLogger(__name__)


def lookup_real_model(reported_model: str, sysid: int | None) -> str:
    """Каноническое имя модели через SYSID_MAP с fallback на reported.

    При lookup unknown sysid — log warning ОДНОГО раза.
    """
    if sysid is None:
        return reported_model
    if sysid in SYSID_MAP:
        return SYSID_MAP[sysid]
    if sysid not in _WARNED_SYSIDS:
        _WARNED_SYSIDS.add(sysid)
        _sysid_logger.warning(
            "sysid_gap: sysid=%d not in SYSID_MAP, falling back to reported_model=%r",
            sysid,
            reported_model,
            extra={"sysid": sysid, "reported_model": reported_model, "category": "sysid_gap"},
        )
    return reported_model


class UplinkInfo(BaseModel):
    """Информация об uplink-подключении устройства к upstream-свитчу."""

    model_config = ConfigDict(extra="allow")

    uplink_mac: str | None = None
    uplink_remote_port: int | None = None


class Device(BaseModel):
    """Базовая модель сетевого устройства UniFi (общее поле для AP и Switch)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    mac: str
    name: str | None = None
    reported_model: str = Field(alias="model")
    sysid: int | None = None
    state: int = 0  # 1=online, 0=offline, 10=connection_interrupted, etc.
    type: str | None = None  # "uap" | "usw" | "ugw" | ...
    last_seen: int | None = None  # unix timestamp
    device_id: str | None = Field(default=None, alias="_id")


class AccessPoint(Device):
    """Wi-Fi точка доступа с обогащением real_model через SYSID_MAP."""

    uplink: UplinkInfo | None = None
    radio_table: list[dict[str, Any]] = Field(default_factory=list)

    @computed_field  # type: ignore  # pydantic computed_field stacked on @property
    @property
    def real_model(self) -> str:
        """Каноническое имя модели через lookup_real_model (включая sysid_gap warning)."""
        return lookup_real_model(self.reported_model, self.sysid)


class SwitchPort(BaseModel):
    """Порт коммутатора с метриками ошибок (для Phase 7 port-errors monitoring)."""

    model_config = ConfigDict(extra="allow")

    port_idx: int
    rx_errors: int = 0
    tx_errors: int = 0
    rx_dropped: int = 0
    tx_dropped: int = 0


class Switch(Device):
    """Коммутатор UniFi с port_table и метриками температуры/PoE."""

    general_temperature: int | None = None
    port_table: list[SwitchPort] = Field(default_factory=list)
