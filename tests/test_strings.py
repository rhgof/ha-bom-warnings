"""strings.json is what Home Assistant translates from, so a silent loss there is invisible."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from custom_components.bom_warnings.const import OTHER_WARNINGS, WARNING_TYPE_SENSORS
from custom_components.bom_warnings.fire_danger import LEVEL_KEYS
from custom_components.bom_warnings.sensor import LEVEL_OPTIONS

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
    # The per-type sensors take their translation key from WARNING_TYPE_SENSORS, not a literal.


@pytest.mark.parametrize("key", ["fire_danger_today", "fire_danger_tomorrow"])
def test_fire_danger_translates_every_enum_option(key: str) -> None:
    assert set(load(STRINGS)["entity"]["sensor"][key]["state"]) == set(LEVEL_KEYS)


@pytest.mark.parametrize("key", [key for _, key in WARNING_TYPE_SENSORS])
def test_every_warning_type_sensor_is_named_and_translates_every_level(key: str) -> None:
    sensor = load(STRINGS)["entity"]["sensor"][key]
    assert sensor["name"].strip()
    assert set(sensor["state"]) == set(LEVEL_OPTIONS)
    assert all(text.strip() for text in sensor["state"].values())
    # The type sensors are level sensors now; no binary sensor of that name may linger.
    assert key not in load(STRINGS)["entity"]["binary_sensor"]


@pytest.mark.parametrize(
    "key",
    ["hide_final_cancelled", *[key for _, key in WARNING_TYPE_SENSORS], OTHER_WARNINGS],
)
def test_every_toggle_on_the_options_form_has_a_label(key: str) -> None:
    assert load(STRINGS)["options"]["step"]["init"]["data"][key].strip()


@pytest.mark.parametrize("field", ["title", "description"])
def test_the_options_form_explains_what_on_and_off_mean(field: str) -> None:
    text = load(STRINGS)["options"]["step"]["init"][field]
    assert text.strip()
    if field == "description":
        assert "on" in text and "off" in text


def test_the_old_filter_and_coastal_waters_switch_are_gone_from_the_forms() -> None:
    strings = load(STRINGS)
    assert set(strings["options"]["step"]["init"]["data"]) == {
        "hide_final_cancelled",
        *[key for _, key in WARNING_TYPE_SENSORS],
        OTHER_WARNINGS,
    }
    assert "include_marine" not in strings["config"]["step"]["zone"]["data"]
