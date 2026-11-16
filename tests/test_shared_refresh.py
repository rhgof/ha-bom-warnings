"""Several locations share one FTP refresh, driven through Home Assistant against the fake FTP."""

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bom_warnings import shared_feed
from custom_components.bom_warnings.const import (
    CONF_AREA_CODES,
    CONF_AREA_NAMES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_STATE,
    DOMAIN,
)
from custom_components.bom_warnings.shared_feed import FEED
from custom_components.bom_warnings.spatial import RefreshResult
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import ENTITY_ID as HOME
from .test_binary_sensor import poll, setup_entry
from .test_options import LAYER_CHECK_DUE, layers, set_options, short_layer_interval  # noqa: F401
from .test_reliability import repair_issues

WORK = "binary_sensor.work_warning"

pytestmark = pytest.mark.freeze_time(NOW)


@pytest.fixture
def work_entry() -> MockConfigEntry:
    """A second location, inside the district the baseline thunderstorm warning covers."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="-27.600,152.900",
        title="Work",
        data={
            CONF_LATITUDE: -27.6,
            CONF_LONGITUDE: 152.9,
            CONF_STATE: "QLD",
            CONF_AREA_CODES: ["QLD_ME008"],
            CONF_AREA_NAMES: {},
        },
    )


def count(server: FakeBom, command: str) -> int:
    """How often the server saw `command`; `LIST` counts only the warnings listing.

    A refresh also lists a product's XML by exact name (a flood warning's phase), which is a
    separate, optional request and says nothing about how many polls ran.
    """
    return sum(
        1 for cmd, arg in server.commands if cmd == command and (command != "LIST" or "*" in arg)
    )


def state_of(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None
    return state.state


async def test_two_entries_share_one_listing_and_one_set_of_fetches(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    work_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    mock_config_entry.add_to_hass(hass)
    work_entry.add_to_hass(hass)
    # Setting up the domain sets up both entries.
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    # The baseline's two thunderstorm products each cost a request for their broadcast text, which
    # the fake server does not have. The absence is remembered, so it is asked once.
    files = len(list(fake_bom.root.rglob("*.cap.xml"))) + 2

    assert state_of(hass, HOME) == STATE_OFF
    assert state_of(hass, WORK) == STATE_ON
    assert count(fake_bom, "LIST") == 1
    assert count(fake_bom, "RETR") == files

    # One more interval: one more listing, and nothing changed so nothing is fetched again.
    await poll(hass, freezer)
    assert count(fake_bom, "LIST") == 2
    assert count(fake_bom, "RETR") == files


async def test_entries_show_their_own_result_from_the_same_refresh(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    work_entry: MockConfigEntry,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await setup_entry(hass, work_entry)

    assert state_of(hass, HOME) == STATE_OFF
    assert state_of(hass, WORK) == STATE_ON
    [warning] = hass.states.get(WORK).attributes["warnings"]  # type: ignore[union-attr]
    assert warning["product_id"] == "IDQ21035"
    assert count(fake_bom, "LIST") == 1  # the second entry joined without a new listing


async def test_a_new_warning_reaches_each_entry_it_covers(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    work_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await setup_entry(hass, work_entry)

    scenarios.apply("warning_appears", fake_bom.root)
    await poll(hass, freezer)

    assert state_of(hass, HOME) == STATE_ON
    assert state_of(hass, WORK) == STATE_ON
    assert len(hass.states.get(HOME).attributes["warnings"]) == 1  # type: ignore[union-attr]


async def test_unloading_one_entry_leaves_the_other_working(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    work_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await setup_entry(hass, work_entry)

    await hass.config_entries.async_unload(work_entry.entry_id)
    await hass.async_block_till_done()
    scenarios.apply("warning_appears", fake_bom.root)
    await poll(hass, freezer)

    assert state_of(hass, WORK) == STATE_UNAVAILABLE
    assert state_of(hass, HOME) == STATE_ON
    assert count(fake_bom, "LIST") == 2


async def test_reloading_one_entry_leaves_the_other_working(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    work_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await setup_entry(hass, work_entry)

    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    scenarios.apply("warning_appears", fake_bom.root)
    await poll(hass, freezer)

    assert state_of(hass, HOME) == STATE_ON
    assert state_of(hass, WORK) == STATE_ON
    assert count(fake_bom, "LIST") == 2  # reloading joined the running refresh


async def test_removing_one_entry_leaves_the_other_working(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    work_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await setup_entry(hass, work_entry)

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await poll(hass, freezer)

    assert state_of(hass, WORK) == STATE_ON
    assert count(fake_bom, "LIST") == 2


async def test_unloading_the_last_entry_stops_refreshing(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    work_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await setup_entry(hass, work_entry)
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.config_entries.async_unload(work_entry.entry_id)
    await hass.async_block_till_done()

    await poll(hass, freezer)
    await poll(hass, freezer)
    assert count(fake_bom, "LIST") == 1

    # Loading again starts a fresh refresh.
    assert await hass.config_entries.async_setup(work_entry.entry_id)
    await hass.async_block_till_done()
    assert count(fake_bom, "LIST") == 2
    assert state_of(hass, WORK) == STATE_ON


async def test_failures_raise_one_repair_issue_for_all_entries(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    work_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await setup_entry(hass, work_entry)
    port = int(fake_bom.address.split(":")[1])
    fake_bom.stop()

    for _ in range(2):
        await poll(hass, freezer)
    assert repair_issues(hass) == []
    await poll(hass, freezer)
    [issue] = repair_issues(hass)
    assert issue.translation_key == "refresh_failing"
    assert state_of(hass, HOME) == STATE_UNAVAILABLE
    assert state_of(hass, WORK) == STATE_UNAVAILABLE

    with FakeBom(fake_bom.root, port=port):
        await poll(hass, freezer)
    assert repair_issues(hass) == []
    assert state_of(hass, WORK) == STATE_ON


async def test_repair_issue_outlives_one_removed_entry_and_goes_with_the_last(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    work_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await setup_entry(hass, work_entry)
    fake_bom.stop()
    for _ in range(3):
        await poll(hass, freezer)

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert len(repair_issues(hass)) == 1

    await hass.config_entries.async_remove(work_entry.entry_id)
    await hass.async_block_till_done()
    assert repair_issues(hass) == []


async def test_layers_are_checked_once_and_each_entry_re_resolves_its_own_point(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    work_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await setup_entry(hass, work_entry)
    layers.reset_mock()
    resolve.reset_mock()

    layers.return_value = RefreshResult(changed=["IDM00001"])
    await poll(hass, freezer, LAYER_CHECK_DUE)

    assert layers.call_count == 1
    points = {(c.kwargs["lat"], c.kwargs["lon"]) for c in resolve.call_args_list}
    assert points == {(-27.47, 153.021), (-27.6, 152.9)}
    assert resolve.call_count == 2


async def test_reloading_an_entry_does_not_re_resolve_after_an_earlier_layer_change(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    work_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await setup_entry(hass, work_entry)
    layers.return_value = RefreshResult(changed=["IDM00001"])
    await poll(hass, freezer, LAYER_CHECK_DUE)
    resolve.reset_mock()

    # The layers already changed before this reload, so there is nothing new to resolve.
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await poll(hass, freezer)

    resolve.assert_not_called()


async def pass_the_grace_period(hass: HomeAssistant, freezer: Any) -> None:
    freezer.tick(shared_feed.FEED_GRACE + timedelta(seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_saving_options_keeps_the_feed_and_fetches_nothing_again(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    feed = hass.data[FEED]
    talked = len(fake_bom.commands)

    # Saving reloads the entry, which leaves the feed with no entry for a moment.
    await set_options(hass, mock_config_entry, thunderstorm_warning=False)
    await pass_the_grace_period(hass, freezer)

    assert hass.data[FEED] is feed
    assert len(fake_bom.commands) == talked
    assert state_of(hass, HOME) == STATE_OFF


async def test_the_feed_is_shut_down_when_no_entry_returns_within_the_grace_period(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert FEED in hass.data

    await pass_the_grace_period(hass, freezer)

    assert FEED not in hass.data


async def test_removing_the_last_entry_shuts_the_feed_down_at_once(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    fake_bom.stop()
    for _ in range(3):
        await poll(hass, freezer)
    assert len(repair_issues(hass)) == 1

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert FEED not in hass.data
    assert repair_issues(hass) == []


async def test_home_assistant_stop_cancels_a_pending_shutdown(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    await pass_the_grace_period(hass, freezer)

    # The timer was cancelled by the stop, so the grace period ending changed nothing.
    assert FEED in hass.data
