"""AuditService — мониторинг и аналитика UniFi сети.

Методы:
- critical() — exit-code-friendly список критических проблем для cron
- status() — read-only inventory snapshot
- light() — MAC duplicates / spoofing / client distribution (Task 6)
- full() — глубокий аудит используя оба API (Task 7)
- trends() — анализ исторических отчётов за N дней (Task 7)
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from unifi_manager.domain.client import WirelessClient
from unifi_manager.domain.device import AccessPoint, Switch
from unifi_manager.settings import Settings

_logger = logging.getLogger(__name__)


class _DeviceClient(Protocol):
    """Минимальный интерфейс для LegacyClient (для type-checking тестов)."""

    def list_devices_raw(self) -> list[dict[str, Any]]: ...
    def list_clients_raw(self) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class AuditIssue:
    """Критическая проблема найденная audit critical."""

    issue_type: str  # "offline" | "high_temperature" | "high_poe" | ...
    device_mac: str
    device_name: str
    severity: str  # "critical" | "warning"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StatusSummary:
    """Inventory snapshot — для status команды."""

    total: int
    online: int
    offline: int
    by_type: dict[str, int]


@dataclass(frozen=True)
class DuplicateMAC:
    """Дубликат MAC — несколько клиентов с одинаковым MAC."""

    mac: str
    hostnames: list[str]


@dataclass(frozen=True)
class SpoofedMAC:
    """Locally-administered MAC — потенциальный spoof."""

    mac: str
    hostname: str | None
    ap_mac: str | None


@dataclass(frozen=True)
class LightAuditReport:
    """Результат audit light — MAC analysis + client distribution."""

    duplicate_macs: list[DuplicateMAC]
    locally_administered: list[SpoofedMAC]
    clients_per_ap: dict[str, int]


@dataclass(frozen=True)
class FullAuditReport:
    """Результат audit full — объединённые данные из обоих API."""

    devices: list[dict[str, Any]]


@dataclass(frozen=True)
class TrendsReport:
    """Результат audit trends — точки данных из исторических отчётов."""

    data_points: list[dict[str, Any]]  # каждый dict — отдельный day report


class AuditService:
    """Бизнес-логика аудита. НЕ делает HTTP сам — использует переданный client."""

    def __init__(
        self,
        *,
        settings: Settings,
        legacy_client: _DeviceClient | None = None,
        integration_client: _DeviceClient | None = None,
    ) -> None:
        self.client = legacy_client
        self.integration_client = integration_client
        self.settings = settings

    @property
    def _legacy(self) -> _DeviceClient:
        """Legacy-клиент для legacy-only методов; ошибка, если он не передан."""
        if self.client is None:
            raise RuntimeError("this audit operation requires the Legacy API client")
        return self.client

    def critical(self) -> list[AuditIssue]:
        """Найти критические проблемы (для cron + exit code 1 в Phase 4)."""
        issues: list[AuditIssue] = []
        thresholds = self.settings.thresholds

        for raw in self._legacy.list_devices_raw():
            device_type = raw.get("type")
            if device_type == "uap":
                try:
                    ap = AccessPoint.model_validate(raw)
                except Exception as e:
                    _logger.warning(
                        "audit critical: skipping unparseable device %s: %s", raw.get("mac"), e
                    )
                    continue
                issues.extend(self._check_device_state(ap.mac, ap.name, ap.state))
            elif device_type == "usw":
                try:
                    sw = Switch.model_validate(raw)
                except Exception as e:
                    _logger.warning(
                        "audit critical: skipping unparseable device %s: %s", raw.get("mac"), e
                    )
                    continue
                issues.extend(self._check_device_state(sw.mac, sw.name, sw.state))
                if (
                    sw.general_temperature is not None
                    and sw.general_temperature > thresholds.critical_temp_c
                ):
                    issues.append(
                        AuditIssue(
                            issue_type="high_temperature",
                            device_mac=sw.mac,
                            device_name=sw.name or sw.mac,
                            severity="critical",
                            context={
                                "temperature": sw.general_temperature,
                                "threshold": thresholds.critical_temp_c,
                            },
                        )
                    )

        return issues

    @staticmethod
    def _check_device_state(mac: str, name: str | None, state: int) -> list[AuditIssue]:
        if state == 1:  # online
            return []
        return [
            AuditIssue(
                issue_type="offline",
                device_mac=mac,
                device_name=name or mac,
                severity="critical",
                context={"state": state},
            )
        ]

    def status(self) -> StatusSummary:
        """Inventory snapshot — кратко для оператора."""
        devices = self._legacy.list_devices_raw()
        total = len(devices)
        online = sum(1 for d in devices if d.get("state") == 1)
        offline = total - online
        type_counts = Counter(d.get("type", "unknown") for d in devices)
        return StatusSummary(
            total=total,
            online=online,
            offline=offline,
            by_type=dict(type_counts),
        )

    def light(self) -> LightAuditReport:
        """MAC duplicates, locally-administered (spoof), client distribution."""
        clients_raw = self._legacy.list_clients_raw()

        # Parse all clients via Pydantic for type safety; один битый payload не валит команду.
        clients: list[WirelessClient] = []
        for raw_c in clients_raw:
            try:
                clients.append(WirelessClient.model_validate(raw_c))
            except Exception as e:
                _logger.warning(
                    "audit light: skipping unparseable client %s: %s", raw_c.get("mac"), e
                )

        # Duplicates
        mac_to_clients: dict[str, list[WirelessClient]] = {}
        for c in clients:
            mac_to_clients.setdefault(c.mac, []).append(c)
        duplicates = [
            DuplicateMAC(
                mac=mac,
                hostnames=[cl.hostname or "<no hostname>" for cl in cls],
            )
            for mac, cls in mac_to_clients.items()
            if len(cls) > 1
        ]

        # Locally administered (bit 0x02 в первом байте)
        spoofed = [
            SpoofedMAC(mac=c.mac, hostname=c.hostname, ap_mac=c.ap_mac)
            for c in clients
            if self._is_locally_administered(c.mac)
        ]

        # Clients per AP
        per_ap: dict[str, int] = {}
        for c in clients:
            if c.ap_mac:
                per_ap[c.ap_mac] = per_ap.get(c.ap_mac, 0) + 1

        return LightAuditReport(
            duplicate_macs=duplicates,
            locally_administered=spoofed,
            clients_per_ap=per_ap,
        )

    @staticmethod
    def _is_locally_administered(mac: str) -> bool:
        """True если первый байт MAC имеет bit 0x02 (locally administered)."""
        try:
            first_byte = int(mac.split(":")[0], 16)
            return bool(first_byte & 0x02)
        except (ValueError, IndexError):
            return False

    def full(self) -> FullAuditReport:
        """Глубокий аудит. Использует те API, чьи клиенты переданы: только Legacy,
        только Integration, или merge обоих.
        """
        legacy_devices = self.client.list_devices_raw() if self.client is not None else []
        integration_devices = (
            self.integration_client.list_devices_raw()
            if self.integration_client is not None
            else []
        )
        if self.client is not None and self.integration_client is not None:
            merged = self._merge_devices(legacy_devices, integration_devices)
            return FullAuditReport(devices=merged)
        return FullAuditReport(devices=legacy_devices or integration_devices)

    @staticmethod
    def _merge_devices(
        legacy: list[dict[str, Any]],
        integration: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge by mac: Legacy data + Integration data → один dict per device."""
        # Integration uses 'macAddress', Legacy uses 'mac'
        by_mac: dict[str, dict[str, Any]] = {}
        for d in legacy:
            mac = d.get("mac")
            if mac:
                by_mac[mac] = dict(d)
        for d in integration:
            mac = d.get("macAddress") or d.get("mac")
            if mac:
                if mac in by_mac:
                    # Add integration-specific fields (ipAddress, etc.)
                    for k, v in d.items():
                        if k not in by_mac[mac]:
                            by_mac[mac][k] = v
                else:
                    by_mac[mac] = dict(d)
        return list(by_mac.values())

    def trends(self, *, days: int = 7) -> TrendsReport:
        """Анализ исторических текстовых отчётов из paths.reports_dir."""
        reports_dir = self.settings.paths.reports_dir
        if not reports_dir.is_dir():
            return TrendsReport(data_points=[])

        data_points: list[dict[str, Any]] = []
        for report_file in sorted(reports_dir.glob("*.txt")):
            data_points.append(self._parse_report(report_file))

        # Простой crop по days (если файлов больше, берём последние days)
        return TrendsReport(data_points=data_points[-days:])

    @staticmethod
    def _parse_report(path: Path) -> dict[str, Any]:
        """Извлечь ключевые метрики из текстового отчёта (graceful — OSError только logged)."""
        result: dict[str, Any] = {"file": path.name}
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            import logging

            logging.getLogger(__name__).warning("Could not read report %s: %s", path, e)
            return result

        # "Total devices: 270" → result["total"] = 270
        for label, key in [
            ("Total devices", "total"),
            ("Online", "online"),
            ("Offline", "offline"),
            ("Critical issues", "critical_issues"),
        ]:
            match = re.search(rf"{label}:\s*(\d+)", text)
            if match:
                result[key] = int(match.group(1))

        # PoE percent
        poe_match = re.search(r"PoE total:.*?\(([\d.]+)%\)", text)
        if poe_match:
            result["poe_percent"] = float(poe_match.group(1))

        return result
