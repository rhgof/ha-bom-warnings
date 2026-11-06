"""The warning types, and which of them a location cares about: the options checklist.

No Home Assistant imports. One row of `WARNING_TYPES` per type; the sensors, the checklist and its
labels, and the migration of old options all derive from it, so a new type is a new row here plus
its name in strings.json. The checklist is a set of keys, one per row plus OTHER_WARNINGS for
events with no row. Every other place asks `event_is_on`.

The views are functions that read the table when called, so a test makes a type disappear by
patching `WARNING_TYPES` alone.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_EVENT_TYPES,
    CONF_INCLUDE_MARINE,
    CONF_WARNING_TYPES,
    OTHER_WARNINGS,
)

# The marine wind strength class, read from the headline.
_CLASSES = {
    "strong": "strong",
    "gale force": "gale",
    "gale": "gale",
    "storm force": "storm",
    "storm": "storm",
    "hurricane force": "hurricane",
    "hurricane": "hurricane",
}
_HEADLINE = re.compile(r"^(?P<class>.+?)\s+wind\s+warning\b", re.IGNORECASE)

# The product XML's severity code for a marine wind hazard. Only these two have been seen (NSW
# product IDN20400, 4 Nov 2026); a storm or hurricane code is unconfirmed, so those classes still
# come from the headline.
XML_WIND_STRENGTHS = {"STR": "strong", "GALE": "gale"}


def wind_strength(headline: str) -> str | None:
    """The strength class of a Wind warning's headline, or None.

    Known classes are lowercase and stable (`strong`, `gale`, `storm`, `hurricane`). Wording this
    code does not know keeps its class text as written, so a new class is shown and not lost. A
    cancellation and a headline with no class have no strength.
    """
    match = _HEADLINE.match(headline.strip())
    if match is None:
        return None
    text = match.group("class").strip()
    if text.lower().startswith("cancellation"):
        return None
    return _CLASSES.get(text.lower(), text)


@dataclass(frozen=True, slots=True)
class WarningType:
    """A CAP event BoM is known to send."""

    # The CAP `<event>`.
    event: str
    icon: str
    # An entity has no description field, so a type that is easy to misread says so in a `note`
    # attribute.
    note: str | None = None
    # Reads a class out of a warning's headline, for the one type that names its strength there.
    strength: Callable[[str], str | None] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SensorType(WarningType):
    """An event with a level sensor and a toggle in the options checklist."""

    # The sensor's translation key, and the name of its toggle in the options checklist.
    key: str
    # The words the checklist shows. Given with each choice instead of looked up in the
    # translations, because the options dialog does not always load a selector's translations and
    # then shows the raw key.
    label: str
    # The sensor's name where it is not just the label and "warning", for a product BoM calls an
    # alert or words differently. It must match the name in `strings.json`, which a test checks.
    name: str | None = None
    # The marine rows only ever match a location whose area codes reach a coastal water zone.
    marine: bool = False

    @property
    def sensor_name(self) -> str:
        return self.name or f"{self.label} warning"


# BoM's Wind event is marine wind, which is not wind at the house. Its Weather event is both the
# Severe Weather Warning and the Coastal Hazard Warning, and which of the two a warning is can only
# be told from its headline, so it is no automation trigger.
_WIND_NOTE = (
    "Marine wind only: BoM's Wind event is for coastal and local waters, not wind at "
    "your house. Damaging winds on land arrive as the Severe weather warning."
)
_WEATHER_NOTE = (
    "For display. BoM's Weather event covers both Severe Weather Warnings and Coastal"
    " Hazard Warnings, so it is not a good automation trigger."
)

# In the order the options form lists them and the sensors are created, then the events that have
# an icon but no sensor.
WARNING_TYPES: tuple[WarningType, ...] = (
    SensorType(
        "Thunderstorm",
        "mdi:weather-lightning-rainy",
        key="thunderstorm_warning",
        label="Severe thunderstorm",
    ),
    SensorType("Fire Weather", "mdi:fire-alert", key="fire_weather_warning", label="Fire weather"),
    # BoM's product is the Heatwave Warning. "Extreme Heat" is only the CAP event, and "extreme"
    # in a name reads as a level beside a sensor whose state may be `severe`.
    SensorType(
        "Extreme Heat", "mdi:thermometer-alert", key="extreme_heat_warning", label="Heatwave"
    ),
    SensorType("Frost", "mdi:snowflake-alert", key="frost_warning", label="Frost"),
    SensorType(
        "Hazardous Road Conditions",
        "mdi:car-brake-alert",
        key="hazardous_road_conditions_warning",
        label="Road weather",
        name="Road weather alert",
    ),
    SensorType("Riverine Flood", "mdi:home-flood", key="flood_warning", label="Flood"),
    SensorType(
        "Sheep Grazier Warning",
        "mdi:sheep",
        key="sheep_grazier_warning",
        label="Sheep graziers",
        name="Warning to sheep graziers",
    ),
    SensorType("Exposure", "mdi:snowflake-thermometer", key="exposure_warning", label="Exposure"),
    SensorType(
        "Tropical Cyclone",
        "mdi:weather-hurricane",
        key="tropical_cyclone_warning",
        label="Tropical cyclone",
    ),
    SensorType(
        "Weather",
        "mdi:cloud-alert",
        key="severe_weather_warning",
        label="Severe weather",
        note=_WEATHER_NOTE,
    ),
    SensorType(
        "Wind",
        "mdi:weather-windy",
        key="marine_wind_warning",
        label="Marine wind",
        note=_WIND_NOTE,
        strength=wind_strength,
        marine=True,
    ),
    SensorType(
        "Large Coastal Surf",
        "mdi:waves-arrow-up",
        key="hazardous_surf_warning",
        label="Hazardous surf",
        marine=True,
    ),
    # No zones yet (#25), so no sensor or toggle: it falls under "Other warnings".
    WarningType("Tsunami", "mdi:tsunami"),
)

_OTHER_LABEL = "Other warnings"


def sensor_types() -> tuple[SensorType, ...]:
    """The types with a level sensor and a checklist toggle."""
    return tuple(t for t in WARNING_TYPES if isinstance(t, SensorType))


def type_of(event: str) -> WarningType | None:
    """The row for a CAP event, or None for an event BoM has not sent before."""
    return next((t for t in WARNING_TYPES if t.event == event), None)


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
