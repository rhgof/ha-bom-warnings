"""Sensors: number of current warnings in the state and the most severe one."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BomWarningsConfigEntry
from .cap import Severity
from .const import DOMAIN
from .coordinator import ActiveWarning, BomWarningsCoordinator

PARALLEL_UPDATES = 0

# Declared order is the severity order: unknown < minor < moderate < severe < extreme.
_RANK = {severity: rank for rank, severity in enumerate(Severity)}
_EPOCH = datetime.min.replace(tzinfo=UTC)

STATE_NONE = "none"


def most_severe(warnings: Iterable[ActiveWarning]) -> ActiveWarning | None:
    """The highest severity; ties go to the most recently issued."""
    return max(
        warnings,
        key=lambda w: (_RANK.get(w.severity, 0), w.sent or _EPOCH),
        default=None,
    )


def _attributes(warning: ActiveWarning) -> dict[str, Any]:
    return {
        "product_id": warning.product_id,
        "event": warning.event,
        "headline": warning.headline,
        "severity": str(warning.severity),
        "sent": warning.sent.isoformat() if warning.sent else None,
        "effective": warning.effective.isoformat() if warning.effective else None,
        "expires": warning.expires.isoformat() if warning.expires else None,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BomWarningsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [WarningCountSensor(coordinator, entry), MostSevereWarningSensor(coordinator, entry)]
    )


class _WarningSensor(CoordinatorEntity[BomWarningsCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: BomWarningsCoordinator, entry: BomWarningsConfigEntry) -> None:
        super().__init__(coordinator)
        unique_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{unique_id}_{self._attr_translation_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )


class WarningCountSensor(_WarningSensor):
    _attr_translation_key = "warning_count"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        return len(self.coordinator.state_warnings)


class MostSevereWarningSensor(_WarningSensor):
    _attr_translation_key = "most_severe_warning"

    @property
    def native_value(self) -> str:
        warning = most_severe(self.coordinator.state_warnings)
        return warning.headline if warning else STATE_NONE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        warnings = self.coordinator.state_warnings
        top = most_severe(warnings)
        return {**(_attributes(top) if top else {}), "warnings": [_attributes(w) for w in warnings]}
