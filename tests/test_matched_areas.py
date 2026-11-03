"""Which areas an entry matched: names on warnings, and the covered list on the count sensor.

Driven through Home Assistant against the fake BoM server. The names are stored on the entry, so
the shapefiles are not involved here; the resolver's part is tested in test_location.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import CONF_AREA_CODES, CONF_AREA_NAMES
from custom_components.bom_warnings.location import LocationUnavailable
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .locations import location_of
from .test_binary_sensor import ENTITY_ID, poll, setup_entry
from .test_options import layers  # noqa: F401
from .test_sensor import COUNT, MOST_SEVERE, state_of

pytestmark = pytest.mark.freeze_time(NOW)

THUNDERSTORM = "sensor.home_thunderstorm_warning"
# The recorded thunderstorm warning covers QLD_ME008 and nothing else of these.
HOME_AND_NEIGHBOUR = ["QLD_ME008", "QLD_PW001"]
NAMES = {"QLD_ME008": "Brisbane", "QLD_PW001": "Moreton Bay"}


def before_names(entry: MockConfigEntry) -> MockConfigEntry:
    """The same entry as an older version stored it: no names key at all."""
    return MockConfigEntry(
        domain=entry.domain,
        version=entry.version,
        unique_id=entry.unique_id,
        title=entry.title,
        options=dict(entry.options),
        data={k: v for k, v in entry.data.items() if k != CONF_AREA_NAMES},
    )


@pytest.mark.parametrize("area_codes", [HOME_AND_NEIGHBOUR])
@pytest.mark.parametrize("entry_area_names", [NAMES])
async def test_the_count_sensor_lists_the_areas_the_entry_covers(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    # In code order, whatever order the entry stored them in.
    assert state_of(hass, COUNT).attributes["areas"] == ["Brisbane", "Moreton Bay"]


@pytest.mark.parametrize("area_codes", [["QLD_PW001"]])
@pytest.mark.parametrize("entry_area_names", [{"QLD_PW001": "Moreton Bay"}])
async def test_the_list_shows_with_no_warning_active(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    assert state_of(hass, COUNT).state == "0"
    assert state_of(hass, COUNT).attributes["areas"] == ["Moreton Bay"]


async def test_an_entry_with_no_names_lists_none(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    assert state_of(hass, COUNT).attributes["areas"] == []


@pytest.mark.parametrize("area_codes", [HOME_AND_NEIGHBOUR])
@pytest.mark.parametrize("entry_area_names", [{"QLD_ME008": "Brisbane", "QLD_PW001": "Brisbane"}])
async def test_areas_with_the_same_name_are_listed_once(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    assert state_of(hass, COUNT).attributes["areas"] == ["Brisbane"]


@pytest.mark.parametrize("area_codes", [HOME_AND_NEIGHBOUR])
@pytest.mark.parametrize("entry_area_names", [NAMES])
@pytest.mark.parametrize("entity_id", [ENTITY_ID, COUNT, MOST_SEVERE, THUNDERSTORM])
async def test_every_warning_list_names_the_area_the_warning_matched(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, entity_id: str
) -> None:
    await setup_entry(hass, mock_config_entry)

    (item,) = state_of(hass, entity_id).attributes["warnings"]
    # The warning covers the home district only, not the neighbour the radius also reaches.
    assert item["area"] == "Brisbane"


@pytest.mark.parametrize("area_codes", [HOME_AND_NEIGHBOUR])
@pytest.mark.parametrize("entry_area_names", [NAMES])
async def test_the_top_warning_fields_include_its_area(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    assert state_of(hass, MOST_SEVERE).attributes["area"] == "Brisbane"


@pytest.mark.parametrize("area_codes", [["QLD_ME008"]])
@pytest.mark.parametrize("entry_area_names", [{}, {"QLD_ME008": ""}, {"QLD_PW001": "Moreton Bay"}])
async def test_a_warning_whose_matched_area_has_no_name_has_no_area(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    (item,) = state_of(hass, COUNT).attributes["warnings"]
    assert "area" not in item


async def test_an_entry_from_before_names_were_stored_learns_them_once(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
    freezer: Any,
) -> None:
    entry = before_names(mock_config_entry)
    resolve.return_value = location_of("QLD_PW001", names={"QLD_PW001": "Moreton Bay"})

    await setup_entry(hass, entry)

    assert resolve.call_count == 1
    assert entry.data[CONF_AREA_NAMES] == {"QLD_PW001": "Moreton Bay"}
    assert state_of(hass, COUNT).attributes["areas"] == ["Moreton Bay"]
    # Learned, so it does not look again.
    await poll(hass, freezer)
    assert resolve.call_count == 1


async def test_a_failed_first_lookup_is_retried_and_the_entry_still_works(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
    freezer: Any,
) -> None:
    entry = before_names(mock_config_entry)
    resolve.side_effect = LocationUnavailable("offline")

    await setup_entry(hass, entry)
    assert CONF_AREA_NAMES not in entry.data
    assert state_of(hass, COUNT).state == "0"
    assert entry.data[CONF_AREA_CODES] == ["QLD_PW001"]

    resolve.side_effect = None
    resolve.return_value = location_of("QLD_PW001", names={"QLD_PW001": "Moreton Bay"})
    await poll(hass, freezer)

    assert entry.data[CONF_AREA_NAMES] == {"QLD_PW001": "Moreton Bay"}
