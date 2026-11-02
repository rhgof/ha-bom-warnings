"""Entries that follow a Home Assistant zone, driven through Home Assistant.

As in test_options, the shapefiles are not in the repo, so `resolve_coordinate` is the one seam
(as the coordinator imports it) and tests say which area codes a circle resolves to. The zone
itself is a plain state, which is all a zone is to the integration.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    CONF_AREA_CODES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_STATE,
    CONF_ZONE,
    DOMAIN,
    MAX_RADIUS_M,
)
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import poll, setup_entry
from .test_options import layers, resolve, set_options  # noqa: F401

pytestmark = pytest.mark.freeze_time(NOW)

ZONE = "zone.holiday"
SENSOR = "binary_sensor.holiday_house_warning"


def set_zone(
    hass: HomeAssistant,
    lat: float = -27.47,
    lon: float = 153.021,
    radius: float = 2000.0,
    entity_id: str = ZONE,
) -> None:
    hass.states.async_set(
        entity_id,
        "0",
        {
            "friendly_name": "Holiday house",
            "latitude": lat,
            "longitude": lon,
            "radius": radius,
            "passive": False,
        },
    )


@pytest.fixture
def zone_codes() -> list[str]:
    return ["QLD_PW001"]


@pytest.fixture
def zone_options() -> dict[str, Any]:
    return {}


@pytest.fixture
def zone_entry(zone_codes: list[str], zone_options: dict[str, Any]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=3,
        unique_id=ZONE,
        title="Holiday house",
        options=zone_options,
        data={
            CONF_ZONE: ZONE,
            CONF_LATITUDE: -27.47,
            CONF_LONGITUDE: 153.021,
            CONF_RADIUS: 2000.0,
            CONF_STATE: zone_codes[0].split("_")[0],
            CONF_AREA_CODES: zone_codes,
        },
    )


def issue(hass: HomeAssistant, entry: MockConfigEntry, kind: str) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{kind}_{entry.entry_id}")


async def change_zone(hass: HomeAssistant, **kwargs: Any) -> None:
    set_zone(hass, **kwargs)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_unchanged_zone_does_not_re_resolve(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    # The zone's state changes whenever someone enters it, which says nothing about its shape.
    hass.states.async_set(ZONE, "2", dict(hass.states.get(ZONE).attributes))  # type: ignore[union-attr]
    await hass.async_block_till_done(wait_background_tasks=True)

    resolve.assert_not_called()
    assert hass.states.get(SENSOR).state == STATE_OFF  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"lat": -33.87, "lon": 151.21}, {"lat": -33.87, "lon": 151.21, "radius_m": 2000.0}),
        ({"radius": 15_000.0}, {"lat": -27.47, "lon": 153.021, "radius_m": 15_000.0}),
        (
            {"lat": -33.87, "lon": 151.21, "radius": 500.0},
            {"lat": -33.87, "lon": 151.21, "radius_m": 500.0},
        ),
    ],
    ids=["moved", "resized", "both"],
)
async def test_editing_the_zone_re_resolves_without_a_restart(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
    change: dict[str, float],
    expected: dict[str, float],
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)
    assert hass.states.get(SENSOR).state == STATE_OFF  # type: ignore[union-attr]

    # The new circle also touches the thunderstorm district, which has a recorded warning.
    resolve.return_value = {"QLD_PW001", "QLD_ME008"}
    await change_zone(hass, **change)

    assert resolve.call_args.kwargs == expected
    assert zone_entry.data[CONF_LATITUDE] == expected["lat"]
    assert zone_entry.data[CONF_LONGITUDE] == expected["lon"]
    assert zone_entry.data[CONF_RADIUS] == expected["radius_m"]
    assert zone_entry.data[CONF_AREA_CODES] == ["QLD_ME008", "QLD_PW001"]
    assert hass.states.get(SENSOR).state == STATE_ON  # type: ignore[union-attr]


@pytest.mark.parametrize("zone_codes", [["QLD_ME008", "QLD_PW001"]])
async def test_shrinking_the_zone_drops_an_area(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)
    assert hass.states.get(SENSOR).state == STATE_ON  # type: ignore[union-attr]

    resolve.return_value = {"QLD_PW001"}
    await change_zone(hass, radius=100.0)

    assert hass.states.get(SENSOR).state == STATE_OFF  # type: ignore[union-attr]


async def test_zone_edited_while_home_assistant_was_down_is_picked_up_at_start(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    set_zone(hass, lat=-33.87, lon=151.21, radius=9_000.0)

    await setup_entry(hass, zone_entry)

    assert resolve.call_args.kwargs == {"lat": -33.87, "lon": 151.21, "radius_m": 9_000.0}
    assert zone_entry.data[CONF_RADIUS] == 9_000.0


async def test_zone_with_no_area_raises_the_repair_and_keeps_the_codes(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    resolve.return_value = set()
    await change_zone(hass, lat=-40.0, lon=100.0)

    found = issue(hass, zone_entry, "no_area")
    assert found is not None
    assert found.translation_key == "no_area"
    assert zone_entry.data[CONF_AREA_CODES] == ["QLD_PW001"]
    assert hass.states.get(SENSOR).state == STATE_OFF  # type: ignore[union-attr]


async def test_failed_re_resolve_is_retried_on_the_next_poll(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    from custom_components.bom_warnings.ftp import BomFtpError

    from .test_binary_sensor import poll

    set_zone(hass)
    await setup_entry(hass, zone_entry)

    resolve.side_effect = BomFtpError("offline")
    await change_zone(hass, radius=7_000.0)
    assert zone_entry.data[CONF_AREA_CODES] == ["QLD_PW001"]

    resolve.side_effect = None
    resolve.return_value = {"QLD_ME008", "QLD_PW001"}
    await poll(hass, freezer)

    assert zone_entry.data[CONF_AREA_CODES] == ["QLD_ME008", "QLD_PW001"]


@pytest.mark.parametrize(
    ("radius", "stored", "clamped"),
    [
        (2_000.0, 2_000.0, False),
        (MAX_RADIUS_M, MAX_RADIUS_M, False),
        (80_000.0, MAX_RADIUS_M, True),
    ],
)
async def test_radius_above_the_cap_is_clamped_and_explained(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
    radius: float,
    stored: float,
    clamped: bool,
) -> None:
    set_zone(hass, radius=radius)
    await setup_entry(hass, zone_entry)

    assert zone_entry.data[CONF_RADIUS] == stored
    found = issue(hass, zone_entry, "radius_clamped")
    assert (found is not None) is clamped
    if found:
        assert found.is_fixable is False
        assert found.translation_placeholders == {
            "title": "Holiday house",
            "radius": "80",
            "max": "50",
        }


async def test_shrinking_an_oversized_zone_clears_the_notice(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    set_zone(hass, radius=80_000.0)
    await setup_entry(hass, zone_entry)
    assert issue(hass, zone_entry, "radius_clamped") is not None

    await change_zone(hass, radius=30_000.0)

    assert issue(hass, zone_entry, "radius_clamped") is None
    assert zone_entry.data[CONF_RADIUS] == 30_000.0


@pytest.mark.parametrize("zone_codes", [["QLD_ME008", "QLD_PW001"]])
async def test_deleting_the_zone_raises_a_repair_and_the_entry_keeps_working(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    hass.states.async_remove(ZONE)
    await hass.async_block_till_done(wait_background_tasks=True)

    found = issue(hass, zone_entry, "zone_removed")
    assert found is not None
    assert found.is_fixable is False
    assert found.translation_placeholders == {"title": "Holiday house", "zone": ZONE}
    assert zone_entry.data[CONF_AREA_CODES] == ["QLD_ME008", "QLD_PW001"]
    assert hass.states.get(SENSOR).state == STATE_ON  # type: ignore[union-attr]
    resolve.assert_not_called()


async def test_recreating_the_zone_clears_the_repair(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)
    hass.states.async_remove(ZONE)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert issue(hass, zone_entry, "zone_removed") is not None

    await change_zone(hass, lat=-33.87, lon=151.21)

    assert issue(hass, zone_entry, "zone_removed") is None
    assert resolve.call_args.kwargs["lat"] == -33.87


async def test_zone_missing_at_start_raises_the_repair(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    await setup_entry(hass, zone_entry)

    assert issue(hass, zone_entry, "zone_removed") is not None
    assert hass.states.get(SENSOR) is not None


async def test_unloaded_entry_stops_following_the_zone(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)
    assert await hass.config_entries.async_unload(zone_entry.entry_id)

    await change_zone(hass, radius=9_000.0)

    resolve.assert_not_called()
    assert zone_entry.data[CONF_RADIUS] == 2000.0


async def test_removing_the_entry_removes_its_repairs(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    set_zone(hass, radius=80_000.0)
    await setup_entry(hass, zone_entry)
    hass.states.async_remove(ZONE)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert issue(hass, zone_entry, "radius_clamped") is not None
    assert issue(hass, zone_entry, "zone_removed") is not None

    await hass.config_entries.async_remove(zone_entry.entry_id)

    for kind in ("radius_clamped", "zone_removed", "no_area"):
        assert issue(hass, zone_entry, kind) is None


# Coastal-water warnings from BoM's samples. The zone's codes are what its circle resolved to:
# one land district plus the water zone the radius reaches. Marine wind has both a gale
# (Moderate) and a storm (Severe) block, and the gale must alert too.
MARINE = [
    (["NT_PW999", "NT_MW002"], "IDD20105", "Wind", "moderate"),
    (["NT_PW999", "NT_MW004"], "IDD20105", "Wind", "severe"),
    (["NSW_PW999", "NSW_MW008"], "IDN28522", "Large Coastal Surf", "moderate"),
    (["NSW_PW999", "NSW_MW007"], "IDN28522", "Large Coastal Surf", "moderate"),
]


def warnings_of(hass: HomeAssistant, entity_id: str = SENSOR) -> list[dict[str, Any]]:
    state = hass.states.get(entity_id)
    assert state is not None
    return list(state.attributes["warnings"])


MARINE_TOGGLE = {"Wind": "marine_wind_warning", "Large Coastal Surf": "hazardous_surf_warning"}


@pytest.mark.parametrize(
    ("zone_codes", "product_id", "event", "severity"),
    MARINE,
    ids=[f"{codes[1]}-{event}" for codes, _, event, _ in MARINE],
)
async def test_coastal_waters_in_the_circle_alert_while_their_type_is_on(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
    product_id: str,
    event: str,
    severity: str,
) -> None:
    scenarios.apply("all_types", fake_bom.root)
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    assert hass.states.get(SENSOR).state == STATE_ON  # type: ignore[union-attr]
    listed = [w for w in warnings_of(hass) if w["product_id"] == product_id]
    assert listed
    assert {w["event"] for w in listed} == {event}
    assert severity in {w["severity"] for w in listed}
    assert hass.states.get("sensor.holiday_house_warning_count").state != "0"  # type: ignore[union-attr]

    await set_options(hass, zone_entry, **{MARINE_TOGGLE[event]: False})

    assert hass.states.get(SENSOR).state == STATE_OFF  # type: ignore[union-attr]
    assert hass.states.get("sensor.holiday_house_warning_count").state == "0"  # type: ignore[union-attr]
    # Toggling is a reload, not a new look at the shapefiles.
    resolve.assert_not_called()


@pytest.mark.parametrize("zone_codes", [["NT_PW999", "NT_MW004"]])
async def test_marine_warning_reaches_the_event_entity_and_ranking(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    scenarios.apply("all_types", fake_bom.root)
    await poll(hass, freezer)

    top = hass.states.get("sensor.holiday_house_most_severe_warning")
    assert top is not None
    assert top.attributes["warnings"][0]["event"] == "Wind"
    event = hass.states.get("event.holiday_house_warning_event")
    assert event is not None
    assert event.attributes["event_type"] in {"new", "update"}
    assert event.attributes["event"] == "Wind"


@pytest.mark.parametrize("zone_codes", [["NT_PT007"]])
async def test_cyclone_codes_match_by_code_though_no_layer_produces_them(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
) -> None:
    """`PT` (cyclone place) codes exist in the file but in none of the layers: a known gap, #26."""
    scenarios.apply("all_types", fake_bom.root)
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    assert {w["event"] for w in warnings_of(hass)} == {"Tropical Cyclone"}


async def test_entry_stored_before_marine_existed_keeps_working(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
) -> None:
    """Home and manual entries have no radius, no zone and no marine option."""
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get("binary_sensor.home_warning").state == STATE_OFF  # type: ignore[union-attr]


async def test_diagnostics_do_not_expose_the_zone(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
) -> None:
    from custom_components.bom_warnings.diagnostics import async_get_config_entry_diagnostics

    set_zone(hass)
    await setup_entry(hass, zone_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, zone_entry)

    text = str(diagnostics)
    for secret in ("-27.47", "153.021", ZONE, "Holiday house", "holiday"):
        assert secret not in text
    assert diagnostics["entry"]["data"]["radius"] == 2000.0
    assert diagnostics["entry"]["data"]["area_codes"] == ["QLD_PW001"]
