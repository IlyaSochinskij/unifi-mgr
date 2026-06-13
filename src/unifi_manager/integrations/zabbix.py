"""Zabbix Low-Level Discovery (LLD) форматтер.

Output идёт в stdout как JSON, который Zabbix external check парсит и
автоматически создаёт хосты/триггеры на найденные устройства.

LLD формат: {"data": [{"{#KEY}": "value", ...}, ...]}
"""

from __future__ import annotations

import json

from unifi_manager.domain.device import Device


def format_lld(devices: list[Device]) -> dict[str, list[dict[str, str]]]:
    """Преобразовать список Device → LLD JSON для Zabbix.

    Для AP использует real_model (через SYSID_MAP), для других — reported_model.
    """
    entries: list[dict[str, str]] = []
    for device in devices:
        # real_model — computed_field на AccessPoint; на Switch его нет, fallback на reported_model
        model = getattr(device, "real_model", device.reported_model)
        entries.append(
            {
                "{#NAME}": device.name or device.mac,
                "{#MAC}": device.mac,
                "{#MODEL}": model,
                "{#TYPE}": device.type or "",
                "{#STATE}": str(device.state),
            }
        )
    return {"data": entries}


def format_lld_json(devices: list[Device]) -> str:
    """Convenience: format_lld + json.dumps for stdout."""
    return json.dumps(format_lld(devices), ensure_ascii=False)
