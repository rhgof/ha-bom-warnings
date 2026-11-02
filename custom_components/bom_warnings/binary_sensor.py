"""Binary sensor: on while a current warning covers the entry's location."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BomWarningsConfigEntry
from .const import (
    DEFAULT_EVENT_ICON,
    DOMAIN,
    EVENT_ICONS,
    WARNING_TYPE_NOTES,
    WARNING_TYPE_SENSORS,
)
from .coordinator import ActiveWarning, BomWarningsCoordinator
from .sensor import rank_warnings

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BomWarningsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    registry = er.async_get(hass)
    unique_id = entry.unique_id or entry.entry_id
    for _, key in WARNING_TYPE_SENSORS:
        if key not in coordinator.enabled_types and (
            entity_id := registry.async_get_entity_id("binary_sensor", DOMAIN, f"{unique_id}_{key}")
        ):
            # A type that is off has no sensor at all, not a disabled one, so the entity list
            # only shows what the location cares about. Turning it on again recreates it.
            registry.async_remove(entity_id)
    async_add_entities(
        [
            WarningActiveBinarySensor(coordinator, entry),
            *(
                WarningTypeBinarySensor(coordinator, entry, event, key)
                for event, key in WARNING_TYPE_SENSORS
                if key in coordinator.enabled_types
            ),
        ]
    )


def _attributes(warning: ActiveWarning) -> dict[str, Any]:
    return {
        "product_id": warning.product_id,
        "event": warning.event,
        "headline": warning.headline,
        "severity": str(warning.severity),
        "phase": str(warning.phase),
        "effective": warning.effective.isoformat() if warning.effective else None,
        "expires": warning.expires.isoformat() if warning.expires else None,
    }


def highest_severity(warnings: Iterable[ActiveWarning]) -> str | None:
    """The top level among the warnings still in force, by the ranking the list already uses."""
    current = rank_warnings(w for w in warnings if w.is_current)
    return current[0].severity.value if current else None


class _DeviceBinarySensor(CoordinatorEntity[BomWarningsCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(
        self, coordinator: BomWarningsCoordinator, entry: BomWarningsConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator)
        unique_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{unique_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )


class WarningTypeBinarySensor(_DeviceBinarySensor):
    """On while a current warning of one CAP event covers the location.

    Only created for a type that is on in the options checklist.
    """

    def __init__(
        self,
        coordinator: BomWarningsCoordinator,
        entry: BomWarningsConfigEntry,
        event: str,
        key: str,
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key
        self._event = event
        self._attr_icon = EVENT_ICONS.get(event, DEFAULT_EVENT_ICON)

    @property
    def _warnings(self) -> tuple[ActiveWarning, ...]:
        return self.coordinator.by_event.get(self._event, ())

    @property
    def is_on(self) -> bool:
        return any(w.is_current for w in self._warnings)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes: dict[str, Any] = {
            "severity": highest_severity(self._warnings),
            "warnings": [_attributes(w) for w in self._warnings],
        }
        if note := WARNING_TYPE_NOTES.get(self._event):
            attributes["note"] = note
        return attributes


class WarningActiveBinarySensor(_DeviceBinarySensor):
    _attr_translation_key = "warning"

    def __init__(self, coordinator: BomWarningsCoordinator, entry: BomWarningsConfigEntry) -> None:
        super().__init__(coordinator, entry, "warning")

    @property
    def is_on(self) -> bool:
        return any(w.is_current for w in self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"warnings": [_attributes(w) for w in self.coordinator.data]}
