"""The config flow, driven through Home Assistant.

The shapefiles are not in the repo, so the one seam is `resolve_coordinate` as the flow imports
it: tests decide which area codes a point resolves to. Everything else (the FTP client built from
the environment, the executor hop, the entry) is real, against the fake BoM server.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    CONF_AREA_CODES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_STATE,
    DOMAIN,
)
from custom_components.bom_warnings.ftp import BomFtpError
from custom_components.bom_warnings.spatial import SpatialDataError
from scripts.fake_bom.server import FakeBom

BRISBANE = {CONF_LATITUDE: -27.4698, CONF_LONGITUDE: 153.0251}


@pytest.fixture
def resolved_codes() -> set[str]:
    """What the shapefiles say about the point; parametrize to change it."""
    return {"QLD_PW011", "QLD_ME008", "QLD_RC167"}


@pytest.fixture
def resolve(fake_bom: FakeBom, resolved_codes: set[str]) -> Iterator[MagicMock]:
    with patch(
        "custom_components.bom_warnings.config_flow.resolve_coordinate",
        return_value=resolved_codes,
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
def no_entry_setup() -> Iterator[None]:
    """These tests are about the flow, not about polling after it."""
    with patch("custom_components.bom_warnings.async_setup_entry", return_value=True):
        yield


async def start_manual(hass: HomeAssistant, user_input: dict[str, Any]) -> Any:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def start_home(hass: HomeAssistant) -> Any:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "home"}
    )


async def test_home_location(hass: HomeAssistant, resolve: MagicMock) -> None:
    await hass.config.async_update(latitude=-27.4698, longitude=153.0251, location_name="Casa")

    result = await start_home(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Casa"
    assert result["result"].unique_id == "-27.470,153.025"
    assert result["data"] == {
        CONF_LATITUDE: -27.4698,
        CONF_LONGITUDE: 153.0251,
        CONF_STATE: "QLD",
        CONF_AREA_CODES: ["QLD_ME008", "QLD_PW011", "QLD_RC167"],
    }
    assert resolve.call_args.kwargs == {"lat": -27.4698, "lon": 153.0251}
    # The cache lives under the config directory, so it survives restarts.
    assert Path(resolve.call_args.args[1]).is_relative_to(hass.config.path())


async def test_manual_location(hass: HomeAssistant, resolve: MagicMock) -> None:
    result = await start_manual(hass, BRISBANE)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "-27.470, 153.025"
    assert result["result"].unique_id == "-27.470,153.025"


async def test_manual_form_has_no_name_field(hass: HomeAssistant, resolve: MagicMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )

    assert {str(key) for key in result["data_schema"].schema} == {"latitude", "longitude"}


@pytest.mark.parametrize("resolved_codes", [set()])
async def test_manual_location_with_no_area(hass: HomeAssistant, resolve: MagicMock) -> None:
    result = await start_manual(hass, {CONF_LATITUDE: -33.0, CONF_LONGITUDE: 100.0})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_area"}

    # The user can correct the coordinates in the same flow.
    resolve.return_value = {"NSW_PW001"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], BRISBANE)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STATE] == "NSW"


@pytest.mark.parametrize("resolved_codes", [set()])
async def test_home_location_with_no_area_aborts(hass: HomeAssistant, resolve: MagicMock) -> None:
    result = await start_home(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_area"


@pytest.mark.parametrize(
    "error", [BomFtpError("down"), SpatialDataError("corrupt"), OSError("disk")]
)
async def test_cannot_connect(hass: HomeAssistant, resolve: MagicMock, error: Exception) -> None:
    resolve.side_effect = error

    result = await start_manual(hass, BRISBANE)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_unexpected_error(hass: HomeAssistant, resolve: MagicMock) -> None:
    resolve.side_effect = ValueError("bug")

    result = await start_manual(hass, BRISBANE)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_duplicate_location_is_rejected(hass: HomeAssistant, resolve: MagicMock) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="-27.470,153.025", data={}).add_to_hass(hass)

    # Different raw coordinates that round to the same unique_id.
    result = await start_manual(hass, {CONF_LATITUDE: -27.4701, CONF_LONGITUDE: 153.0249})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("resolved_codes", "state"),
    [
        ({"QLD_PW011", "QLD_ME008"}, "QLD"),
        ({"ACT_PW001"}, "ACT"),
        ({"NSW_RC031"}, "NSW"),  # no forecast district: fall back to any area's prefix
    ],
)
async def test_state_comes_from_the_forecast_district(
    hass: HomeAssistant, resolve: MagicMock, state: str
) -> None:
    result = await start_manual(hass, BRISBANE)

    assert result["data"][CONF_STATE] == state
