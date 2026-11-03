"""The fire danger sensors, driven through Home Assistant against the fake BoM FTP server.

The real capture is the 2026-11-02 16:15 AEDT issue: its four periods are 3 to 6 November.
"""

import json
import os
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import pytest
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    DEFAULT_FIRE_DANGER_ICON,
    FIRE_DANGER_COLORS,
    FIRE_DANGER_ICONS,
)
from custom_components.bom_warnings.diagnostics import async_get_config_entry_diagnostics
from custom_components.bom_warnings.fire_danger import LEVEL_KEYS
from scripts.fake_bom import layout
from scripts.fake_bom.server import FakeBom

from .test_binary_sensor import ENTITY_ID as WARNING
from .test_binary_sensor import poll, setup_entry
from .test_reliability import repair_issues

TODAY = "sensor.home_fire_danger_today"
TOMORROW = "sensor.home_fire_danger_tomorrow"
FIRE_FILE = "IDN10016.xml"
# Local (AEDT, +11:00) wall-clock times, written as UTC because that is what the clock holds.
AFTER_THE_16_15_ISSUE = "2026-11-02 06:00:00+00:00"  # 17:00 on 2 Nov
AFTER_THE_05_05_ISSUE = "2026-11-02 18:30:00+00:00"  # 05:30 on 3 Nov


def served(fake_bom: FakeBom) -> Path:
    return fake_bom.root / layout.WARNINGS / FIRE_FILE


def reissue(fake_bom: FakeBom, data: bytes) -> None:
    """Serve a changed file; a later mtime is what makes BoM's listing line differ."""
    path = served(fake_bom)
    stat = path.stat()
    path.write_bytes(data)
    os.utime(path, (stat.st_mtime + 60, stat.st_mtime + 60))


def one_day_later(raw: bytes) -> bytes:
    """A later issue shaped like the capture, with every date moved on by a day (test data only)."""
    for day in (6, 5, 4, 3, 2):
        raw = raw.replace(f"2026-11-0{day}".encode(), f"2026-11-0{day + 1}".encode())
    return raw


def state_of(hass: HomeAssistant, entity_id: str) -> Any:
    state = hass.states.get(entity_id)
    assert state is not None
    return state


@pytest.fixture
def freeze(freezer: Any) -> Any:
    freezer.move_to("2026-11-02 06:00:00+00:00")
    return freezer


@pytest.mark.parametrize("area_codes", [["NSW_FW004"]])
@pytest.mark.parametrize(
    ("now", "today", "tomorrow"),
    [
        (AFTER_THE_16_15_ISSUE, STATE_UNKNOWN, "moderate"),
        (AFTER_THE_05_05_ISSUE, "moderate", "moderate"),
    ],
    ids=["after_16_15", "after_05_05"],
)
async def test_greater_sydney_states_from_the_real_capture(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
    now: str,
    today: str,
    tomorrow: str,
) -> None:
    freezer.move_to(now)
    await setup_entry(hass, mock_config_entry)

    assert (state_of(hass, TODAY).state, state_of(hass, TOMORROW).state) == (today, tomorrow)


@pytest.mark.parametrize("area_codes", [["NSW_PW005", "NSW_FW004"]])
async def test_attributes_describe_the_district_and_every_period(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freeze: Any
) -> None:
    await setup_entry(hass, mock_config_entry)

    attrs = state_of(hass, TOMORROW).attributes
    assert attrs["forecast"] == [
        {"date": "2026-11-03", "level": "moderate", "fire_behaviour_index": 16},
        {"date": "2026-11-04", "level": "moderate", "fire_behaviour_index": 17},
        {"date": "2026-11-05", "level": "high", "fire_behaviour_index": 28},
        {"date": "2026-11-06", "level": "moderate", "fire_behaviour_index": 22},
    ]
    assert attrs["issued"] == "2026-11-02T16:15:00+11:00"
    assert attrs["district"] == "Greater Sydney Region"
    assert attrs["source"] == "IDN10016"
    assert attrs["attribution"] == "Australian Government Bureau of Meteorology"
    assert attrs["icon"] == FIRE_DANGER_ICONS["moderate"]
    assert attrs["color"] == FIRE_DANGER_COLORS["moderate"]
    assert attrs["device_class"] == "enum"
    assert attrs["options"] == list(LEVEL_KEYS)


@pytest.mark.parametrize("area_codes", [["NSW_FW001"]])
async def test_icon_and_colour_follow_each_days_level(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    freezer.move_to(AFTER_THE_05_05_ISSUE)
    await setup_entry(hass, mock_config_entry)

    today = state_of(hass, TODAY).attributes
    assert (today["icon"], today["color"]) == (
        FIRE_DANGER_ICONS["no_rating"],
        FIRE_DANGER_COLORS["no_rating"],
    )


@pytest.mark.parametrize("area_codes", [["NSW_FW001"]])
async def test_a_level_nobody_has_seen_is_unknown_with_the_raw_text_kept(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freezer: Any
) -> None:
    freezer.move_to(AFTER_THE_05_05_ISSUE)
    reissue(fake_bom, served(fake_bom).read_bytes().replace(b">No Rating<", b">Code Red<", 1))
    await setup_entry(hass, mock_config_entry)

    today = state_of(hass, TODAY)
    assert today.state == STATE_UNKNOWN
    assert today.attributes["level"] == "Code Red"
    assert today.attributes["icon"] == DEFAULT_FIRE_DANGER_ICON
    assert today.attributes["forecast"][0]["level"] == "Code Red"


@pytest.mark.parametrize("area_codes", [["QLD_PW001"], ["NSW_PW005", "NSW_ME001"], ["NSW_FW099"]])
async def test_no_entities_when_no_stored_code_is_in_the_product(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freeze: Any
) -> None:
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get(TODAY) is None
    assert hass.states.get(TOMORROW) is None
    assert state_of(hass, WARNING).state == STATE_OFF


@pytest.mark.parametrize("area_codes", [["NSW_FW004"]])
async def test_entities_share_the_device_have_distinct_ids_and_are_enabled(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freeze: Any
) -> None:
    await setup_entry(hass, mock_config_entry)

    entities = er.async_get(hass)
    today = entities.async_get(TODAY)
    tomorrow = entities.async_get(TOMORROW)
    warning = entities.async_get(WARNING)
    assert today is not None and tomorrow is not None and warning is not None
    assert len({today.unique_id, tomorrow.unique_id, warning.unique_id}) == 3
    assert today.device_id == tomorrow.device_id == warning.device_id
    assert today.disabled_by is None and tomorrow.disabled_by is None
    assert dr.async_get(hass).async_get(str(today.device_id)) is not None


@pytest.mark.parametrize("area_codes", [["NSW_FW004"]])
async def test_unchanged_listing_is_not_fetched_again_and_a_change_is_fetched_once(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freeze: Any,
) -> None:
    def calls(command: str) -> int:
        return sum(1 for c, arg in fake_bom.commands if c == command and arg == FIRE_FILE)

    await setup_entry(hass, mock_config_entry)
    assert (calls("LIST"), calls("RETR")) == (1, 1)

    await poll(hass, freeze)
    assert (calls("LIST"), calls("RETR")) == (2, 1)

    reissue(fake_bom, served(fake_bom).read_bytes().replace(b">High<", b">Extreme<", 1))
    await poll(hass, freeze)
    assert (calls("LIST"), calls("RETR")) == (3, 2)
    await poll(hass, freeze)
    assert (calls("LIST"), calls("RETR")) == (4, 2)


@pytest.mark.parametrize("area_codes", [["QLD_PW001"]])
async def test_an_entry_without_a_fire_weather_code_never_asks_for_the_product(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freeze: Any
) -> None:
    await setup_entry(hass, mock_config_entry)

    assert [arg for _, arg in fake_bom.commands if FIRE_FILE in arg] == []


@pytest.mark.parametrize("area_codes", [["NSW_FW004"]])
@pytest.mark.parametrize("failure", ["missing", "empty", "malformed"])
async def test_a_bad_product_at_startup_leaves_warnings_and_the_repair_issue_alone(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freeze: Any,
    failure: str,
) -> None:
    served(fake_bom).unlink()
    if failure != "missing":
        served(fake_bom).write_bytes({"empty": b"", "malformed": b"<product>"}[failure])
    await setup_entry(hass, mock_config_entry)
    for _ in range(4):
        await poll(hass, freeze)

    assert state_of(hass, WARNING).state == STATE_OFF
    assert repair_issues(hass) == []
    assert mock_config_entry.runtime_data.coordinator.consecutive_failures == 0
    assert hass.states.get(TODAY) is None


@pytest.mark.parametrize("area_codes", [["NSW_FW004"]])
async def test_entities_appear_once_a_missing_product_shows_up(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freeze: Any
) -> None:
    capture = served(fake_bom).read_bytes()
    served(fake_bom).unlink()
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get(TOMORROW) is None

    served(fake_bom).write_bytes(capture)
    await poll(hass, freeze)

    assert state_of(hass, TOMORROW).state == "moderate"


@pytest.mark.parametrize("area_codes", [["NSW_FW004"]])
async def test_the_product_going_missing_later_keeps_the_last_data(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freeze: Any
) -> None:
    await setup_entry(hass, mock_config_entry)
    served(fake_bom).unlink()
    for _ in range(4):
        await poll(hass, freeze)

    assert state_of(hass, TOMORROW).state == "moderate"
    assert state_of(hass, WARNING).state == STATE_OFF
    assert repair_issues(hass) == []


@pytest.mark.parametrize("area_codes", [["NSW_FW004"]])
async def test_entities_go_unavailable_not_missing_when_the_district_leaves_the_product(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freeze: Any
) -> None:
    raw = served(fake_bom).read_bytes()
    await setup_entry(hass, mock_config_entry)
    start = raw.index(b'<area aac="NSW_FW004"')
    end = raw.index(b'<area aac="NSW_FW005"')
    reissue(fake_bom, raw[:start] + raw[end:])

    await poll(hass, freeze)

    assert state_of(hass, TODAY).state == STATE_UNAVAILABLE
    assert state_of(hass, TOMORROW).state == STATE_UNAVAILABLE
    assert er.async_get(hass).async_get(TODAY) is not None
    assert state_of(hass, WARNING).state == STATE_OFF


@pytest.mark.parametrize("area_codes", [["NSW_FW001"]])
@pytest.mark.parametrize(
    ("restart_at", "today", "tomorrow"),
    [
        # Same local day as the remembered rating (3 Nov): it survives the restart.
        ("2026-11-03 06:00:00+00:00", "no_rating", "no_rating"),
        ("2026-11-03 12:59:00+00:00", "no_rating", "no_rating"),
        # Local midnight: 3 Nov is over and the issue's own 4 Nov period takes over.
        ("2026-11-03 13:00:00+00:00", "no_rating", "moderate"),
    ],
    ids=["afternoon", "before_midnight", "next_day"],
)
async def test_the_remembered_rating_survives_a_reload_until_the_end_of_its_local_day(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
    restart_at: str,
    today: str,
    tomorrow: str,
) -> None:
    freezer.move_to(AFTER_THE_05_05_ISSUE)
    await setup_entry(hass, mock_config_entry)
    reissue(fake_bom, one_day_later(served(fake_bom).read_bytes()))
    freezer.move_to("2026-11-03 06:00:00+00:00")
    await poll(hass, freezer)

    freezer.move_to(restart_at)
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert state_of(hass, TODAY).state == today
    assert state_of(hass, TOMORROW).state == tomorrow


@pytest.mark.parametrize("area_codes", [["NSW_FW004"]])
async def test_what_is_remembered_is_saved_and_pruned_in_storage_after_a_restart(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    # What is shown on each day is tested without Home Assistant; this is the storage wiring.
    freezer.move_to(AFTER_THE_05_05_ISSUE)
    await setup_entry(hass, mock_config_entry)
    stored = hass_storage[f"bom_warnings.fire_danger.{mock_config_entry.entry_id}"]["data"]
    assert [p["date"] for p in stored["periods"]] == [
        "2026-11-03",
        "2026-11-04",
        "2026-11-05",
        "2026-11-06",
    ]

    # Down for two days: the 3rd must not be kept in storage on the 5th.
    freezer.move_to("2026-11-05 00:30:00+00:00")  # 11:30 on 5 Nov
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    stored = hass_storage[f"bom_warnings.fire_danger.{mock_config_entry.entry_id}"]["data"]
    assert [p["date"] for p in stored["periods"]][0] == "2026-11-04"


@pytest.mark.parametrize("area_codes", [["NSW_FW001"]])
async def test_removing_the_entry_deletes_its_remembered_ratings(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    freezer.move_to(AFTER_THE_05_05_ISSUE)
    await setup_entry(hass, mock_config_entry)
    key = f"bom_warnings.fire_danger.{mock_config_entry.entry_id}"
    assert key in hass_storage

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert key not in hass_storage


@pytest.mark.parametrize("area_codes", [["NSW_FW004"]])
async def test_diagnostics_include_the_fire_district_but_no_coordinates(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freeze: Any
) -> None:
    await setup_entry(hass, mock_config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    text = str(diagnostics)
    for secret in ("-27.47", "153.021", "-27.470,153.021"):
        assert secret not in text
    fire = diagnostics["coordinator"]["fire_danger"]
    assert (fire["product"], fire["district"], fire["issued"]) == (
        "IDN10016",
        "NSW_FW004",
        "2026-11-02T16:15:00+11:00",
    )
    assert [p["level"] for p in fire["periods"]] == ["moderate", "moderate", "high", "moderate"]


@pytest.mark.parametrize("area_codes", [["QLD_PW001"]])
async def test_diagnostics_fire_danger_is_empty_without_a_match(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry, freeze: Any
) -> None:
    await setup_entry(hass, mock_config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert diagnostics["coordinator"]["fire_danger"] is None


def test_levels_have_one_colour_and_one_icon_each() -> None:
    assert list(FIRE_DANGER_COLORS) == list(LEVEL_KEYS)
    assert list(FIRE_DANGER_ICONS) == list(LEVEL_KEYS)
    assert len(set(FIRE_DANGER_COLORS.values())) == len(LEVEL_KEYS)
    assert all(len(c) == 7 and c.startswith("#") for c in FIRE_DANGER_COLORS.values())


@pytest.mark.skipif(find_spec("hass_frontend") is None, reason="home-assistant-frontend missing")
def test_every_fire_danger_icon_exists_in_the_frontend_icon_list() -> None:
    spec = find_spec("hass_frontend")
    assert spec is not None and spec.submodule_search_locations
    icon_list = (
        Path(next(iter(spec.submodule_search_locations))) / "static" / "mdi" / "iconList.json"
    )
    known = {f"mdi:{icon['name']}" for icon in json.loads(icon_list.read_text())}

    assert {*FIRE_DANGER_ICONS.values(), DEFAULT_FIRE_DANGER_ICON} - known == set()


def test_the_fixture_dates_this_file_relies_on() -> None:
    """Guards the clock constants above: they assume the capture is the 16:15 issue of 2 Nov."""
    raw = (layout.FIRE_DANGER_FIXTURES / FIRE_FILE).read_bytes()
    assert b"2026-11-02T16:15:00+11:00" in raw
