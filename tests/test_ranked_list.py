"""The location-only ranked warning list, with icon and colour, through Home Assistant.

Runs on the fake server's `all_types` scenario (a real sample of every warning type, dates
shifted to now), so the list must pick the entry's own warnings out of a nationwide feed.
"""

import json
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    CONF_AREA_CODES,
    CONF_HIDE_FINAL,
    DEFAULT_EVENT_ICON,
    LEVEL_COLORS,
    NO_WARNING_ICON,
)
from custom_components.bom_warnings.warning_types import WARNING_TYPES
from scripts.fake_bom import layout, scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_options import layers, set_options  # noqa: F401
from .test_sensor import COUNT, MOST_SEVERE, poll, setup_entry, state_of
from .test_warning_types import MATCHABLE, entry_at

EVENT_ICONS = {t.event: t.icon for t in WARNING_TYPES}

pytestmark = pytest.mark.freeze_time(NOW)

# The area codes of the owner's real Home entry (north Sydney coast).
HOME_CODES = [
    "NSW_FL068",
    "NSW_FW004",
    "NSW_ME001",
    "NSW_ME008",
    "NSW_ME011",
    "NSW_ME017",
    "NSW_PW005",
]
# Home's codes plus one area from each of four more samples, so every severity level is present:
# NSW_FW015 (extreme fire block), NSW_PW006 (Severe Weather, CAP unknown), SA_ME003 (moderate road
# conditions) and NSW_RC031 (minor flood). A real location would not span states; this one only
# exercises the ranking.
SPREAD_CODES = [*HOME_CODES, "NSW_FW015", "NSW_PW006", "SA_ME003", "NSW_RC031"]

OUTSIDE_NSW = {"IDT38200", "IDQ21137", "IDV23000", "IDQ21013", "IDQ21033", "IDT29000", "IDD24500"}

ICON_LIST = Path("static") / "mdi" / "iconList.json"


@pytest.fixture(autouse=True)
def all_types(fake_bom: FakeBom) -> None:
    scenarios.apply("all_types", fake_bom.root)


def entry_with(codes: list[str], **options: Any) -> MockConfigEntry:
    entry = entry_at(codes[0])
    return MockConfigEntry(
        domain=entry.domain,
        version=entry.version,
        unique_id=entry.unique_id,
        title=entry.title,
        options=options,
        data={**entry.data, CONF_AREA_CODES: codes},
    )


def rows(hass: HomeAssistant, entity_id: str = COUNT) -> list[tuple[str, str, str, str]]:
    return [
        (w["product_id"], w["level"], w["icon"], w["color"])
        for w in state_of(hass, entity_id).attributes["warnings"]
    ]


def row(product_id: str, level: str, icon: str) -> tuple[str, str, str, str]:
    return (product_id, level, icon, LEVEL_COLORS[level])


async def test_home_codes_list_only_what_covers_the_location(hass: HomeAssistant) -> None:
    await setup_entry(hass, entry_with(HOME_CODES))

    # The Greater Sydney fire block is the only warning on Home's codes; the other states' samples
    # and western NSW's must never appear.
    assert rows(hass) == [row("IDN22000", "severe", EVENT_ICONS["Fire Weather"])]
    assert state_of(hass, COUNT).state == "1"
    listed = {w["product_id"] for w in state_of(hass, COUNT).attributes["warnings"]}
    assert not listed & OUTSIDE_NSW


async def test_a_headline_too_long_for_a_state_is_truncated_and_kept_whole_in_the_attribute(
    hass: HomeAssistant,
) -> None:
    await setup_entry(hass, entry_with(HOME_CODES))

    most = state_of(hass, MOST_SEVERE)
    headline = most.attributes["headline"]
    assert len(headline) > 255
    assert headline.startswith("Extreme Fire Weather Warning for Greater Hunter")
    assert most.state == headline[:254] + "…"


async def test_every_severity_level_is_ranked_with_unknown_between_moderate_and_severe(
    hass: HomeAssistant,
) -> None:
    await setup_entry(hass, entry_with(SPREAD_CODES))

    assert rows(hass) == [
        row("IDN22000", "extreme", EVENT_ICONS["Fire Weather"]),
        row("IDN22000", "severe", EVENT_ICONS["Fire Weather"]),
        row("IDN21037", "unknown", EVENT_ICONS["Weather"]),
        row("IDS20240", "moderate", EVENT_ICONS["Hazardous Road Conditions"]),
        row("IDN36631", "minor", EVENT_ICONS["Riverine Flood"]),
    ]
    assert state_of(hass, COUNT).state == "5"


async def test_list_items_carry_the_documented_fields(hass: HomeAssistant) -> None:
    await setup_entry(hass, entry_with(SPREAD_CODES))

    item = state_of(hass, COUNT).attributes["warnings"][2]
    assert set(item) == {
        "product_id",
        "event",
        "severity",
        "level",
        "icon",
        "color",
        "headline",
        "phase",
        "sent",
        "effective",
        "expires",
    }
    assert item["event"] == "Weather"
    assert item["severity"] == "unknown"
    assert item["phase"] == "new"


async def test_most_severe_sensor_shows_the_top_item_with_icon_level_and_colour(
    hass: HomeAssistant,
) -> None:
    await setup_entry(hass, entry_with(SPREAD_CODES))

    most = state_of(hass, MOST_SEVERE)
    top = most.attributes["warnings"][0]
    assert most.state == top["headline"]
    assert (most.attributes["icon"], most.attributes["level"], most.attributes["color"]) == (
        EVENT_ICONS["Fire Weather"],
        "extreme",
        LEVEL_COLORS["extreme"],
    )
    assert most.attributes["product_id"] == "IDN22000"
    assert most.attributes["severity"] == "extreme"
    assert most.attributes["warnings"] == state_of(hass, COUNT).attributes["warnings"]


@pytest.mark.parametrize("entity_id", [COUNT, MOST_SEVERE])
async def test_entity_icon_follows_the_top_warning(hass: HomeAssistant, entity_id: str) -> None:
    await setup_entry(hass, entry_with(["NSW_PW006"]))

    assert state_of(hass, entity_id).attributes["icon"] == EVENT_ICONS["Weather"]


@pytest.mark.parametrize("entity_id", [COUNT, MOST_SEVERE])
async def test_entity_icon_is_neutral_without_warnings(hass: HomeAssistant, entity_id: str) -> None:
    await setup_entry(hass, entry_with(["WA_PW099"]))

    assert state_of(hass, entity_id).attributes["icon"] == NO_WARNING_ICON


async def test_ended_warnings_follow_the_current_ones_when_not_hidden(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    layers: object,  # noqa: F811
    freezer: Any,
) -> None:
    codes = ["NSW_MW001", "NSW_RC031"]
    entry = entry_with(codes)
    await setup_entry(hass, entry)
    scenarios.apply("warning_cancelled", fake_bom.root)
    await poll(hass, freezer)
    await set_options(hass, entry, **{CONF_HIDE_FINAL: False})

    items = state_of(hass, COUNT).attributes["warnings"]
    assert [(i["product_id"], i["phase"]) for i in items] == [
        ("IDN36631", "new"),
        ("IDN20400", "cancelled"),
    ]
    assert state_of(hass, COUNT).state == "1"


@pytest.mark.parametrize("removed", ["IDN22000", "IDN21037", "IDS20240", "IDN36631"])
async def test_list_shrinks_when_a_warning_is_removed(
    hass: HomeAssistant, fake_bom: FakeBom, freezer: Any, removed: str
) -> None:
    await setup_entry(hass, entry_with(SPREAD_CODES))
    before = rows(hass)

    (fake_bom.root / layout.WARNINGS / f"{removed}.cap.xml").unlink()
    await poll(hass, freezer)

    assert rows(hass) == [r for r in before if r[0] != removed]
    assert state_of(hass, COUNT).state == str(len(rows(hass)))


async def test_list_grows_when_a_covering_warning_appears(
    hass: HomeAssistant, fake_bom: FakeBom, freezer: Any
) -> None:
    (fake_bom.root / layout.WARNINGS / "IDN21037.cap.xml").unlink()
    await setup_entry(hass, entry_with(SPREAD_CODES))
    assert "IDN21037" not in {r[0] for r in rows(hass)}

    scenarios.apply("all_types", fake_bom.root)
    await poll(hass, freezer)

    assert ("IDN21037", "unknown") in {r[:2] for r in rows(hass)}


@pytest.mark.parametrize(
    ("product_id", "event", "code"),
    MATCHABLE,
    ids=[f"{event}-{product}" for product, event, _ in MATCHABLE],
)
async def test_each_event_gets_its_icon(
    hass: HomeAssistant, product_id: str, event: str, code: str
) -> None:
    await setup_entry(hass, entry_at(code))

    icons = {
        w["icon"]
        for w in state_of(hass, COUNT).attributes["warnings"]
        if w["product_id"] == product_id
    }
    assert icons == {EVENT_ICONS[event]}


def test_colours_are_one_hex_per_level_in_ranking_order() -> None:
    assert list(LEVEL_COLORS) == ["minor", "moderate", "unknown", "severe", "extreme"]
    assert all(len(c) == 7 and c.startswith("#") for c in LEVEL_COLORS.values())
    assert len(set(LEVEL_COLORS.values())) == len(LEVEL_COLORS)


@pytest.mark.skipif(find_spec("hass_frontend") is None, reason="home-assistant-frontend missing")
def test_every_icon_exists_in_the_frontend_icon_list() -> None:
    spec = find_spec("hass_frontend")
    assert spec is not None and spec.submodule_search_locations
    icon_list = Path(next(iter(spec.submodule_search_locations))) / ICON_LIST
    known = {f"mdi:{icon['name']}" for icon in json.loads(icon_list.read_text())}

    used = {*EVENT_ICONS.values(), DEFAULT_EVENT_ICON, NO_WARNING_ICON}
    assert used - known == set()
