"""Which warning types a location cares about: the options checklist, as pure functions.

No Home Assistant imports. The checklist is a set of keys, one per row of WARNING_TYPE_SENSORS plus
OTHER_WARNINGS for events with no row. Every other place asks `event_is_on`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    CONF_EVENT_TYPES,
    CONF_INCLUDE_MARINE,
    CONF_WARNING_TYPES,
    OTHER_WARNINGS,
    WARNING_TYPE_SENSORS,
)

MARINE_EVENTS = frozenset({"Wind", "Large Coastal Surf"})

# The words the options checklist shows. Given with each choice instead of looked up in the
# translations, because the options dialog does not always load a selector's translations and then
# shows the raw key.
TYPE_LABELS = {
    "thunderstorm_warning": "Thunderstorm",
    "fire_weather_warning": "Fire weather",
    "extreme_heat_warning": "Extreme heat",
    "frost_warning": "Frost",
    "hazardous_road_conditions_warning": "Hazardous road conditions",
    "flood_warning": "Flood",
    "sheep_grazier_warning": "Sheep grazier",
    "exposure_warning": "Exposure",
    "tropical_cyclone_warning": "Tropical cyclone",
    "severe_weather_warning": "Severe weather",
    "marine_wind_warning": "Marine wind",
    "hazardous_surf_warning": "Hazardous surf",
    OTHER_WARNINGS: "Other warnings",
}


def type_keys() -> tuple[str, ...]:
    """Every toggle, in the order the options form lists them."""
    return (*(key for _, key in WARNING_TYPE_SENSORS), OTHER_WARNINGS)


def key_of(event: str) -> str:
    for known, key in WARNING_TYPE_SENSORS:
        if known == event:
            return key
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
        wanted -= {key for event, key in WARNING_TYPE_SENSORS if event in MARINE_EVENTS}
    return [key for key in type_keys() if key in wanted]
