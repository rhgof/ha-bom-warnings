"""Repair issue after repeated refresh failures, and diagnostics, driven through Home Assistant."""

from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bom_warnings.const import DOMAIN
from custom_components.bom_warnings.diagnostics import async_get_config_entry_diagnostics
from custom_components.bom_warnings.ftp import BomFtpError
from custom_components.bom_warnings.shared_feed import FEED
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import ENTITY_ID, poll, setup_entry

pytestmark = pytest.mark.freeze_time(NOW)


def repair_issues(hass: HomeAssistant) -> list[ir.IssueEntry]:
    return [issue for (domain, _), issue in ir.async_get(hass).issues.items() if domain == DOMAIN]


async def test_repair_issue_appears_after_three_failures_and_clears_on_recovery(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    port = int(fake_bom.address.split(":")[1])
    fake_bom.stop()

    for _ in range(2):
        await poll(hass, freezer)
        assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE  # type: ignore[union-attr]
        assert repair_issues(hass) == []

    await poll(hass, freezer)
    [issue] = repair_issues(hass)
    assert issue.translation_key == "refresh_failing"
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING

    with FakeBom(fake_bom.root, port=port):
        await poll(hass, freezer)

    assert repair_issues(hass) == []
    assert hass.states.get(ENTITY_ID).state == STATE_OFF  # type: ignore[union-attr]


async def test_a_success_in_between_resets_the_failure_count(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    port = int(fake_bom.address.split(":")[1])
    fake_bom.stop()
    await poll(hass, freezer)
    await poll(hass, freezer)

    with FakeBom(fake_bom.root, port=port) as _:
        await poll(hass, freezer)
    # Down again: the count starts over, so two more failures raise nothing.
    await poll(hass, freezer)
    await poll(hass, freezer)

    assert repair_issues(hass) == []


async def test_repair_issue_is_removed_with_the_entry(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    fake_bom.stop()
    for _ in range(3):
        await poll(hass, freezer)
    assert len(repair_issues(hass)) == 1

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert repair_issues(hass) == []


async def test_diagnostics_redact_location(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_entry(hass, mock_config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    # Called directly: the HTTP download path breaks under the frozen clock these tests need.
    text = str(diagnostics)
    for secret in ("-27.47", "153.021", "-27.470,153.021", "Home"):
        assert secret not in text
    assert diagnostics["entry"]["data"]["state"] == "QLD"
    assert diagnostics["entry"]["data"]["area_codes"] == ["QLD_PW001"]
    assert diagnostics["coordinator"]["last_update_success"] is True
    assert diagnostics["coordinator"]["warnings"] == []


async def test_repair_issue_appears_when_bom_is_down_at_startup(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    fake_bom.stop()
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert repair_issues(hass) == []

    # Home Assistant retries the setup; the count must survive each failed attempt.
    for _ in range(2):
        freezer.tick(timedelta(minutes=2))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done(wait_background_tasks=True)

    [issue] = repair_issues(hass)
    assert issue.translation_key == "refresh_failing"


async def test_removing_an_entry_that_never_set_up_clears_the_repair_issue(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    fake_bom.stop()
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    for _ in range(2):
        freezer.tick(timedelta(minutes=2))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done(wait_background_tasks=True)
    assert len(repair_issues(hass)) == 1

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert repair_issues(hass) == []


@pytest.mark.parametrize(
    ("target", "error"),
    [
        ("custom_components.bom_warnings.client_from_env", BomFtpError("bad host")),
        (
            "custom_components.bom_warnings.BomWarningsCoordinator.async_config_entry_first_refresh",
            RuntimeError("bug"),
        ),
    ],
)
async def test_failed_setup_leaves_no_entry_registered_on_the_feed(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    target: str,
    error: Exception,
) -> None:
    mock_config_entry.add_to_hass(hass)

    with patch(target, side_effect=error):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert hass.data[FEED].entry_ids == set()
