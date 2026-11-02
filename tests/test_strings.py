"""strings.json is what Home Assistant translates from, so a silent loss there is invisible."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from custom_components.bom_warnings.fire_danger import LEVEL_KEYS

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


@pytest.mark.parametrize("key", ["fire_danger_today", "fire_danger_tomorrow"])
def test_fire_danger_translates_every_enum_option(key: str) -> None:
    assert set(load(STRINGS)["entity"]["sensor"][key]["state"]) == set(LEVEL_KEYS)
