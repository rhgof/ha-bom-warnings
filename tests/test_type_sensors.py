"""One binary sensor per warning type, driven through Home Assistant against the fake BoM server.

A type's sensor exists while the type is on in the options checklist, and a new entry has every
type on. Thunderstorm is the type most of these tests use; the table in const.py has a row per type.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.active_warnings import (
    LEVEL_OPTIONS,
    ActiveWarning,
    type_attributes,
)
from custom_components.bom_warnings.cap import Phase, Severity
from custom_components.bom_warnings.const import (
    CONF_HIDE_FINAL,
    CONF_WARNING_TYPES,
    LEVEL_COLORS,
)
from custom_components.bom_warnings.warning_types import sensor_types
from scripts.fake_bom import layout, scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import ENTITY_ID as ANY_WARNING
from .test_binary_sensor import poll, setup_entry

pytestmark = pytest.mark.freeze_time(NOW)

THUNDERSTORM = "sensor.home_thunderstorm_warning"
# BoM sends the CAP severity `unknown` for Severe Thunderstorm Warnings; it is shown as unrated.
NONE = "none"
UNRATED = "unrated"


async def start(hass: HomeAssistant, entry: MockConfigEntry, entity_id: str = THUNDERSTORM) -> Any:
    await setup_entry(hass, entry)
    state = hass.states.get(entity_id)
    assert state is not None
    return state


def warning(severity: Severity, **overrides: Any) -> ActiveWarning:
    fields: dict[str, Any] = {
        "product_id": "IDQ00001",
        "event": "Thunderstorm",
        "headline": "Severe Thunderstorm Warning",
        "severity": severity,
        "effective": None,
        "expires": None,
        "phase": Phase.NEW,
    }
    return ActiveWarning(**{**fields, **overrides})


async def test_renamed_sensors_keep_their_entity_ids(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    for warning_type in sensor_types():
        entity_id = f"sensor.home_{warning_type.key}"
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.attributes["friendly_name"] == f"Home {warning_type.sensor_name}"


async def test_the_sensor_is_enabled_from_the_start(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    entry = er.async_get(hass).async_get(THUNDERSTORM)
    assert entry is not None
    assert entry.disabled_by is None
    assert hass.states.get(THUNDERSTORM) is not None


@pytest.mark.parametrize("area_codes", [["QLD_ME008"]])
async def test_the_sensor_turns_on_for_a_covering_warning(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    state = await start(hass, mock_config_entry)

    assert state.state == UNRATED
    assert state.attributes["friendly_name"] == "Home Severe thunderstorm warning"


@pytest.mark.parametrize(
    ("area_codes", "expected"),
    [
        (["QLD_PW001"], NONE),
        (["QLD_ME008"], UNRATED),
        (["QLD_PW013"], UNRATED),
    ],
    ids=["not-covered", "brisbane", "darling-downs"],
)
async def test_rated_only_while_a_thunderstorm_warning_covers_the_location(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
    expected: str,
) -> None:
    state = await start(hass, mock_config_entry)

    assert state.state == expected


async def test_with_no_warning_the_state_is_none_and_the_attributes_are_empty(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    state = await start(hass, mock_config_entry)

    assert state.state == NONE
    assert state.attributes["warnings"] == []
    for key in ("headline", "expires", "product_id", "event"):
        assert state.attributes[key] is None, key


async def test_with_no_warning_the_level_is_none_and_there_is_no_colour(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    state = await start(hass, mock_config_entry)

    assert state.attributes["level"] == NONE
    assert state.attributes["color"] is None


@pytest.mark.parametrize("area_codes", [["QLD_ME008"]])
async def test_an_active_warning_gives_its_level_and_the_colour_of_that_level(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    state = await start(hass, mock_config_entry)

    assert state.attributes["level"] == UNRATED
    assert state.attributes["color"] == LEVEL_COLORS["unknown"]


@pytest.mark.parametrize("severity", list(Severity))
def test_each_level_has_its_own_colour(severity: Severity) -> None:
    attributes = type_attributes("Thunderstorm", [warning(severity)])

    assert attributes["level"] == ("unrated" if severity is Severity.UNKNOWN else severity.value)
    assert attributes["color"] == LEVEL_COLORS[severity.value]


@pytest.mark.parametrize("phase", [Phase.CANCELLED, Phase.FINAL])
def test_an_ended_warning_leaves_the_level_none_and_no_colour(phase: Phase) -> None:
    attributes = type_attributes("Thunderstorm", [warning(Severity.SEVERE, phase=phase)])

    assert attributes["level"] == NONE
    assert attributes["color"] is None


def test_the_colour_follows_the_highest_current_warning() -> None:
    attributes = type_attributes(
        "Thunderstorm",
        [warning(Severity.MINOR), warning(Severity.EXTREME, product_id="IDQ00002")],
    )

    assert attributes["level"] == "extreme"
    assert attributes["color"] == LEVEL_COLORS["extreme"]


@pytest.mark.parametrize("area_codes", [["QLD_ME008", "QLD_PW013"]])
async def test_attributes_list_each_warning_of_the_type_with_the_highest_severity(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    state = await start(hass, mock_config_entry)

    assert state.state == UNRATED  # what BoM sends for these recorded files is `unknown`
    # The top warning's fields are top-level attributes, so a tile can show them. Equal severity
    # goes to the most recently issued.
    assert state.attributes["product_id"] in {"IDQ21033", "IDQ21035"}
    assert state.attributes["event"] == "Thunderstorm"
    assert state.attributes["headline"].startswith("Severe Thunderstorm Warning for")
    assert state.attributes["expires"] is not None
    assert "severity" not in state.attributes  # the state says it
    assert {w["product_id"] for w in state.attributes["warnings"]} == {"IDQ21033", "IDQ21035"}
    [brisbane] = (w for w in state.attributes["warnings"] if w["product_id"] == "IDQ21035")
    assert brisbane["event"] == "Thunderstorm"
    assert brisbane["headline"].startswith("Severe Thunderstorm Warning for Greater Brisbane")
    assert brisbane["phase"] == "update"  # the recorded message type
    assert brisbane["expires"] == "2026-11-01T09:03:55+00:00"
    assert set(brisbane) == {
        "product_id",
        "event",
        "headline",
        "severity",
        "phase",
        "effective",
        "expires",
        "in_force",
        "summary",
    }
    assert 0 < len(brisbane["summary"]) <= 300


@pytest.mark.parametrize("area_codes", [["QLD_PW013"]])
async def test_off_when_the_warning_file_is_removed(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    await start(hass, mock_config_entry)
    assert hass.states.get(THUNDERSTORM).state == UNRATED  # type: ignore[union-attr]

    scenarios.apply("warning_removed", fake_bom.root)
    await poll(hass, freezer)

    assert hass.states.get(THUNDERSTORM).state == NONE  # type: ignore[union-attr]


@pytest.mark.parametrize("area_codes", [["QLD_PW001"]])
async def test_a_warning_of_another_type_does_not_turn_it_on(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    await start(hass, mock_config_entry)
    assert hass.states.get(THUNDERSTORM).state == NONE  # type: ignore[union-attr]

    scenarios.apply("warning_appears", fake_bom.root)
    await poll(hass, freezer)

    # `warning_appears` adds a heatwave over the same area codes.
    assert hass.states.get(THUNDERSTORM).state == NONE  # type: ignore[union-attr]


@pytest.mark.parametrize("area_codes", [["QLD_ME008"]])
async def test_off_once_the_warning_has_expired(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    await start(hass, mock_config_entry)
    assert hass.states.get(THUNDERSTORM).state == UNRATED  # type: ignore[union-attr]

    await poll(hass, freezer, minutes=70)  # the recorded warning expires at 09:03

    assert hass.states.get(THUNDERSTORM).state == NONE  # type: ignore[union-attr]


def cancel_the_darling_downs_warning(fake_bom: FakeBom) -> None:
    """BoM's sample file for IDQ21033 holds a real cancellation for Darling Downs (QLD_PW013)."""
    layout.put_sample(
        fake_bom.root,
        "IDQ21033.cap.xml",
        shift_to=datetime.fromisoformat(NOW).astimezone(UTC),
        mtime=datetime.fromisoformat(NOW).timestamp() + 60,
    )


@pytest.mark.parametrize("area_codes", [["QLD_PW013"]])
async def test_a_cancelled_warning_is_not_current(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    await start(hass, mock_config_entry)
    assert hass.states.get(THUNDERSTORM).state == UNRATED  # type: ignore[union-attr]

    cancel_the_darling_downs_warning(fake_bom)
    await poll(hass, freezer)

    assert hass.states.get(THUNDERSTORM).state == NONE  # type: ignore[union-attr]


@pytest.mark.parametrize("area_codes", [["QLD_PW013"]])
@pytest.mark.parametrize("entry_options", [{CONF_HIDE_FINAL: False}])
async def test_a_cancelled_warning_is_listed_for_reference_when_not_hidden(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    await start(hass, mock_config_entry)

    cancel_the_darling_downs_warning(fake_bom)
    await poll(hass, freezer)

    state = hass.states.get(THUNDERSTORM)
    assert state is not None
    assert state.state == NONE
    [listed] = state.attributes["warnings"]
    assert listed["phase"] == "cancelled"
    assert state.attributes["headline"] is None


@pytest.mark.parametrize("area_codes", [["QLD_ME008"]])
@pytest.mark.parametrize("entry_options", [{CONF_WARNING_TYPES: ["frost_warning"]}])
async def test_a_type_that_is_off_has_no_sensor_and_is_not_counted(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    """Only Frost is on, so the thunderstorm warning at this location is ignored everywhere."""
    await setup_entry(hass, mock_config_entry)

    assert er.async_get(hass).async_get(THUNDERSTORM) is None
    assert hass.states.get(THUNDERSTORM) is None
    assert hass.states.get("sensor.home_frost_warning").state == NONE  # type: ignore[union-attr]
    assert hass.states.get(ANY_WARNING).state == STATE_OFF  # type: ignore[union-attr]
    assert hass.states.get("sensor.home_warning_count").state == "0"  # type: ignore[union-attr]


async def test_the_sensor_is_a_level_sensor_not_a_safety_binary_sensor(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    state = await start(hass, mock_config_entry)

    assert state.attributes["device_class"] == "enum"
    assert state.attributes["options"] == LEVEL_OPTIONS
    assert "state_class" not in state.attributes
    assert state.attributes["icon"] == "mdi:weather-lightning-rainy"
    assert hass.states.get("binary_sensor.home_thunderstorm_warning") is None
