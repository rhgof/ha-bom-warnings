"""Every BoM warning type through Home Assistant, from real samples on the fake server.

The `all_types` scenario shifts the samples' dates to the moment it is applied, so with time
frozen they are all current. Each type is matched by the first PW/ME/FW code in its file.
"""

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    CONF_AREA_CODES,
    CONF_EVENT_TYPES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_STATE,
    DOMAIN,
    KNOWN_EVENT_TYPES,
)
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import ENTITY_ID, setup_entry
from .test_options import layers, set_options  # noqa: F401

pytestmark = pytest.mark.freeze_time(NOW)

MOST_SEVERE = "sensor.home_most_severe_warning"


@pytest.fixture(autouse=True)
def all_types(fake_bom: FakeBom) -> None:
    scenarios.apply("all_types", fake_bom.root)


def entry_at(code: str) -> MockConfigEntry:
    """A location whose only area code is `code`; the state comes from its prefix."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="-27.470,153.021",
        title="Home",
        data={
            CONF_LATITUDE: -27.47,
            CONF_LONGITUDE: 153.021,
            CONF_STATE: code.split("_")[0],
            CONF_AREA_CODES: [code],
        },
    )


def pairs(hass: HomeAssistant, entity_id: str) -> set[tuple[str, str]]:
    state = hass.states.get(entity_id)
    assert state is not None
    return {(w["product_id"], w["event"]) for w in state.attributes["warnings"]}


# product id, event, first PW/ME/FW code in the file (state prefix included).
MATCHABLE = [
    ("IDT38200", "Exposure", "TAS_PW008"),
    ("IDQ21137", "Weather", "QLD_PW015"),
    ("IDN22000", "Fire Weather", "NSW_FW015"),
    ("IDV23000", "Frost", "VIC_PW004"),
    ("IDQ21013", "Extreme Heat", "QLD_PW002"),
    ("IDS20240", "Hazardous Road Conditions", "SA_ME003"),
    ("IDQ21033", "Thunderstorm", "QLD_PW001"),
    ("IDN21037", "Weather", "NSW_PW006"),
    ("IDT29000", "Sheep Grazier Warning", "TAS_PW010"),
    ("IDDIDD24500", "Tropical Cyclone", "NT_PW002"),
]


@pytest.mark.parametrize(
    ("product_id", "event", "code"),
    MATCHABLE,
    ids=[f"{event}-{product}" for product, event, _ in MATCHABLE],
)
async def test_location_in_the_warned_area_turns_the_binary_sensor_on(
    hass: HomeAssistant, product_id: str, event: str, code: str
) -> None:
    await setup_entry(hass, entry_at(code))

    assert hass.states.get(ENTITY_ID).state == STATE_ON  # type: ignore[union-attr]
    assert (product_id, event) in pairs(hass, ENTITY_ID)


# Warnings in coastal-water (MW) or tsunami (TW) zones are never matched to a land location,
# so the binary sensor stays off; the state-wide sensors still see them, except the tsunami
# whose file name is not listed by `*.cap.xml` (known gap).
STATE_ONLY = [
    ("IDN28522", "Large Coastal Surf", "NSW_PW999", True),
    ("IDD20105", "Wind", "NT_PW999", True),
    ("IDY68027", "Tsunami", "QLD_PW999", False),
]


@pytest.mark.parametrize(
    ("product_id", "event", "code", "seen_by_state"),
    STATE_ONLY,
    ids=[event for _, event, _, _ in STATE_ONLY],
)
async def test_water_zone_warning_leaves_the_binary_sensor_off(
    hass: HomeAssistant, product_id: str, event: str, code: str, seen_by_state: bool
) -> None:
    await setup_entry(hass, entry_at(code))

    assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]
    assert ((product_id, event) in pairs(hass, MOST_SEVERE)) is seen_by_state


async def test_event_type_filter_keeps_a_thunderstorm_warning(
    hass: HomeAssistant,
    layers: object,  # noqa: F811
) -> None:
    entry = entry_at("QLD_PW002")
    await setup_entry(hass, entry)
    assert {event for _, event in pairs(hass, ENTITY_ID)} == {"Extreme Heat", "Thunderstorm"}

    await set_options(hass, entry, **{CONF_EVENT_TYPES: ["Thunderstorm"]})

    assert {event for _, event in pairs(hass, ENTITY_ID)} == {"Thunderstorm"}


def test_severe_thunderstorm_is_not_offered_as_an_event_type() -> None:
    assert "Severe Thunderstorm" not in KNOWN_EVENT_TYPES
    assert "Thunderstorm" in KNOWN_EVENT_TYPES
