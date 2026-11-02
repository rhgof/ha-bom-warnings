"""Options and layer-change handling, driven through Home Assistant.

The shapefiles are not in the repo, so layer changes are injected at two seams, as the
coordinator imports them: `refresh_layers` reports which layers changed and `resolve_coordinate`
says which area codes the stored point now resolves to. Everything else is real, against the
fake BoM server.
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    CONF_AREA_CODES,
    CONF_EVENT_TYPES,
    CONF_HIDE_FINAL,
    CONF_STATE,
    DOMAIN,
)
from custom_components.bom_warnings.spatial import RefreshResult
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import ENTITY_ID, poll, setup_entry

pytestmark = pytest.mark.freeze_time(NOW)

# Shorter than the real interval so the recorded warnings (which expire at 09:03) still count.
CHECK_INTERVAL = timedelta(minutes=30)
# Longer than that interval, so the next poll checks the layers again.
LAYER_CHECK_DUE = 31


@pytest.fixture(autouse=True)
def short_layer_interval() -> Iterator[None]:
    with patch("custom_components.bom_warnings.coordinator.LAYER_CHECK_INTERVAL", CHECK_INTERVAL):
        yield


@pytest.fixture
def layers() -> Iterator[MagicMock]:
    """`refresh_layers`: by default nothing changed."""
    with patch(
        "custom_components.bom_warnings.coordinator.refresh_layers",
        return_value=RefreshResult(),
    ) as mock:
        yield mock


@pytest.fixture
def resolve() -> Iterator[MagicMock]:
    with patch(
        "custom_components.bom_warnings.coordinator.resolve_coordinate",
        return_value={"QLD_PW001", "QLD_ME008"},
    ) as mock:
        yield mock


def issue_of(entry: MockConfigEntry, hass: HomeAssistant) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"no_area_{entry.entry_id}")


def sensor_state(hass: HomeAssistant) -> Any:
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    return state


async def set_options(hass: HomeAssistant, entry: MockConfigEntry, **options: Any) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], options)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


@pytest.mark.parametrize("area_codes", [["QLD_ME008", "QLD_PW001"]])
async def test_event_type_choice_applies_without_a_restart(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,
) -> None:
    scenarios.apply("warning_appears", fake_bom.root)
    await setup_entry(hass, mock_config_entry)
    events = [w["event"] for w in sensor_state(hass).attributes["warnings"]]
    assert sorted(events) == ["Extreme Heat", "Thunderstorm"]

    await set_options(hass, mock_config_entry, **{CONF_EVENT_TYPES: ["Extreme Heat"]})

    events = [w["event"] for w in sensor_state(hass).attributes["warnings"]]
    assert events == ["Extreme Heat"]
    assert mock_config_entry.options[CONF_EVENT_TYPES] == ["Extreme Heat"]


@pytest.mark.parametrize("area_codes", [["NSW_MW001"]])
async def test_cancelled_warnings_are_shown_when_not_hidden(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    scenarios.apply("warning_cancelled", fake_bom.root)
    await poll(hass, freezer)
    assert sensor_state(hass).state == STATE_OFF

    await set_options(hass, mock_config_entry, **{CONF_HIDE_FINAL: False})

    assert sensor_state(hass).state == STATE_ON
    [warning] = sensor_state(hass).attributes["warnings"]
    assert warning["phase"] == "cancelled"


async def test_options_form_defaults_hide_final_and_all_types(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,
) -> None:
    await setup_entry(hass, mock_config_entry)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})

    assert result["data"] == {CONF_HIDE_FINAL: True, CONF_EVENT_TYPES: []}


async def test_changed_layer_re_resolves_stored_codes(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,
    resolve: MagicMock,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert sensor_state(hass).state == STATE_OFF
    resolve.assert_not_called()  # nothing changed at setup

    # The district boundary moved: the same point is now in an area with a warning.
    resolve.return_value = {"NSW_PW002", "QLD_ME008"}
    layers.return_value = RefreshResult(changed=["IDM00001"])
    await poll(hass, freezer, LAYER_CHECK_DUE)

    assert mock_config_entry.data[CONF_AREA_CODES] == ["NSW_PW002", "QLD_ME008"]
    assert mock_config_entry.data[CONF_STATE] == "NSW"
    assert resolve.call_args.kwargs == {"lat": -27.47, "lon": 153.021}
    assert sensor_state(hass).state == STATE_ON


async def test_layers_are_checked_once_per_interval_not_every_poll(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await poll(hass, freezer)
    await poll(hass, freezer)
    assert layers.call_count == 1

    await poll(hass, freezer, LAYER_CHECK_DUE)
    assert layers.call_count == 2


async def test_no_area_after_layer_change_raises_a_repair_and_keeps_codes(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,
    resolve: MagicMock,
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)

    resolve.return_value = set()
    layers.return_value = RefreshResult(changed=["IDM00001"])
    await poll(hass, freezer, LAYER_CHECK_DUE)

    issue = issue_of(mock_config_entry, hass)
    assert issue is not None
    assert issue.translation_key == "no_area"
    assert issue.translation_placeholders == {"title": "Home"}
    assert mock_config_entry.data[CONF_AREA_CODES] == ["QLD_PW001"]
    # The old codes still match, so the sensor keeps working rather than going unavailable.
    assert sensor_state(hass).state == STATE_OFF

    # A later layer update that covers the point again clears the repair.
    resolve.return_value = {"QLD_PW001"}
    await poll(hass, freezer, LAYER_CHECK_DUE)
    assert issue_of(mock_config_entry, hass) is None
