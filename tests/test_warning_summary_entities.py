"""The summary and the BoM attribution on the entities, with BoM's real samples.

The `all_types` scenario serves one real sample of every type with its dates shifted to now, on top
of a baseline that holds a recorded flood warning (`IDN36631`, NSW_RC031). The unit rules for the
summary itself are in `test_warning_summary.py`.
"""

import pytest
from homeassistant.core import HomeAssistant

from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import ENTITY_ID as WARNING_BINARY_SENSOR
from .test_binary_sensor import setup_entry
from .test_warning_types import entry_at

pytestmark = pytest.mark.freeze_time(NOW)

ATTRIBUTION = "Australian Government Bureau of Meteorology"
FLOOD_SUMMARY = (
    "The Warrego River at Barringun No. 2 is currently at 1.73 m and rising, below the minor "
    "flood level. The Warrego River at Barringun No. 2 may exceed the minor flood level (2.80 m) "
    "during Monday 02 November. A peak below the moderate level is expected later in the coming "
    "week."
)
COUNT = "sensor.home_warning_count"
MOST_SEVERE = "sensor.home_most_severe_warning"
FLOOD = "sensor.home_flood_warning"
MARINE_WIND = "sensor.home_marine_wind_warning"
EVENT = "event.home_warning_event"


@pytest.fixture(autouse=True)
def all_types(fake_bom: FakeBom) -> None:
    scenarios.apply("all_types", fake_bom.root)


async def test_a_flood_summary_is_in_every_list_and_at_the_top_of_the_sensors_that_show_one(
    hass: HomeAssistant,
) -> None:
    await setup_entry(hass, entry_at("NSW_RC031"))

    for entity_id in (COUNT, MOST_SEVERE, FLOOD, WARNING_BINARY_SENSOR):
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert [w["summary"] for w in state.attributes["warnings"]] == [FLOOD_SUMMARY], entity_id
    for entity_id in (MOST_SEVERE, FLOOD):
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.attributes["summary"] == FLOOD_SUMMARY, entity_id


async def test_the_count_sensor_and_binary_sensor_have_no_top_level_summary(
    hass: HomeAssistant,
) -> None:
    await setup_entry(hass, entry_at("NSW_RC031"))

    for entity_id in (COUNT, WARNING_BINARY_SENSOR):
        state = hass.states.get(entity_id)
        assert state is not None
        assert "summary" not in state.attributes, entity_id


async def test_a_marine_wind_warning_has_no_summary_because_its_file_has_no_description(
    hass: HomeAssistant,
) -> None:
    await setup_entry(hass, entry_at("NT_MW002"))

    state = hass.states.get(MARINE_WIND)
    assert state is not None
    assert state.attributes["warnings"]
    assert "summary" not in state.attributes
    assert all("summary" not in w for w in state.attributes["warnings"])


@pytest.mark.parametrize("entity_id", [COUNT, MOST_SEVERE, WARNING_BINARY_SENSOR, FLOOD])
async def test_every_warning_entity_carries_the_bom_attribution(
    hass: HomeAssistant, entity_id: str
) -> None:
    await setup_entry(hass, entry_at("NSW_RC031"))

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["attribution"] == ATTRIBUTION


async def test_the_event_entity_is_unchanged(hass: HomeAssistant) -> None:
    await setup_entry(hass, entry_at("NSW_RC031"))

    state = hass.states.get(EVENT)
    assert state is not None
    assert "attribution" not in state.attributes
