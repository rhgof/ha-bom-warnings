"""The strength class of a marine wind warning, read from its headline.

CAP severity has only two levels for marine wind (a gale and a strong wind are both Moderate), so
the class is named only in the headline. BoM's spatial data guide lists the classes for the Marine
Wind Warning severity: small craft alert, strong wind, gale, storm force and hurricane force wind.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.cap import parse_cap
from custom_components.bom_warnings.strength import wind_strength
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import setup_entry
from .test_options import layers, resolve  # noqa: F401
from .test_zones import set_zone, zone_codes, zone_entry, zone_options  # noqa: F401

pytestmark = pytest.mark.freeze_time(NOW)

FIXTURES = Path(__file__).parent / "fixtures"
WIND_SENSOR = "sensor.holiday_house_marine_wind_warning"


def recorded_headlines(path: str) -> list[str]:
    warning = parse_cap((FIXTURES / path).read_bytes())
    assert warning is not None
    return [info.headline for info in warning.infos]


# IDD20105 holds a storm, a storm, a gale and a strong wind block, in that order.
SAMPLE = recorded_headlines("cap_samples/IDD20105.cap.xml")


@pytest.mark.parametrize(
    ("headline", "strength"),
    [
        (SAMPLE[0], "storm"),
        (SAMPLE[1], "storm"),
        (SAMPLE[2], "gale"),
        (SAMPLE[3], "strong"),
        (recorded_headlines("cap/IDT20100.cap.xml")[0], "strong"),
        (recorded_headlines("cap/IDW20100.cap.xml")[0], "strong"),
        # The class names in BoM's guide; the exact headline wording is not in a recorded file.
        ("Hurricane Force Wind Warning for coastal waters between A and B", "hurricane"),
        ("strong wind warning for coastal waters between A and B", "strong"),
    ],
    ids=["storm", "storm-2", "gale", "strong", "tas-strong", "wa-strong", "hurricane", "lowercase"],
)
def test_the_class_is_read_from_the_headline(headline: str, strength: str) -> None:
    assert wind_strength("Wind", headline) == strength


@pytest.mark.parametrize(
    ("headline", "expected"),
    [
        (recorded_headlines("cap/IDN20400.cap.xml")[0], None),
        ("Final Wind Warning for coastal waters between A and B", "Final"),
        ("Small Craft Alert Wind Warning for coastal waters between A and B", "Small Craft Alert"),
        ("Wind Warning for coastal waters between A and B", None),
        ("", None),
    ],
    ids=["cancellation", "unknown-wording", "small-craft", "no-class", "empty"],
)
def test_wording_that_is_not_a_known_class(headline: str, expected: str | None) -> None:
    """A cancellation has no strength; wording this code does not know keeps its class text."""
    assert wind_strength("Wind", headline) == expected


@pytest.mark.parametrize(
    "event",
    ["Large Coastal Surf", "Weather", "Thunderstorm", "Tropical Cyclone"],
)
def test_other_events_never_have_a_strength(event: str) -> None:
    assert wind_strength(event, SAMPLE[0]) is None


@pytest.fixture(autouse=True)
def all_types(fake_bom: FakeBom) -> None:
    scenarios.apply("all_types", fake_bom.root)


# The water zones a circle can reach in the NT sample, and the class warned there.
@pytest.mark.parametrize(
    ("zone_codes", "strength"),
    [(["NT_PW999", "NT_MW002"], "gale"), (["NT_PW999", "NT_MW004"], "storm")],
    ids=["gale", "storm"],
)
async def test_marine_wind_sensor_and_lists_carry_the_strength(
    hass: HomeAssistant,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
    zone_codes: list[str],  # noqa: F811
    strength: str,
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    sensor = hass.states.get(WIND_SENSOR)
    assert sensor is not None
    # The top warning decides the attribute. The gale zone also lies in the strong wind block, so
    # its list holds both, and every entry has a class.
    assert sensor.attributes["strength"] == strength
    assert strength in {w["strength"] for w in sensor.attributes["warnings"]}
    assert {w["strength"] for w in sensor.attributes["warnings"]} <= {"strong", "gale", "storm"}

    # The same warning in the lists shared by the other sensors carries it too.
    for entity_id in (
        "binary_sensor.holiday_house_warning",
        "sensor.holiday_house_warning_count",
        "sensor.holiday_house_most_severe_warning",
    ):
        state = hass.states.get(entity_id)
        assert state is not None
        winds = [w for w in state.attributes["warnings"] if w["event"] == "Wind"]
        assert winds, entity_id
        assert strength in {w["strength"] for w in winds}
        assert all(w["strength"] in {"strong", "gale", "storm"} for w in winds)


async def test_marine_wind_strength_is_none_when_nothing_is_warned(
    hass: HomeAssistant,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    """A water zone with no wind warning: the sensor is `none` and has no strength."""
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    sensor = hass.states.get(WIND_SENSOR)
    assert sensor is not None
    assert sensor.state == "none"
    assert sensor.attributes["strength"] is None


@pytest.mark.parametrize(
    ("entity_id", "event"),
    [
        ("sensor.holiday_house_hazardous_surf_warning", "Large Coastal Surf"),
        ("sensor.holiday_house_severe_weather_warning", "Weather"),
        ("sensor.holiday_house_thunderstorm_warning", "Thunderstorm"),
    ],
)
async def test_other_sensors_do_not_gain_a_strength(
    hass: HomeAssistant,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
    entity_id: str,
    event: str,
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    state = hass.states.get(entity_id)
    assert state is not None
    attributes: dict[str, Any] = dict(state.attributes)
    assert "strength" not in attributes
    assert all("strength" not in w for w in attributes["warnings"])
