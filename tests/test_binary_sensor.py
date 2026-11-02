"""The warning binary sensor, driven through Home Assistant against the fake BoM FTP server."""

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bom_warnings.const import DOMAIN
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW

ENTITY_ID = "binary_sensor.home_warning"

pytestmark = pytest.mark.freeze_time(NOW)


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def poll(hass: HomeAssistant, freezer: Any, minutes: int = 11) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, dt_util.utcnow())
    # Coordinator refreshes run as background tasks.
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_off_when_no_warning_covers_the_location(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]
    assert hass.states.get(ENTITY_ID).attributes["warnings"] == []  # type: ignore[union-attr]


@pytest.mark.parametrize("area_codes", [["QLD_ME008"]])
async def test_on_with_matching_warning_attributes(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == STATE_ON
    [warning] = state.attributes["warnings"]
    assert warning["product_id"] == "IDQ21035"
    assert warning["event"] == "Thunderstorm"
    assert warning["severity"] == "unknown"  # BoM sends Unknown for this recorded file
    assert warning["expires"] == "2026-11-01T09:03:55+00:00"


async def test_turns_on_when_a_covering_warning_appears_then_off_when_it_is_removed(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]

    scenarios.apply("warning_appears", fake_bom.root)
    await poll(hass, freezer, 1)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]  # not yet due

    await poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_ON  # type: ignore[union-attr]

    scenarios.apply("baseline", fake_bom.root)
    await poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]


@pytest.mark.parametrize("area_codes", [["QLD_PW013"]])
async def test_removed_warning_stops_counting(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_ON  # type: ignore[union-attr]

    scenarios.apply("warning_removed", fake_bom.root)
    await poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]


@pytest.mark.parametrize("area_codes", [["NSW_MW001"]])
async def test_cancelled_warning_does_not_count(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)

    scenarios.apply("warning_cancelled", fake_bom.root)
    await poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]


@pytest.mark.parametrize("area_codes", [["QLD_ME008"]])
async def test_warning_that_expires_stops_counting(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get(ENTITY_ID).state == STATE_ON  # type: ignore[union-attr]

    # IDQ21035 expires at 09:03:55 and its file is unchanged, so no refetch is needed.
    await poll(hass, freezer, 70)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]


async def test_unavailable_when_the_server_is_down_and_recovers(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)

    fake_bom.stop()
    await poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE  # type: ignore[union-attr]


async def test_setup_retries_when_the_server_is_down(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
) -> None:
    fake_bom.stop()
    mock_config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_removes_the_entity(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE  # type: ignore[union-attr]
    assert DOMAIN in hass.config.components
