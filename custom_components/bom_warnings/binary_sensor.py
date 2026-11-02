"""Binary sensor: on while a current warning covers the entry's location."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BomWarningsConfigEntry
from .const import DOMAIN
from .coordinator import ActiveWarning, BomWarningsCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BomWarningsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([WarningActiveBinarySensor(entry.runtime_data.coordinator, entry)])


def _attributes(warning: ActiveWarning) -> dict[str, Any]:
    return {
        "product_id": warning.product_id,
        "event": warning.event,
        "headline": warning.headline,
        "severity": str(warning.severity),
        "effective": warning.effective.isoformat() if warning.effective else None,
        "expires": warning.expires.isoformat() if warning.expires else None,
    }


class WarningActiveBinarySensor(CoordinatorEntity[BomWarningsCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "warning"
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, coordinator: BomWarningsCoordinator, entry: BomWarningsConfigEntry) -> None:
        super().__init__(coordinator)
        unique_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{unique_id}_warning"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"warnings": [_attributes(w) for w in self.coordinator.data]}
