"""strings.json is what Home Assistant translates from, so a silent loss there is invisible."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from custom_components.bom_warnings.active_warnings import LEVEL_OPTIONS
from custom_components.bom_warnings.fire_danger import LEVEL_KEYS
from custom_components.bom_warnings.warning_types import WarningType, sensor_types

COMPONENT = Path(__file__).parent.parent / "custom_components" / "bom_warnings"
STRINGS = COMPONENT / "strings.json"
ENGLISH = COMPONENT / "translations" / "en.json"


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    duplicates = {key for key in keys if keys.count(key) > 1}
    assert not duplicates, f"duplicate keys: {sorted(duplicates)}"
    return dict(pairs)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(), object_pairs_hook=_no_duplicates)


@pytest.mark.parametrize("path", [STRINGS, ENGLISH], ids=lambda p: p.name)
def test_no_duplicate_keys(path: Path) -> None:
    load(path)


def test_translations_match_strings() -> None:
    assert load(ENGLISH) == load(STRINGS)


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("issues", "refresh_failing"),
        ("issues", "no_area"),
        ("issues", "zone_removed"),
        ("issues", "radius_clamped"),
        ("entity.binary_sensor", "warning"),
        ("entity.event", "warning_event"),
        ("entity.sensor", "warning_count"),
        ("entity.sensor", "most_severe_warning"),
        ("entity.sensor", "fire_danger_today"),
        ("entity.sensor", "fire_danger_tomorrow"),
    ],
)
def test_every_translation_key_used_in_code_exists(section: str, key: str) -> None:
    node: Any = load(STRINGS)
    for part in section.split("."):
        node = node[part]
    assert key in node


def test_translation_keys_in_code_are_all_listed_above() -> None:
    """Guards the list above: a new translation_key in code must be added to it."""
    used: set[str] = set()
    for source in COMPONENT.glob("*.py"):
        used |= set(re.findall(r'translation_key\s*=\s*"(\w+)"', source.read_text()))
    assert used == {
        "refresh_failing",
        "no_area",
        "zone_removed",
        "radius_clamped",
        "warning",
        "warning_event",
        "warning_count",
        "most_severe_warning",
    }
    # The per-type sensors take their translation key from the warning type table, not a literal.


@pytest.mark.parametrize("key", ["fire_danger_today", "fire_danger_tomorrow"])
def test_fire_danger_translates_every_enum_option(key: str) -> None:
    assert set(load(STRINGS)["entity"]["sensor"][key]["state"]) == set(LEVEL_KEYS)


@pytest.mark.parametrize("warning_type", sensor_types(), ids=lambda t: t.key)
def test_every_warning_type_sensor_is_named_and_translates_every_level(
    warning_type: WarningType,
) -> None:
    key = warning_type.key
    sensor = load(STRINGS)["entity"]["sensor"][key]
    assert sensor["name"] == warning_type.sensor_name
    assert set(sensor["state"]) == set(LEVEL_OPTIONS)
    assert all(text.strip() for text in sensor["state"].values())
    # The type sensors are level sensors now; no binary sensor of that name may linger.
    assert key not in load(STRINGS)["entity"]["binary_sensor"]


@pytest.mark.parametrize("field", ["hide_final_cancelled", "warning_types"])
def test_every_field_on_the_options_form_has_a_label_and_help(field: str) -> None:
    step = load(STRINGS)["options"]["step"]["init"]
    assert step["data"][field].strip()
    assert step["data_description"][field].strip()


@pytest.mark.parametrize("field", ["title", "description"])
def test_the_options_form_explains_what_on_and_off_mean(field: str) -> None:
    text = load(STRINGS)["options"]["step"]["init"][field]
    assert text.strip()
    if field == "description":
        assert "on" in text and "off" in text


def test_the_options_form_is_two_fields() -> None:
    strings = load(STRINGS)
    assert set(strings["options"]["step"]["init"]["data"]) == {
        "hide_final_cancelled",
        "warning_types",
    }
    assert "include_marine" not in strings["config"]["step"]["zone"]["data"]


# The names BoM uses for its own products, so a person who knows the Bureau's wording finds them.
# Event names such as "Extreme Heat" are CAP vocabulary, and "extreme" would read as a level.
BOM_SENSOR_NAMES = {
    "thunderstorm_warning": "Severe thunderstorm warning",
    "fire_weather_warning": "Fire weather warning",
    "extreme_heat_warning": "Heatwave warning",
    "frost_warning": "Frost warning",
    "hazardous_road_conditions_warning": "Road weather alert",
    "flood_warning": "Flood warning",
    "sheep_grazier_warning": "Warning to sheep graziers",
    "exposure_warning": "Exposure warning",
    "tropical_cyclone_warning": "Tropical cyclone warning",
    "severe_weather_warning": "Severe weather warning",
    "marine_wind_warning": "Marine wind warning",
    "hazardous_surf_warning": "Hazardous surf warning",
}


def test_the_sensor_names_are_the_bureaus_product_names() -> None:
    names = {key: sensor["name"] for key, sensor in load(STRINGS)["entity"]["sensor"].items()}

    assert {key: names[key] for key in BOM_SENSOR_NAMES} == BOM_SENSOR_NAMES
    assert {t.key: t.sensor_name for t in sensor_types()} == BOM_SENSOR_NAMES
