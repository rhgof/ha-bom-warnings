"""The warning count and most-severe sensors, driven through Home Assistant."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bom_warnings.cap import Severity
from custom_components.bom_warnings.coordinator import ActiveWarning
from custom_components.bom_warnings.sensor import rank_warnings
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW

COUNT = "sensor.home_warning_count"
MOST_SEVERE = "sensor.home_most_severe_warning"

pytestmark = pytest.mark.freeze_time(NOW)


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
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


def warning(
    severity: Severity,
    sent: datetime | None = None,
    event: str = "Wind",
    product_id: str = "IDX00000",
) -> ActiveWarning:
    return ActiveWarning(
        product_id=product_id,
        event=event,
        headline=f"{severity} {event}",
        severity=severity,
        effective=None,
        expires=None,
        sent=sent,
    )


# The baseline has two QLD thunderstorm warnings, but only one covers QLD_ME008. The count is
# for the location, not its state, so a warning elsewhere in the state is never counted.
@pytest.mark.parametrize(
    ("area_codes", "count"),
    [
        (["QLD_PW001"], "0"),
        (["QLD_ME008"], "1"),
        (["NSW_PW001"], "0"),
        (["SA_PW001"], "0"),
    ],
)
async def test_counts_only_warnings_covering_the_location(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    count: str,
) -> None:
    await setup_entry(hass, mock_config_entry)

    assert state_of(hass, COUNT).state == count
    assert len(state_of(hass, COUNT).attributes["warnings"]) == int(count)


@pytest.mark.parametrize("area_codes", [["QLD_PW001"]])
async def test_most_severe_ignores_state_mates_that_do_not_cover_the_location(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    state = state_of(hass, MOST_SEVERE)
    assert state.state == "none"
    assert state.attributes["warnings"] == []


@pytest.mark.parametrize("area_codes", [["SA_PW001"]])
async def test_no_warnings_gives_none_not_unavailable(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    state = state_of(hass, MOST_SEVERE)
    assert state.state == "none"
    assert state.attributes["warnings"] == []


@pytest.mark.parametrize("area_codes", [["QLD_ME008", "QLD_PW001"]])
async def test_most_severe_picks_the_severe_warning_when_it_appears(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert state_of(hass, COUNT).state == "1"
    assert state_of(hass, MOST_SEVERE).attributes["severity"] == "unknown"

    scenarios.apply("warning_appears", fake_bom.root)
    await poll(hass, freezer)

    assert state_of(hass, COUNT).state == "2"
    most = state_of(hass, MOST_SEVERE)
    assert most.attributes["event"] == "Extreme Heat"
    assert most.attributes["severity"] == "severe"
    assert most.state == most.attributes["headline"]
    assert len(most.attributes["warnings"]) == 2


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


@pytest.mark.parametrize(
    "severities",
    [
        [Severity.SEVERE, Severity.UNKNOWN, Severity.EXTREME, Severity.MINOR, Severity.MODERATE],
        [Severity.UNKNOWN, Severity.MINOR, Severity.MODERATE, Severity.SEVERE, Severity.EXTREME],
    ],
)
def test_severity_order_is_minor_moderate_unknown_severe_extreme(
    severities: list[Severity],
) -> None:
    # CAP `unknown` is what BoM sends for Severe Weather and Severe Thunderstorm, so it must
    # rank above a minor or moderate warning and below a severe one.
    ranked = rank_warnings(warning(s) for s in severities)

    assert [w.severity for w in ranked] == [
        Severity.EXTREME,
        Severity.SEVERE,
        Severity.UNKNOWN,
        Severity.MODERATE,
        Severity.MINOR,
    ]


def test_ties_break_on_most_recent_sent_then_undated_last_then_product_id() -> None:
    old = warning(Severity.SEVERE, datetime(2026, 11, 1, 1, tzinfo=UTC), "Old", "IDX00001")
    new = warning(Severity.SEVERE, datetime(2026, 11, 1, 2, tzinfo=UTC), "New", "IDX00009")
    undated_b = warning(Severity.SEVERE, None, "UndatedB", "IDX00002")
    undated_a = warning(Severity.SEVERE, None, "UndatedA", "IDX00001")

    ranked = rank_warnings([undated_b, old, undated_a, new])

    assert [w.event for w in ranked] == ["New", "Old", "UndatedA", "UndatedB"]


def test_ranking_nothing_gives_an_empty_list() -> None:
    assert rank_warnings([]) == []
