"""The warning event entity, driven through Home Assistant against the fake BoM FTP server."""

import os
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import CONF_AREA_CODES, CONF_WARNING_TYPES, DOMAIN
from scripts.fake_bom import layout, scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .locations import location_of
from .test_binary_sensor import poll, setup_entry
from .test_options import layers  # noqa: F401
from .test_zones import change_zone, set_zone, zone_codes, zone_entry, zone_options  # noqa: F401

ENTITY_ID = "event.home_warning_event"
THUNDERSTORM = "IDQ21035.cap.xml"

pytestmark = pytest.mark.freeze_time(NOW)


@pytest.fixture
def area_codes() -> list[str]:
    """The Brisbane metro area, covered by the baseline thunderstorm warning."""
    return ["QLD_ME008"]


def reissue(fake_bom: FakeBom, edit: Callable[[str], str]) -> None:
    """Rewrite the recorded thunderstorm file the way BoM reissues it, with a later mtime."""
    path = fake_bom.root / layout.WARNINGS / THUNDERSTORM
    path.write_text(edit(path.read_text()))
    later = layout.BASE_TIME + 3600
    os.utime(path, (later, later))


def newer_issue(text: str) -> str:
    return text.replace("2026-11-01T06:03:58", "2026-11-01T07:03:58")


def final(text: str) -> str:
    return newer_issue(text).replace("<headline>", "<headline>Final ")


def cancelled(text: str) -> str:
    return (
        newer_issue(text)
        .replace("<msgType>Update", "<msgType>Cancel")
        .replace("<headline>", "<headline>Cancellation of ")
    )


@pytest.fixture
def fired(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Attributes of every event the entity fires (a new event changes the entity's state)."""
    events: list[dict[str, Any]] = []

    @callback
    def record(event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if (
            new is not None
            and new.attributes.get("event_type")
            and old is not None
            and old.state not in (STATE_UNAVAILABLE, new.state)  # a restore is not an event
        ):
            events.append(dict(new.attributes))

    @callback
    def only_entity(data: EventStateChangedData) -> bool:
        return data["entity_id"] == ENTITY_ID

    hass.bus.async_listen(EVENT_STATE_CHANGED, record, event_filter=only_entity)
    return events


async def test_no_event_for_warning_present_at_startup(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    fired: list[dict[str, Any]],
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await poll(hass, freezer)
    await poll(hass, freezer)

    assert fired == []
    assert hass.states.get(ENTITY_ID) is not None


@pytest.mark.parametrize("area_codes", [["QLD_PW001"]])
async def test_new_warning_fires_once_with_details(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    fired: list[dict[str, Any]],
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)

    scenarios.apply("warning_appears", fake_bom.root)
    await poll(hass, freezer)
    await poll(hass, freezer)  # unchanged on a later refresh

    [event] = fired
    assert event["event_type"] == "new"
    assert event["product_id"] == "IDQ21013"
    assert event["severity"] == "severe"
    assert event["headline"] == "Severe heatwave warning for Queensland"
    assert event["event"] == "Extreme Heat"


async def test_update_then_final_then_cancelled_each_fire_once(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    fired: list[dict[str, Any]],
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)

    reissue(fake_bom, newer_issue)
    await poll(hass, freezer)
    await poll(hass, freezer)
    assert [e["event_type"] for e in fired] == ["update"]

    reissue(fake_bom, final)
    await poll(hass, freezer)
    assert [e["event_type"] for e in fired] == ["update", "final"]

    reissue(fake_bom, cancelled)
    await poll(hass, freezer)
    await poll(hass, freezer)
    assert [e["event_type"] for e in fired] == ["update", "final", "cancelled"]
    assert {e["product_id"] for e in fired} == {"IDQ21035"}


async def test_rewritten_file_with_same_content_fires_nothing(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    fired: list[dict[str, Any]],
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)

    scenarios.apply("warning_updated", fake_bom.root)
    await poll(hass, freezer)

    assert fired == []


async def test_cancellation_fires_once_and_not_again_after_a_reload(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    fired: list[dict[str, Any]],
    freezer: Any,
) -> None:
    # A warning the entry has already seen as current, which is what a cancellation ends.
    await setup_entry(hass, mock_config_entry)

    reissue(fake_bom, cancelled)
    await poll(hass, freezer)
    await poll(hass, freezer)
    [event] = fired
    assert event["event_type"] == "cancelled"
    assert event["product_id"] == "IDQ21035"

    # A restart while the cancel file is still served must not repeat it.
    fired.clear()
    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await poll(hass, freezer)
    assert fired == []


async def test_warning_that_disappears_fires_nothing(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    fired: list[dict[str, Any]],
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)

    (fake_bom.root / layout.WARNINGS / THUNDERSTORM).unlink()
    await poll(hass, freezer)

    assert fired == []


@pytest.mark.parametrize(
    ("warning_types", "expected"),
    [
        # hide_final defaults to on, yet final and cancelled are the events themselves.
        (["thunderstorm_warning"], ["final", "cancelled"]),
        (None, ["final", "cancelled"]),
        (["extreme_heat_warning"], []),
    ],
    ids=["type-on", "every-type-on", "other-type-only"],
)
async def test_the_type_checklist_decides_which_events_fire(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    fired: list[dict[str, Any]],
    freezer: Any,
    warning_types: list[str] | None,
    expected: list[str],
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={} if warning_types is None else {CONF_WARNING_TYPES: warning_types},
    )
    await setup_entry(hass, mock_config_entry)

    reissue(fake_bom, final)
    await poll(hass, freezer)
    reissue(fake_bom, cancelled)
    await poll(hass, freezer)

    assert [e["event_type"] for e in fired] == expected


def event_state(hass: HomeAssistant, entry: MockConfigEntry) -> State:
    """The event entity's state, found by its unique id and not by a guessed entity id."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("event", DOMAIN, f"{entry.unique_id}_warning_event")
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    return state


async def test_a_cancelled_product_first_covered_by_a_move_fires_nothing(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
) -> None:
    # The cancel file is served throughout. The entry's area does not include its district yet.
    scenarios.apply("warning_cancelled", fake_bom.root)
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    resolve.return_value = location_of("QLD_PW001", "NSW_MW001")
    await change_zone(hass, lat=-30.0)

    # The move took effect, and the warning it now covers was never in this entry's area as
    # anything but already cancelled, so there is nothing to report. Read the entity itself: the
    # `fired` recorder above missed an event the entity had fired.
    assert zone_entry.data[CONF_AREA_CODES] == ["NSW_MW001", "QLD_PW001"]
    state = event_state(hass, zone_entry)
    assert state.state == STATE_UNKNOWN
    assert state.attributes.get("event_type") is None


async def test_a_current_warning_first_covered_by_a_move_still_fires_new(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,
) -> None:
    set_zone(hass)
    await setup_entry(hass, zone_entry)

    # The baseline thunderstorm warning covers this district, and it is current.
    resolve.return_value = location_of("QLD_PW001", "QLD_ME008")
    await change_zone(hass, lat=-28.0)

    state = event_state(hass, zone_entry)
    assert state.attributes["event_type"] == "new"
    assert state.attributes["product_id"] == "IDQ21035"


async def test_a_warning_that_drops_out_of_the_feed_still_reports_its_cancellation(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    fired: list[dict[str, Any]],
    freezer: Any,
) -> None:
    path = fake_bom.root / layout.WARNINGS / THUNDERSTORM
    seen = path.read_text()
    await setup_entry(hass, mock_config_entry)

    # The file is missing for one refresh, then served again as the cancellation of a warning
    # this entry had seen as current. It was reported then, and its end is still owed.
    path.unlink()
    await poll(hass, freezer)
    path.write_text(cancelled(seen))
    later = layout.BASE_TIME + 3600
    os.utime(path, (later, later))
    await poll(hass, freezer)
    await poll(hass, freezer)

    assert [e["event_type"] for e in fired] == ["cancelled"]
    assert {e["product_id"] for e in fired} == {"IDQ21035"}
