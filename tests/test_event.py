"""The warning event entity, driven through Home Assistant against the fake BoM FTP server."""

import os
from collections.abc import Callable
from typing import Any

import pytest
from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import CONF_EVENT_TYPES, CONF_INCLUDE_MARINE
from scripts.fake_bom import layout, scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import poll, setup_entry

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


@pytest.mark.parametrize("area_codes", [["NSW_MW001"]])
@pytest.mark.parametrize("entry_options", [{CONF_INCLUDE_MARINE: True}])
async def test_cancellation_fires_once_and_not_again_after_a_reload(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    fired: list[dict[str, Any]],
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)

    scenarios.apply("warning_cancelled", fake_bom.root)
    await poll(hass, freezer)
    await poll(hass, freezer)
    [event] = fired
    assert event["event_type"] == "cancelled"
    assert event["product_id"] == "IDN20400"

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
    ("event_types", "expected"),
    [
        # hide_final defaults to on, yet final and cancelled are the events themselves.
        (["Thunderstorm"], ["final", "cancelled"]),
        ([], ["final", "cancelled"]),
        (["Extreme Heat"], []),
    ],
)
async def test_event_type_option_filters_events(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    fired: list[dict[str, Any]],
    freezer: Any,
    event_types: list[str],
    expected: list[str],
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_EVENT_TYPES: event_types}
    )
    await setup_entry(hass, mock_config_entry)

    reissue(fake_bom, final)
    await poll(hass, freezer)
    reissue(fake_bom, cancelled)
    await poll(hass, freezer)

    assert [e["event_type"] for e in fired] == expected
