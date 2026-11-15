"""Moving a zone entry to another zone, without losing its entities.

An entry's unique id is the zone it was made from, and its device and entity ids are built from
that. Reconfiguring must therefore leave the unique id alone, or every entity would be recreated
under a new id and dashboards and automations would break.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_WARNING_RADIUS,
    CONF_ZONE,
    DOMAIN,
)
from custom_components.bom_warnings.location import LocationUnavailable
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .locations import location_of
from .test_binary_sensor import setup_entry
from .test_options import layers  # noqa: F401
from .test_zones import ZONE, set_zone, zone_codes, zone_entry, zone_options  # noqa: F401

pytestmark = pytest.mark.freeze_time(NOW)

HOME = "zone.home"


@pytest.fixture(autouse=True)
def zones(hass: HomeAssistant) -> None:
    set_zone(hass, radius=2000.0)
    set_zone(hass, entity_id=HOME, lat=-33.87, lon=151.21, radius=100.0, name="Home")


def entity_ids(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, str]:
    registry = er.async_get(hass)
    return {
        entity.unique_id: entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }


async def reconfigure(hass: HomeAssistant, entry: MockConfigEntry, zone: str) -> Any:
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    return await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_ZONE: zone})


async def test_reconfigure_follows_the_new_zone_and_keeps_every_entity_id(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
) -> None:
    await setup_entry(hass, zone_entry)
    before = entity_ids(hass, zone_entry)
    assert before
    resolve.return_value = location_of("NSW_PW001")

    result = await reconfigure(hass, zone_entry, HOME)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert zone_entry.unique_id == ZONE
    assert zone_entry.data[CONF_ZONE] == HOME
    assert zone_entry.data[CONF_LATITUDE] == -33.87
    assert zone_entry.data[CONF_LONGITUDE] == 151.21
    # The new zone's own radius (100 m) is not used: the entry keeps its warning radius.
    assert zone_entry.data[CONF_RADIUS] == 2000.0
    assert resolve.call_args.kwargs == {"lat": -33.87, "lon": 151.21, "radius_m": 2000.0}
    assert entity_ids(hass, zone_entry) == before
    assert zone_entry.title == "Home"


@pytest.mark.parametrize("zone_options", [{CONF_WARNING_RADIUS: 10.0}])
async def test_reconfigure_keeps_the_warning_radius(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
) -> None:
    await setup_entry(hass, zone_entry)

    await reconfigure(hass, zone_entry, HOME)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert zone_entry.data[CONF_RADIUS] == 10_000.0
    assert resolve.call_args.kwargs["radius_m"] == 10_000.0


async def test_a_zone_another_entry_follows_is_refused(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
) -> None:
    other = MockConfigEntry(
        domain=DOMAIN,
        version=4,
        unique_id=HOME,
        title="Home",
        data={**zone_entry.data, CONF_ZONE: HOME},
    )
    other.add_to_hass(hass)
    zone_entry.add_to_hass(hass)

    result = await reconfigure(hass, zone_entry, HOME)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "zone_already_followed"}
    assert zone_entry.data[CONF_ZONE] == ZONE


@pytest.mark.parametrize(
    ("setup", "error"),
    [
        ("missing", "zone_not_found"),
        ("unreachable", "cannot_connect"),
        ("no_area", "no_area"),
    ],
)
async def test_a_failed_reconfigure_shows_the_error_and_changes_nothing(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    resolve: MagicMock,
    setup: str,
    error: str,
) -> None:
    zone_entry.add_to_hass(hass)
    before = dict(zone_entry.data)
    target = HOME
    if setup == "missing":
        target = "zone.nowhere"
    elif setup == "unreachable":
        resolve.side_effect = LocationUnavailable("down")
    else:
        resolve.return_value = location_of()

    result = await reconfigure(hass, zone_entry, target)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert dict(zone_entry.data) == before


async def test_only_zone_entries_can_be_reconfigured(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_a_zone_entry"
