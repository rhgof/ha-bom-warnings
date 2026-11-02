"""The per-type binary sensors for the land warning types, from BoM's real samples.

The `all_types` scenario serves one real sample of every type with its dates shifted to now, on top
of the baseline (which holds a recorded flood warning). Each type is matched by a code in its file.
"""

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    EVENT_ICONS,
    WARNING_TYPE_SENSORS,
)
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import ENTITY_ID as ANY_WARNING
from .test_binary_sensor import poll, setup_entry
from .test_strings import STRINGS, load
from .test_warning_types import entry_at

pytestmark = pytest.mark.freeze_time(NOW)

# CAP event, translation key, name, a sample product that covers it, and one of its area codes.
LAND_TYPES = [
    ("Fire Weather", "fire_weather_warning", "Fire weather warning", "IDN22000", "NSW_FW015"),
    ("Extreme Heat", "extreme_heat_warning", "Extreme heat warning", "IDQ21013", "QLD_PW002"),
    ("Frost", "frost_warning", "Frost warning", "IDV23000", "VIC_PW004"),
    (
        "Hazardous Road Conditions",
        "hazardous_road_conditions_warning",
        "Hazardous road conditions warning",
        "IDS20240",
        "SA_ME003",
    ),
    ("Riverine Flood", "flood_warning", "Flood warning", "IDN36631", "NSW_RC031"),
    (
        "Sheep Grazier Warning",
        "sheep_grazier_warning",
        "Sheep grazier warning",
        "IDT29000",
        "TAS_PW010",
    ),
    ("Exposure", "exposure_warning", "Exposure warning", "IDT38200", "TAS_PW008"),
    (
        "Tropical Cyclone",
        "tropical_cyclone_warning",
        "Tropical cyclone warning",
        "IDD24500",
        "NT_PW002",
    ),
    ("Weather", "severe_weather_warning", "Severe weather warning", "IDN21037", "NSW_PW006"),
]
LAND_IDS = [event for event, *_ in LAND_TYPES]
SEVERITIES = {"minor", "moderate", "unrated", "severe", "extreme"}


@pytest.fixture(autouse=True)
def all_types(fake_bom: FakeBom) -> None:
    scenarios.apply("all_types", fake_bom.root)


def sensor_id(key: str) -> str:
    return f"sensor.home_{key}"


def table_entity_ids() -> list[str]:
    return [sensor_id(key) for _, key in WARNING_TYPE_SENSORS]


def test_the_table_has_a_row_for_every_land_and_marine_type_and_thunderstorm() -> None:
    events = {event for event, _ in WARNING_TYPE_SENSORS}
    assert events == {*LAND_IDS, "Thunderstorm", "Wind", "Large Coastal Surf"}
    # Tsunami has no zones yet (#25).
    assert "Tsunami" not in events


def test_every_row_has_a_distinct_key_a_name_and_an_icon() -> None:
    names = load(STRINGS)["entity"]["sensor"]
    keys = [key for _, key in WARNING_TYPE_SENSORS]
    assert len(set(keys)) == len(keys)
    for event, key in WARNING_TYPE_SENSORS:
        assert names[key]["name"].strip(), key
        assert event in EVENT_ICONS, event
    assert len({names[key]["name"] for key in keys}) == len(keys)


@pytest.mark.parametrize(
    ("event", "key", "name"),
    [(event, key, name) for event, key, name, _, _ in LAND_TYPES],
    ids=LAND_IDS,
)
def test_each_land_type_is_named_for_what_it_is(event: str, key: str, name: str) -> None:
    assert (event, key) in WARNING_TYPE_SENSORS
    assert load(STRINGS)["entity"]["sensor"][key]["name"] == name


async def test_every_sensor_is_created_enabled_and_the_state_count_is_bounded(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    before = len(hass.states.async_all())
    await setup_entry(hass, mock_config_entry)

    registry = er.async_get(hass)
    for entity_id in table_entity_ids():
        entry = registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert entry.disabled_by is None
        assert hass.states.get(entity_id) is not None
    # Twelve type sensors, plus the warning, count, most severe and event entities (the fire
    # danger sensors need a state in the NSW product).
    assert len(WARNING_TYPE_SENSORS) == 12
    assert len(hass.states.async_all()) - before <= 12 + 6


@pytest.mark.parametrize(
    ("event", "key", "product_id", "code"),
    [(event, key, product, code) for event, key, _, product, code in LAND_TYPES],
    ids=LAND_IDS,
)
async def test_each_type_turns_on_for_a_warning_of_its_type(
    hass: HomeAssistant, event: str, key: str, product_id: str, code: str
) -> None:
    await setup_entry(hass, entry_at(code))

    state = hass.states.get(sensor_id(key))
    assert state is not None
    assert state.state in SEVERITIES
    assert state.attributes["event"] == event
    assert state.attributes["product_id"] == product_id
    listed = {(w["product_id"], w["event"]) for w in state.attributes["warnings"]}
    assert (product_id, event) in listed
    assert {e for _, e in listed} == {event}
    assert state.attributes["icon"] == EVENT_ICONS[event]


@pytest.mark.parametrize(
    ("event", "code"),
    [(event, code) for event, _, _, _, code in LAND_TYPES],
    ids=LAND_IDS,
)
async def test_a_sensor_is_on_exactly_when_a_warning_of_its_type_covers_the_location(
    hass: HomeAssistant, freezer: Any, event: str, code: str
) -> None:
    """The sensors agree with the list: a warning of another type never turns one on."""
    await setup_entry(hass, entry_at(code))

    listed = hass.states.get(ANY_WARNING)
    assert listed is not None
    covering = {w["event"] for w in listed.attributes["warnings"]}
    assert event in covering
    for row_event, key in WARNING_TYPE_SENSORS:
        state = hass.states.get(sensor_id(key))
        assert state is not None, key
        assert (state.state != "none") == (row_event in covering), key


async def test_all_sensors_are_off_where_nothing_is_warned(
    hass: HomeAssistant, freezer: Any
) -> None:
    await setup_entry(hass, entry_at("NSW_PW999"))

    for entity_id in table_entity_ids():
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state == "none"
        assert state.attributes["headline"] is None
        assert state.attributes["warnings"] == []


async def test_only_weather_and_marine_wind_carry_a_note(hass: HomeAssistant, freezer: Any) -> None:
    """The Weather event is also BoM's Coastal Hazard Warning, so it is no automation trigger.

    Marine wind has its own note (tests/test_type_sensors_marine.py): Wind is not wind at the house.
    """
    await setup_entry(hass, entry_at("NSW_PW006"))

    notes = {
        key: hass.states.get(sensor_id(key)).attributes.get("note")  # type: ignore[union-attr]
        for _, key in WARNING_TYPE_SENSORS
    }
    assert "display" in (notes["severe_weather_warning"] or "").lower()
    assert "automation" in (notes["severe_weather_warning"] or "").lower()
    assert all(
        note is None
        for key, note in notes.items()
        if key not in {"severe_weather_warning", "marine_wind_warning"}
    )


@pytest.mark.parametrize("area_codes", [["NSW_PW999", "NSW_MW008"]])
async def test_an_event_without_a_row_has_no_sensor_but_is_still_listed(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A type with no row (surf here, as if it were new) is in the list, count and event entity."""
    without_surf = tuple(row for row in WARNING_TYPE_SENSORS if row[0] != "Large Coastal Surf")
    monkeypatch.setattr("custom_components.bom_warnings.sensor.WARNING_TYPE_SENSORS", without_surf)
    monkeypatch.setattr(
        "custom_components.bom_warnings.coordinator.WARNING_TYPE_SENSORS", without_surf
    )
    scenarios.apply("baseline", fake_bom.root)
    await setup_entry(hass, mock_config_entry)

    # The event entity fires on a change, so the surf warning arrives after the entry has loaded.
    scenarios.apply("all_types", fake_bom.root)
    await poll(hass, freezer)

    registry = er.async_get(hass)
    assert [e.entity_id for e in registry.entities.values() if "surf" in e.entity_id] == []
    for _, key in without_surf:
        entity_id = sensor_id(key)
        assert hass.states.get(entity_id).state == "none"  # type: ignore[union-attr]
    listed = hass.states.get(ANY_WARNING)
    assert listed is not None
    assert "Large Coastal Surf" in {w["event"] for w in listed.attributes["warnings"]}
    assert hass.states.get("sensor.home_warning_count").state != "0"  # type: ignore[union-attr]
    assert "Large Coastal Surf" in {
        w["event"]
        for w in hass.states.get("sensor.home_most_severe_warning").attributes["warnings"]  # type: ignore[union-attr]
    }
    event = hass.states.get("event.home_warning_event")
    assert event is not None
    assert event.attributes.get("event") == "Large Coastal Surf"
