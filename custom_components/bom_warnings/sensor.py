"""Sensors: the warnings covering the location, ranked, and the most severe one."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import MAX_LENGTH_STATE_STATE as MAX_STATE_LENGTH
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BomWarningsConfigEntry
from .const import DEFAULT_EVENT_ICON, DOMAIN, EVENT_ICONS, LEVEL_COLORS, NO_WARNING_ICON
from .coordinator import ActiveWarning, BomWarningsCoordinator

PARALLEL_UPDATES = 0

# Dict order is the ranking order, lowest first: minor < moderate < unknown < severe < extreme.
_LEVEL_RANK = {level: rank for rank, level in enumerate(LEVEL_COLORS)}
_EPOCH = datetime.min.replace(tzinfo=UTC)

STATE_NONE = "none"


def _level(warning: ActiveWarning) -> str:
    return warning.severity.value


def _icon(warning: ActiveWarning) -> str:
    return EVENT_ICONS.get(warning.event, DEFAULT_EVENT_ICON)


def rank_warnings(warnings: Iterable[ActiveWarning]) -> list[ActiveWarning]:
    """Most severe first; ties go to the most recently issued, undated last, then product id."""
    return sorted(
        warnings,
        key=lambda w: (
            -_LEVEL_RANK[_level(w)],
            w.sent is None,
            -(w.sent or _EPOCH).timestamp(),
            w.product_id,
        ),
    )


def _current_then_ended(warnings: Iterable[ActiveWarning]) -> list[ActiveWarning]:
    ranked = rank_warnings(warnings)
    return [w for w in ranked if w.is_current] + [w for w in ranked if not w.is_current]


def _item(warning: ActiveWarning) -> dict[str, Any]:
    level = _level(warning)
    return {
        "product_id": warning.product_id,
        "event": warning.event,
        "severity": str(warning.severity),
        "level": level,
        "icon": _icon(warning),
        "color": LEVEL_COLORS[level],
        "headline": warning.headline,
        "phase": str(warning.phase),
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

    @property
    def _ranked(self) -> list[ActiveWarning]:
        return _current_then_ended(self.coordinator.data)

    @property
    def _top(self) -> ActiveWarning | None:
        return next((w for w in self._ranked if w.is_current), None)

    @property
    def icon(self) -> str:
        top = self._top
        return _icon(top) if top else NO_WARNING_ICON


class WarningCountSensor(_WarningSensor):
    _attr_translation_key = "warning_count"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        return sum(w.is_current for w in self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"warnings": [_item(w) for w in self._ranked]}


class MostSevereWarningSensor(_WarningSensor):
    _attr_translation_key = "most_severe_warning"

    @property
    def native_value(self) -> str:
        top = self._top
        if top is None:
            return STATE_NONE
        # Home Assistant turns a state over 255 characters into "unknown"; some real headlines
        # list a dozen districts. The full text stays in the `headline` attribute.
        headline = top.headline
        if len(headline) > MAX_STATE_LENGTH:
            return headline[: MAX_STATE_LENGTH - 1] + "…"
        return headline

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        top = self._top
        return {**(_item(top) if top else {}), "warnings": [_item(w) for w in self._ranked]}
