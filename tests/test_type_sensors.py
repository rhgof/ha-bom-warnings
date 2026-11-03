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

from custom_components.bom_warnings.active_warnings import ActiveWarning
from custom_components.bom_warnings.cap import Phase, Severity
from custom_components.bom_warnings.const import (
    CONF_HIDE_FINAL,
    CONF_WARNING_TYPES,
    WARNING_TYPE_SENSORS,
)
from custom_components.bom_warnings.sensor import LEVEL_OPTIONS, highest_level
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
    assert state.attributes["friendly_name"] == "Home Thunderstorm warning"


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
    }


@pytest.mark.parametrize(
    ("severities", "expected"),
    [
        ([], "none"),
        ([Severity.MINOR], "minor"),
        ([Severity.MINOR, Severity.SEVERE, Severity.MODERATE], "severe"),
        # `unknown` is what BoM sends for Severe Thunderstorm. It is shown as `unrated`, because
        # `unknown` is Home Assistant's own no-value state, and it ranks above moderate.
        ([Severity.MODERATE, Severity.UNKNOWN], "unrated"),
        ([Severity.UNKNOWN, Severity.SEVERE], "severe"),
        ([Severity.SEVERE, Severity.EXTREME], "extreme"),
    ],
)
def test_highest_level_uses_the_existing_ranking(severities: list[Severity], expected: str) -> None:
    assert highest_level([warning(s) for s in severities]) == expected


def test_a_finished_warning_does_not_set_the_level() -> None:
    finished = warning(Severity.EXTREME, phase=Phase.CANCELLED)

    assert highest_level([finished, warning(Severity.MINOR)]) == "minor"
    assert highest_level([finished]) == "none"


def test_the_states_are_the_ranking_lowest_first_and_never_the_ha_unknown_state() -> None:
    assert LEVEL_OPTIONS == ["none", "minor", "moderate", "unrated", "severe", "extreme"]
    assert "unknown" not in LEVEL_OPTIONS


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


async def test_every_row_of_the_table_has_a_distinct_key_and_event() -> None:
    keys = [key for _, key in WARNING_TYPE_SENSORS]
    events = [event for event, _ in WARNING_TYPE_SENSORS]
    assert len(set(keys)) == len(keys)
    assert len(set(events)) == len(events)
    assert ("Thunderstorm", "thunderstorm_warning") in WARNING_TYPE_SENSORS


async def test_the_sensor_is_a_level_sensor_not_a_safety_binary_sensor(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    state = await start(hass, mock_config_entry)

    assert state.attributes["device_class"] == "enum"
    assert state.attributes["options"] == LEVEL_OPTIONS
    assert "state_class" not in state.attributes
    assert state.attributes["icon"] == "mdi:weather-lightning-rainy"
    assert hass.states.get("binary_sensor.home_thunderstorm_warning") is None
