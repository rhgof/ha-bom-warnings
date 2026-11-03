"""The warning types, and which of them a location cares about: the options checklist.

No Home Assistant imports. One row of `WARNING_TYPES` per type; the sensors, the checklist and its
labels, and the migration of old options all derive from it, so a new type is a new row here plus
its name in strings.json. The checklist is a set of keys, one per row plus OTHER_WARNINGS for
events with no row. Every other place asks `event_is_on`.

The views are functions that read the table when called, so a test makes a type disappear by
patching `WARNING_TYPES` alone.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_EVENT_TYPES,
    CONF_INCLUDE_MARINE,
    CONF_WARNING_TYPES,
    OTHER_WARNINGS,
)


@dataclass(frozen=True, slots=True)
class WarningType:
    # The CAP `<event>` this type is.
    event: str
    # The type sensor's translation key, and the name of its toggle in the options checklist.
    key: str
    # The words the checklist shows. Given with each choice instead of looked up in the
    # translations, because the options dialog does not always load a selector's translations and
    # then shows the raw key.
    label: str
    # The marine rows only ever match a location whose area codes reach a coastal water zone.
    marine: bool = False


# In the order the options form lists them and the sensors are created.
WARNING_TYPES = (
    WarningType("Thunderstorm", "thunderstorm_warning", "Thunderstorm"),
    WarningType("Fire Weather", "fire_weather_warning", "Fire weather"),
    WarningType("Extreme Heat", "extreme_heat_warning", "Extreme heat"),
    WarningType("Frost", "frost_warning", "Frost"),
    WarningType(
        "Hazardous Road Conditions",
        "hazardous_road_conditions_warning",
        "Hazardous road conditions",
    ),
    WarningType("Riverine Flood", "flood_warning", "Flood"),
    WarningType("Sheep Grazier Warning", "sheep_grazier_warning", "Sheep grazier"),
    WarningType("Exposure", "exposure_warning", "Exposure"),
    WarningType("Tropical Cyclone", "tropical_cyclone_warning", "Tropical cyclone"),
    WarningType("Weather", "severe_weather_warning", "Severe weather"),
    WarningType("Wind", "marine_wind_warning", "Marine wind", marine=True),
    WarningType("Large Coastal Surf", "hazardous_surf_warning", "Hazardous surf", marine=True),
)

_OTHER_LABEL = "Other warnings"


def sensor_types() -> tuple[WarningType, ...]:
    """The types with a level sensor and a checklist toggle."""
    return WARNING_TYPES


def label_of(key: str) -> str:
    if key == OTHER_WARNINGS:
        return _OTHER_LABEL
    for warning_type in sensor_types():
        if warning_type.key == key:
            return warning_type.label
    raise KeyError(key)


def type_keys() -> tuple[str, ...]:
    """Every toggle, in the order the options form lists them."""
    return (*(t.key for t in sensor_types()), OTHER_WARNINGS)


def key_of(event: str) -> str:
    for warning_type in sensor_types():
        if warning_type.event == event:
            return warning_type.key
    return OTHER_WARNINGS


def enabled_keys(options: Mapping[str, Any]) -> frozenset[str]:
    """The types that are on; with no stored choice, all of them."""
    stored = options.get(CONF_WARNING_TYPES)
    if stored is None:
        return frozenset(type_keys())
    return frozenset(stored) & frozenset(type_keys())


def event_is_on(event: str, enabled: frozenset[str]) -> bool:
    return key_of(event) in enabled


def keys_from_legacy_options(options: Mapping[str, Any]) -> list[str]:
    """The checklist that reproduces what an entry from before it showed.

    An empty event-type filter meant every type; a filter with names meant only those, and a name
    with no row now means "Other warnings". Coastal waters counted only with `include_marine`.
    """
    named = options.get(CONF_EVENT_TYPES) or []
    wanted = {key_of(event) for event in named} if named else set(type_keys())
    if not options.get(CONF_INCLUDE_MARINE, False):
        wanted -= {t.key for t in sensor_types() if t.marine}
    return [key for key in type_keys() if key in wanted]
