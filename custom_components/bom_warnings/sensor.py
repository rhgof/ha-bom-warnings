"""Sensors: the warnings covering the location, ranked, and the most severe one."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import MAX_LENGTH_STATE_STATE as MAX_STATE_LENGTH
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import BomWarningsConfigEntry
from .const import (
    DEFAULT_EVENT_ICON,
    DEFAULT_FIRE_DANGER_ICON,
    DOMAIN,
    EVENT_ICONS,
    FIRE_DANGER_COLORS,
    FIRE_DANGER_ICONS,
    LEVEL_COLORS,
    NO_WARNING_ICON,
)
from .coordinator import ActiveWarning, BomWarningsCoordinator, FireDangerView
from .fire_danger import LEVEL_KEYS, FireDangerPeriod

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

    # Fire danger entities exist only for an entry whose codes are in a fetched product. That
    # product may arrive after setup (the optional step failed or the file was missing), so keep
    # checking until it does; once added, a missing district only makes them unavailable.
    added = False

    @callback
    def _add_fire_danger() -> None:
        nonlocal added
        if added or coordinator.fire_danger is None:
            return
        added = True
        async_add_entities(
            [FireDangerSensor(coordinator, entry, offset) for offset in FIRE_DANGER_DAYS]
        )

    _add_fire_danger()
    if not added:
        entry.async_on_unload(coordinator.async_add_listener(_add_fire_danger))


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


# Translation key by day offset from the local date.
FIRE_DANGER_DAYS = {0: "fire_danger_today", 1: "fire_danger_tomorrow"}
FIRE_DANGER_ATTRIBUTION = "Australian Government Bureau of Meteorology"


def _period_item(period: FireDangerPeriod) -> dict[str, Any]:
    return {
        "date": period.date.isoformat(),
        "level": period.level,
        "fire_behaviour_index": period.fire_behaviour_index,
    }


class FireDangerSensor(_WarningSensor):
    """The fire danger rating of the entry's fire weather district for today or tomorrow."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(LEVEL_KEYS)
    _attr_attribution = FIRE_DANGER_ATTRIBUTION

    def __init__(
        self, coordinator: BomWarningsCoordinator, entry: BomWarningsConfigEntry, day_offset: int
    ) -> None:
        self._attr_translation_key = FIRE_DANGER_DAYS[day_offset]
        self._day_offset = day_offset
        super().__init__(coordinator, entry)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.fire_danger is not None

    @property
    def _view(self) -> FireDangerView | None:
        return self.coordinator.fire_danger

    @property
    def _period(self) -> FireDangerPeriod | None:
        view = self._view
        if view is None:
            return None
        day = view.local_date(dt_util.utcnow()) + timedelta(days=self._day_offset)
        return view.by_date.get(day)

    @property
    def _level(self) -> str | None:
        period = self._period
        return period.level if period else None

    @property
    def native_value(self) -> str | None:
        # An enum sensor must not report a state outside its options; the raw text is an attribute.
        return self._level if self._level in LEVEL_KEYS else None

    @property
    def icon(self) -> str:
        return FIRE_DANGER_ICONS.get(self._level or "", DEFAULT_FIRE_DANGER_ICON)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        view = self._view
        if view is None:
            return {}
        level = self._level
        return {
            "level": level,
            "color": FIRE_DANGER_COLORS.get(level or ""),
            "fire_behaviour_index": self._period.fire_behaviour_index if self._period else None,
            "forecast": [_period_item(p) for p in view.forecast],
            "issued": view.issued.isoformat() if view.issued else None,
            "district": view.district_name,
            "source": view.product_id,
        }
