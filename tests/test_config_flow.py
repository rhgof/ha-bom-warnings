"""The config flow, driven through Home Assistant.

The shapefiles are not in the repo, so the one seam is `location.resolve_location` (the shared
`resolve` fixture): tests decide which location a point resolves to. Everything else (the FTP client
built from the environment, the executor hop, the entry) is real, against the fake BoM server.
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
    CONF_AREA_NAMES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_STATE,
    CONF_ZONE,
    DOMAIN,
    MAX_RADIUS_M,
)
from custom_components.bom_warnings.location import LocationUnavailable, ResolvedLocation
from scripts.fake_bom.server import FakeBom

BRISBANE = {CONF_LATITUDE: -27.4698, CONF_LONGITUDE: 153.0251}
# What the `resolve` fixture says the point is in, by code.
RESOLVED_NAMES = {
    "QLD_PW011": "Moreton Bay",
    "QLD_ME008": "Brisbane",
    "QLD_RC167": "Brisbane River",
}


@pytest.fixture(autouse=True)
def no_network(fake_bom: FakeBom) -> None:
    """A call that escapes the `resolve` mock reaches the fake server, never BoM."""


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
        CONF_AREA_NAMES: RESOLVED_NAMES,
    }
    assert resolve.call_args.kwargs == {"lat": -27.4698, "lon": 153.0251, "radius_m": 0.0}
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
    resolve.return_value = ResolvedLocation(frozenset({"NSW_PW001"}), "NSW")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], BRISBANE)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STATE] == "NSW"


@pytest.mark.parametrize("resolved_codes", [set()])
async def test_home_location_with_no_area_aborts(hass: HomeAssistant, resolve: MagicMock) -> None:
    result = await start_home(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_area"


async def test_cannot_connect(hass: HomeAssistant, resolve: MagicMock) -> None:
    resolve.side_effect = LocationUnavailable("down")

    result = await start_manual(hass, BRISBANE)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_unexpected_error(
    hass: HomeAssistant, resolve: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    resolve.side_effect = ValueError("bug")

    result = await start_manual(hass, BRISBANE)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}
    # Flow errors map to a translated key and are not logged.
    assert not [r for r in caplog.records if r.name.startswith("custom_components.bom_warnings")]


async def test_duplicate_location_is_rejected(hass: HomeAssistant, resolve: MagicMock) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="-27.470,153.025", data={}).add_to_hass(hass)

    # Different raw coordinates that round to the same unique_id.
    result = await start_manual(hass, {CONF_LATITUDE: -27.4701, CONF_LONGITUDE: 153.0249})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("resolved_codes", "resolved_state"), [({"ACT_PW001"}, "ACT"), ({"NSW_RC031"}, "NSW")]
)
async def test_state_is_the_one_the_resolver_found(
    hass: HomeAssistant, resolve: MagicMock, resolved_state: str
) -> None:
    result = await start_manual(hass, BRISBANE)

    assert result["data"][CONF_STATE] == resolved_state


def set_zone(
    hass: HomeAssistant, entity_id: str = "zone.holiday", name: str = "Holiday house", **extra: Any
) -> None:
    attributes = {
        "friendly_name": name,
        "latitude": -33.8688,
        "longitude": 151.2093,
        "radius": 2000.0,
        "passive": False,
        **extra,
    }
    hass.states.async_set(entity_id, "0", attributes)


async def start_zone(hass: HomeAssistant, entity_id: str = "zone.holiday", **choices: Any) -> Any:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "zone"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zone"
    return await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_ZONE: entity_id})


async def test_menu_offers_zones_only_when_there_are_some(hass: HomeAssistant) -> None:
    set_zone(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert "zone" in result["menu_options"]
    assert {"home", "manual"} <= set(result["menu_options"])

    for entity_id in hass.states.async_entity_ids("zone"):
        hass.states.async_remove(entity_id)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["menu_options"] == ["home", "manual"]


async def test_zone_creates_an_entry_that_follows_it(
    hass: HomeAssistant, resolve: MagicMock
) -> None:
    set_zone(hass)

    result = await start_zone(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Holiday house"
    assert result["result"].unique_id == "zone.holiday"
    assert result["data"] == {
        CONF_ZONE: "zone.holiday",
        CONF_LATITUDE: -33.8688,
        CONF_LONGITUDE: 151.2093,
        CONF_RADIUS: 2000.0,
        CONF_STATE: "QLD",
        CONF_AREA_CODES: ["QLD_ME008", "QLD_PW011", "QLD_RC167"],
        CONF_AREA_NAMES: RESOLVED_NAMES,
    }
    assert resolve.call_args.kwargs == {"lat": -33.8688, "lon": 151.2093, "radius_m": 2000.0}


@pytest.mark.parametrize(
    ("radius", "stored"),
    [
        (100, 100),
        (MAX_RADIUS_M, MAX_RADIUS_M),
        (MAX_RADIUS_M + 1, MAX_RADIUS_M),
        (900_000, MAX_RADIUS_M),
    ],
)
async def test_radius_is_capped(
    hass: HomeAssistant, resolve: MagicMock, radius: float, stored: float
) -> None:
    set_zone(hass, radius=radius)

    result = await start_zone(hass)

    assert result["data"][CONF_RADIUS] == stored
    assert resolve.call_args.kwargs["radius_m"] == stored


async def test_the_same_zone_cannot_be_added_twice(hass: HomeAssistant, resolve: MagicMock) -> None:
    set_zone(hass)
    assert (await start_zone(hass))["type"] is FlowResultType.CREATE_ENTRY

    result = await start_zone(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_two_zones_at_the_same_place_are_allowed(
    hass: HomeAssistant, resolve: MagicMock
) -> None:
    set_zone(hass, "zone.holiday", "Holiday house")
    set_zone(hass, "zone.beach", "Beach")

    first = await start_zone(hass, "zone.holiday")
    second = await start_zone(hass, "zone.beach")

    assert first["type"] is second["type"] is FlowResultType.CREATE_ENTRY


async def test_zone_beside_a_home_entry_at_the_same_place_is_allowed(
    hass: HomeAssistant, resolve: MagicMock
) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="-33.869,151.209", data={}).add_to_hass(hass)
    set_zone(hass)

    assert (await start_zone(hass))["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize("resolved_codes", [set()])
async def test_zone_with_no_area_shows_an_error(hass: HomeAssistant, resolve: MagicMock) -> None:
    set_zone(hass)

    result = await start_zone(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_area"}


async def test_zone_that_disappeared_shows_an_error(
    hass: HomeAssistant, resolve: MagicMock
) -> None:
    set_zone(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "zone"}
    )
    hass.states.async_remove("zone.holiday")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ZONE: "zone.holiday"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "zone_not_found"}
    resolve.assert_not_called()


@pytest.mark.parametrize(
    ("error", "key"),
    [(LocationUnavailable("down"), "cannot_connect"), (RuntimeError("boom"), "unknown")],
)
async def test_zone_errors_use_the_standard_keys(
    hass: HomeAssistant, resolve: MagicMock, error: Exception, key: str
) -> None:
    resolve.side_effect = error
    set_zone(hass)

    result = await start_zone(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}
