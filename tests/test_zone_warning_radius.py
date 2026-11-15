"""A zone entry's warning radius: how far around the zone's centre to look.

It is the entry's own option and is kept apart from the zone's radius, which is sized for presence
detection. Driven through Home Assistant like test_zones, with `location.resolve_location` as the
one seam.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    CONF_HIDE_FINAL,
    CONF_RADIUS,
    CONF_WARNING_RADIUS,
    DOMAIN,
)
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import setup_entry
from .test_options import layers, set_options  # noqa: F401
from .test_zones import (  # noqa: F401
    change_zone,
    set_zone,
    zone_codes,
    zone_entry,
    zone_options,
)

pytestmark = pytest.mark.freeze_time(NOW)


async def test_the_warning_radius_not_the_zones_own_sets_the_circle(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
) -> None:
    set_zone(hass, radius=2000.0)
    await setup_entry(hass, zone_entry)
    resolve.reset_mock()

    await set_options(hass, zone_entry, **{CONF_WARNING_RADIUS: 15})
    await hass.async_block_till_done(wait_background_tasks=True)

    assert resolve.call_args.kwargs == {"lat": -27.47, "lon": 153.021, "radius_m": 15_000.0}
    assert zone_entry.data[CONF_RADIUS] == 15_000.0


async def test_resizing_the_zone_changes_nothing(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
) -> None:
    set_zone(hass, radius=2000.0)
    await setup_entry(hass, zone_entry)
    resolve.reset_mock()

    await change_zone(hass, radius=30_000.0)

    resolve.assert_not_called()
    assert zone_entry.data[CONF_RADIUS] == 2000.0


@pytest.mark.parametrize("zone_options", [{CONF_WARNING_RADIUS: 10.0}])
async def test_saving_other_options_keeps_the_warning_radius(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    await set_options(hass, zone_entry, **{CONF_HIDE_FINAL: False})

    assert zone_entry.options[CONF_WARNING_RADIUS] == 10.0
    assert zone_entry.options[CONF_HIDE_FINAL] is False


async def test_only_zone_entries_are_offered_the_warning_radius(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
) -> None:
    async def offered(entry: MockConfigEntry) -> dict[str, Any]:
        entry.add_to_hass(hass)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        return {str(key): key for key in result["data_schema"].schema}

    zone_fields = await offered(zone_entry)
    home_fields = await offered(mock_config_entry)

    assert zone_fields[CONF_WARNING_RADIUS].default() == 2.0
    assert CONF_WARNING_RADIUS not in home_fields


@pytest.mark.parametrize("radius_km", [-1, 50.1])
async def test_the_options_form_refuses_a_radius_outside_the_limits(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
    radius_km: float,
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)
    result = await hass.config_entries.options.async_init(zone_entry.entry_id)

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_WARNING_RADIUS: radius_km}
        )


@pytest.mark.parametrize(
    ("radius_m", "radius_km"),
    [(15_000.0, 15.0), (2_500.0, 2.5), (100.0, 0.1), (0.0, 0.0), (80_000.0, 50.0)],
)
async def test_a_zone_entry_from_before_keeps_the_radius_it_was_looking(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
    radius_m: float,
    radius_km: float,
) -> None:
    """Version 3 used the zone's radius, so the option starts as what that was."""
    old = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        unique_id=zone_entry.unique_id,
        title=zone_entry.title,
        data={**zone_entry.data, CONF_RADIUS: radius_m},
    )
    set_zone(hass, radius=radius_m)
    await setup_entry(hass, old)

    assert old.state is ConfigEntryState.LOADED
    assert old.version == 4
    assert old.options[CONF_WARNING_RADIUS] == radius_km
    assert old.data[CONF_RADIUS] == radius_km * 1000


async def test_a_home_entry_from_before_gets_no_warning_radius(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
) -> None:
    old = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        unique_id=mock_config_entry.unique_id,
        title=mock_config_entry.title,
        data=dict(mock_config_entry.data),
    )

    await setup_entry(hass, old)

    assert old.version == 4
    assert CONF_WARNING_RADIUS not in old.options
