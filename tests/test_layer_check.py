"""The weekly shapefile layer check runs in the background, apart from the warnings refresh.

`refresh_layers` is patched (see `layers` in test_options) because the shapefiles are not in the
repo. Everything else is real, against the fake BoM server.
"""

import threading
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import CONF_AREA_CODES, SPATIAL_CACHE_DIR
from custom_components.bom_warnings.ftp import BomFtpError
from custom_components.bom_warnings.layer_check import LAYER_CHECK_INTERVAL
from custom_components.bom_warnings.shared_feed import FEED
from custom_components.bom_warnings.spatial import LAYERS, RefreshResult
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import ENTITY_ID, poll
from .test_options import layers, resolve  # noqa: F401
from .test_reliability import repair_issues

pytestmark = pytest.mark.freeze_time(NOW)

RECORD = ".last_layer_check"


def record_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(SPATIAL_CACHE_DIR)) / RECORD


def write_record(hass: HomeAssistant, text: str) -> None:
    path = record_path(hass)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


def test_interval_is_weekly() -> None:
    assert timedelta(days=7) == LAYER_CHECK_INTERVAL


async def test_first_check_runs_after_the_first_refresh_with_its_own_client(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
) -> None:
    await setup(hass, mock_config_entry)

    assert layers.call_count == 1
    assert layers.call_args.args[0] is not hass.data[FEED]._ftp
    assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]


async def test_the_warnings_refresh_does_not_wait_for_the_layer_check_nor_repeat_it(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
) -> None:
    release = threading.Event()
    layers.side_effect = lambda *_: release.wait(10) and RefreshResult()
    mock_config_entry.add_to_hass(hass)
    try:
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        # Set up and showing data while the check is still blocked.
        assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]

        feed = hass.data[FEED]
        await feed.async_refresh()
        await feed.async_refresh()
    finally:
        release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert layers.call_count == 1


async def test_layer_check_errors_never_fail_the_refresh_and_are_retried(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    layers.side_effect = BomFtpError("timed out")
    await setup(hass, mock_config_entry)

    feed = hass.data[FEED]
    assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]
    assert feed.consecutive_failures == 0
    assert not record_path(hass).exists()

    for _ in range(3):
        await poll(hass, freezer)
    assert layers.call_count == 4  # retried on every later poll until it gets through
    assert feed.consecutive_failures == 0
    assert repair_issues(hass) == []


async def test_a_check_where_every_layer_failed_is_not_recorded(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    layers.return_value = RefreshResult(failed=dict.fromkeys(LAYERS, "timed out"))
    await setup(hass, mock_config_entry)
    assert not record_path(hass).exists()

    layers.return_value = RefreshResult()
    await poll(hass, freezer)
    assert layers.call_count == 2
    assert record_path(hass).exists()

    await poll(hass, freezer)
    assert layers.call_count == 2


async def test_a_check_that_reached_the_server_is_recorded(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
) -> None:
    layers.return_value = RefreshResult(failed={LAYERS[0]: "timed out"})
    await setup(hass, mock_config_entry)

    assert dt_util.parse_datetime(record_path(hass).read_text()) == dt_util.parse_datetime(NOW)


@pytest.mark.parametrize(
    ("record_age", "checks"),
    [
        (timedelta(days=1), 0),
        (timedelta(days=6, hours=23), 0),
        (timedelta(days=8), 1),
        (None, 1),
        ("not a time", 1),
        ("", 1),
    ],
)
async def test_restart_checks_only_when_the_record_is_missing_corrupt_or_old(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    record_age: timedelta | str | None,
    checks: int,
) -> None:
    if isinstance(record_age, timedelta):
        write_record(hass, (dt_util.utcnow() - record_age).isoformat())
    elif record_age is not None:
        write_record(hass, record_age)

    await setup(hass, mock_config_entry)

    assert layers.call_count == checks


async def test_a_recorded_check_comes_due_a_week_later(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    write_record(hass, (dt_util.utcnow() - timedelta(days=1)).isoformat())
    await setup(hass, mock_config_entry)
    for _ in range(5):
        await poll(hass, freezer, 60 * 24)
    assert layers.call_count == 0

    await poll(hass, freezer, 60 * 24)
    assert layers.call_count == 1


async def test_a_layer_change_publishes_a_new_snapshot_and_entries_re_resolve(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    layers.return_value = RefreshResult(changed=["IDM00001"])
    resolve.return_value = {"QLD_ME008"}
    await setup(hass, mock_config_entry)

    assert hass.data[FEED].data.layer_generation == 1
    assert mock_config_entry.data[CONF_AREA_CODES] == ["QLD_ME008"]
    assert hass.states.get(ENTITY_ID).state == STATE_ON  # type: ignore[union-attr]


async def test_unloading_the_last_entry_does_not_wait_for_a_running_check(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
) -> None:
    release = threading.Event()
    layers.side_effect = lambda *_: release.wait(10) and RefreshResult()
    mock_config_entry.add_to_hass(hass)
    try:
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert FEED not in hass.data
    finally:
        release.set()
