"""The warning count and most-severe sensors, driven through Home Assistant."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bom_warnings.cap import Severity
from custom_components.bom_warnings.const import CONF_STATE
from custom_components.bom_warnings.coordinator import ActiveWarning
from custom_components.bom_warnings.sensor import most_severe
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW

COUNT = "sensor.home_warning_count"
MOST_SEVERE = "sensor.home_most_severe_warning"

pytestmark = pytest.mark.freeze_time(NOW)


async def setup_entry(
    hass: HomeAssistant, entry: MockConfigEntry, state: str | None = None
) -> None:
    if state:
        entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_STATE: state})
    else:
        entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def poll(hass: HomeAssistant, freezer: Any, minutes: int = 11) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)


def state_of(hass: HomeAssistant, entity_id: str) -> Any:
    state = hass.states.get(entity_id)
    assert state is not None
    return state


def warning(severity: Severity, sent: datetime | None = None, event: str = "Wind") -> ActiveWarning:
    return ActiveWarning(
        product_id="IDX00000",
        event=event,
        headline=f"{severity} {event}",
        severity=severity,
        effective=None,
        expires=None,
        sent=sent,
    )


async def test_counts_current_warnings_in_the_state(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    # No baseline warning covers QLD_PW001, but two QLD thunderstorm warnings are current.
    await setup_entry(hass, mock_config_entry)

    assert state_of(hass, COUNT).state == "2"


@pytest.mark.parametrize(
    ("state", "area_codes", "count"),
    [("NSW", ["NSW_PW001"], "1"), ("SA", ["SA_PW001"], "0")],
)
async def test_other_states_warnings_are_not_counted(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    state: str,
    count: str,
) -> None:
    await setup_entry(hass, mock_config_entry, state)

    assert state_of(hass, COUNT).state == count


@pytest.mark.parametrize("area_codes", [["SA_PW001"]])
async def test_no_warnings_gives_none_not_unavailable(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry, "SA")

    state = state_of(hass, MOST_SEVERE)
    assert state.state == "none"
    assert state.attributes["warnings"] == []


async def test_most_severe_picks_the_severe_warning_when_it_appears(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert state_of(hass, MOST_SEVERE).attributes["severity"] == "unknown"

    scenarios.apply("warning_appears", fake_bom.root)
    await poll(hass, freezer)

    assert state_of(hass, COUNT).state == "3"
    most = state_of(hass, MOST_SEVERE)
    assert most.attributes["event"] == "Extreme Heat"
    assert most.attributes["severity"] == "severe"
    assert most.state == most.attributes["headline"]
    assert len(most.attributes["warnings"]) == 3


async def test_unavailable_when_the_server_is_down(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)

    fake_bom.stop()
    await poll(hass, freezer)

    assert state_of(hass, COUNT).state == STATE_UNAVAILABLE
    assert state_of(hass, MOST_SEVERE).state == STATE_UNAVAILABLE


def test_severity_order_is_exactly_unknown_minor_moderate_severe_extreme() -> None:
    remaining = [
        warning(s)
        for s in (
            Severity.SEVERE,
            Severity.UNKNOWN,
            Severity.EXTREME,
            Severity.MINOR,
            Severity.MODERATE,
        )
    ]
    ranked: list[Severity] = []
    while remaining:
        best = most_severe(remaining)
        assert best is not None
        ranked.append(best.severity)
        remaining.remove(best)

    assert ranked == [
        Severity.EXTREME,
        Severity.SEVERE,
        Severity.MODERATE,
        Severity.MINOR,
        Severity.UNKNOWN,
    ]


def test_ties_break_on_most_recently_issued() -> None:
    old = warning(Severity.SEVERE, datetime(2026, 11, 1, 1, tzinfo=UTC), "Old")
    new = warning(Severity.SEVERE, datetime(2026, 11, 1, 2, tzinfo=UTC), "New")
    undated = warning(Severity.SEVERE, None, "Undated")

    assert most_severe([old, undated, new]) is new


def test_most_severe_of_nothing_is_none() -> None:
    assert most_severe([]) is None
