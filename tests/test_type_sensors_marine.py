"""The per-type sensors for marine wind and hazardous surf, from BoM's real samples.

Coastal-water warnings only reach an entry whose area codes include a water zone (`MW`), and only
count while their type is on in the options checklist. The zone entry stands in for a circle that
reached the water: its codes are what the circle resolved to.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
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
from .test_binary_sensor import setup_entry
from .test_options import layers, resolve, set_options  # noqa: F401
from .test_strings import STRINGS, load
from .test_zones import ZONE, set_zone, zone_codes, zone_entry, zone_options  # noqa: F401

pytestmark = pytest.mark.freeze_time(NOW)

WIND = "binary_sensor.holiday_house_marine_wind_warning"
SURF = "binary_sensor.holiday_house_hazardous_surf_warning"

# Event, translation key, name, sample product, the water-zone codes a circle can reach, and the
# severity of the warning there. IDD20105 has a gale (Moderate) and a storm (Severe) block.
MARINE_TYPES = [
    (
        "Wind",
        "marine_wind_warning",
        "Marine wind warning",
        "IDD20105",
        ["NT_PW999", "NT_MW002"],
        "moderate",
    ),
    (
        "Wind",
        "marine_wind_warning",
        "Marine wind warning",
        "IDD20105",
        ["NT_PW999", "NT_MW004"],
        "severe",
    ),
    (
        "Large Coastal Surf",
        "hazardous_surf_warning",
        "Hazardous surf warning",
        "IDN28522",
        ["NSW_PW999", "NSW_MW008"],
        "moderate",
    ),
    (
        "Large Coastal Surf",
        "hazardous_surf_warning",
        "Hazardous surf warning",
        "IDN28522",
        ["NSW_PW999", "NSW_MW007"],
        "moderate",
    ),
]
IDS = [f"{codes[1]}-{event}" for event, _, _, _, codes, _ in MARINE_TYPES]


@pytest.fixture(autouse=True)
def all_types(fake_bom: FakeBom) -> None:
    scenarios.apply("all_types", fake_bom.root)


def entity(key: str) -> str:
    return f"binary_sensor.holiday_house_{key}"


@pytest.mark.parametrize(
    ("event", "key", "name"),
    [
        ("Wind", "marine_wind_warning", "Marine wind warning"),
        ("Large Coastal Surf", "hazardous_surf_warning", "Hazardous surf warning"),
    ],
    ids=["wind", "surf"],
)
def test_the_marine_types_are_in_the_table_with_a_clear_name(
    event: str, key: str, name: str
) -> None:
    assert (event, key) in WARNING_TYPE_SENSORS
    assert event in EVENT_ICONS
    assert load(STRINGS)["entity"]["binary_sensor"][key]["name"] == name


@pytest.mark.parametrize(
    ("event", "key", "_name", "product_id", "zone_codes", "severity"), MARINE_TYPES, ids=IDS
)
async def test_marine_sensor_follows_its_toggle_without_re_resolving(
    hass: HomeAssistant,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
    event: str,
    key: str,
    _name: str,
    product_id: str,
    zone_codes: list[str],  # noqa: F811
    severity: str,
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)
    # The warning is in the feed and the circle reaches the water, and the type is on.
    state = hass.states.get(entity(key))
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes["severity"] == severity
    assert {(w["product_id"], w["event"]) for w in state.attributes["warnings"]} == {
        (product_id, event)
    }
    assert state.attributes["icon"] == EVENT_ICONS[event]

    await set_options(hass, zone_entry, **{key: False})
    # Off removes the sensor; the stored area codes are untouched, so nothing is looked up again.
    assert er.async_get(hass).async_get(entity(key)) is None
    resolve.assert_not_called()

    await set_options(hass, zone_entry, **{key: True})
    assert hass.states.get(entity(key)).state == STATE_ON  # type: ignore[union-attr]
    resolve.assert_not_called()


@pytest.mark.parametrize("zone_codes", [["NSW_PW999", "NSW_MW008", "NT_MW004"]])
async def test_wind_and_surf_sensors_are_each_on_only_for_their_own_type(
    hass: HomeAssistant,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    for entity_id, product_id in ((WIND, "IDD20105"), (SURF, "IDN28522")):
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == STATE_ON
        assert {w["product_id"] for w in state.attributes["warnings"]} == {product_id}


@pytest.mark.parametrize("zone_codes", [["NSW_PW999", "NSW_MW008"]])
async def test_a_water_zone_without_a_wind_warning_leaves_the_wind_sensor_off(
    hass: HomeAssistant,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    state = hass.states.get(WIND)
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes["severity"] is None


@pytest.mark.parametrize("zone_codes", [["NT_PW999", "NT_MW004", "NSW_MW008"]])
async def test_only_the_marine_wind_sensor_says_wind_here_means_marine_wind(
    hass: HomeAssistant,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    """BoM's Wind event is marine wind: land damaging winds arrive as the Severe weather type."""
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    note = (hass.states.get(WIND).attributes.get("note") or "").lower()  # type: ignore[union-attr]
    assert "marine" in note
    assert "severe weather" in note
    assert "note" not in hass.states.get(SURF).attributes  # type: ignore[union-attr]
