"""ExportService — CSV/JSON выгрузка clients и devices.

Devices экспортируются через AccessPoint / Switch модели — это значит
real_model (computed_field SYSID_MAP) попадает в output (regression-prone
по audit fix).

Безопасность: по умолчанию export_devices применяет allow-list безопасных
колонок (секреты вырезаны). raw=True даёт сырой UniFi payload — опасно.
"""

from __future__ import annotations

import csv
import json
from typing import IO, Any, Literal, Protocol

from unifi_manager.domain.client import WirelessClient
from unifi_manager.domain.device import AccessPoint, Switch
from unifi_manager.utils.redact import is_secret_key, redact_secrets

Format = Literal["csv", "json"]

# Безопасные для шаринга колонки (typed-поля моделей + полезные raw inventory-поля).
_SAFE_DEVICE_FIELDS: frozenset[str] = frozenset(
    {
        "mac",
        "name",
        "reported_model",
        "real_model",
        "sysid",
        "state",
        "type",
        "last_seen",
        "device_id",
        "ip",
        "version",
        "adopted",
        "uptime",
        "num_sta",
        "general_temperature",
        "site_id",
        "uplink",
    }
)


def _safe_row(row: dict[str, Any]) -> dict[str, Any]:
    """Allow-list по top-level колонкам + рекурсивная вырезка секретов внутри значений.

    Top-level: остаются только колонки из _SAFE_DEVICE_FIELDS (и не похожие на секрет).
    Вложенно: redact_secrets режет секретные ключи внутри (например в uplink) — SEC8.
    """
    return {
        k: redact_secrets(v)
        for k, v in row.items()
        if k in _SAFE_DEVICE_FIELDS and not is_secret_key(k)
    }


class _DeviceClient(Protocol):
    def list_devices_raw(self) -> list[dict[str, Any]]: ...
    def list_clients_raw(self) -> list[dict[str, Any]]: ...


class ExportService:
    """Экспорт типизированных данных в CSV или JSON."""

    def __init__(self, legacy_client: _DeviceClient) -> None:
        self.client = legacy_client

    def export_clients(self, *, output: IO[str], fmt: Format) -> None:
        """Выгрузить всех клиентов site."""
        clients = [
            WirelessClient.model_validate(c).model_dump(mode="json")
            for c in self.client.list_clients_raw()
        ]
        self._write(output, clients, fmt)

    def export_devices(self, *, output: IO[str], fmt: Format, raw: bool = False) -> None:
        """Выгрузить все устройства.

        raw=False (default): только allow-list безопасных колонок (секреты вырезаны).
        raw=True: сырой payload UniFi целиком — ОПАСНО (содержит x_authkey и т.п.).
        """
        rows: list[dict[str, Any]] = []
        for raw_dev in self.client.list_devices_raw():
            device_type = raw_dev.get("type")
            if device_type == "uap":
                rows.append(AccessPoint.model_validate(raw_dev).model_dump(mode="json"))
            elif device_type == "usw":
                rows.append(Switch.model_validate(raw_dev).model_dump(mode="json"))
            else:
                rows.append(raw_dev)
        if not raw:
            rows = [_safe_row(r) for r in rows]
        self._write(output, rows, fmt)

    @staticmethod
    def _write(output: IO[str], rows: list[dict[str, Any]], fmt: Format) -> None:
        if fmt == "json":
            json.dump(rows, output, ensure_ascii=False, indent=2, default=str)
        elif fmt == "csv":
            if not rows:
                return  # empty CSV — no header to write
            # Объединяем все ключи для полного header (некоторые device могут не иметь полей)
            fieldnames: list[str] = []
            seen: set[str] = set()
            for row in rows:
                for k in row:
                    if k not in seen:
                        seen.add(k)
                        fieldnames.append(k)
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _stringify(v) for k, v in row.items()})
        else:
            raise ValueError(f"unsupported format: {fmt!r}")


def _stringify(value: Any) -> str:
    """Преобразовать значение для CSV cell (lists/dicts → JSON string)."""
    if isinstance(value, list | dict):
        return json.dumps(value, ensure_ascii=False, default=str)
    if value is None:
        return ""
    return str(value)
