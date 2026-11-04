"""The packaged dashboard section, rendered through Home Assistant's template engine.

The section is a file users copy, so these tests treat it as one: render its Markdown cards against
the shared attribute fixture (`fixtures/dashboard/states.json`, which a card repo can reuse as its
contract), and check that the fixture and the entities it names are what the integration really
produces. The browser behaviour (which markup the card keeps) is checked by hand, see
docs/dashboard.md.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from custom_components.bom_warnings.active_warnings import (
    ActiveWarning,
    type_attributes,
    warning_attributes,
)
from custom_components.bom_warnings.cap import Severity
from custom_components.bom_warnings.const import LEVEL_COLORS
from custom_components.bom_warnings.warning_types import WARNING_TYPES, SensorType

from .conftest import NOW
from .test_ranked_list import SPREAD_CODES, all_types, entry_with  # noqa: F401
from .test_sensor import COUNT, setup_entry

pytestmark = pytest.mark.freeze_time(NOW)

NOW_DT = datetime.fromisoformat("2026-11-04T00:24:50+00:00")

SECTION = Path(__file__).parents[1] / "docs" / "dashboards" / "warnings-section.yaml"
STATES: dict[str, dict[str, dict[str, Any]]] = json.loads(
    (Path(__file__).parent / "fixtures" / "dashboard" / "states.json").read_text()
)
SLUG = "home"

# What the cards read from a warning list item.
CARD_KEYS = {"event", "level", "color", "icon", "headline", "phase"}


def section_text() -> str:
    return SECTION.read_text().replace("<title>", SLUG)


def markdown_content(title: str) -> str:
    cards = yaml.safe_load(section_text())["cards"]
    content: str = next(
        c["content"] for c in cards if c.get("type") == "markdown" and c["title"] == title
    )
    return content


async def render(hass: HomeAssistant, scenario: str, title: str) -> str:
    for entity_id, entity in STATES[scenario].items():
        hass.states.async_set(entity_id, entity["state"], entity["attributes"])
    return " ".join(Template(markdown_content(title), hass).async_render().split())


@pytest.mark.parametrize(
    ("scenario", "title", "present", "absent"),
    [
        pytest.param(
            "active",
            "Warnings",
            [
                '<font color="#D32F2F"><ha-icon icon="mdi:thermometer-alert"></ha-icon> '
                "&#9632;</font> "
                "**Extreme Heat** (severe): Severe heatwave warning for Greater Sydney",
                '<font color="#FB8C00"><ha-icon icon="mdi:weather-windy"></ha-icon> '
                "&#9632;</font> "
                "**Wind** (moderate): Strong Wind Warning",
                "**Riverine Flood** (moderate, final): Moderate Flood Warning",
            ],
            ["No warnings for this location."],
            id="list-active",
        ),
        pytest.param(
            "none",
            "Warnings",
            ["No warnings for this location."],
            ["<font", "**"],
            id="list-none",
        ),
        pytest.param(
            "active",
            "Fire danger",
            [
                '<font color="#FEDD3A"><ha-icon icon="mdi:fire"></ha-icon></font> **Today**: High',
                '<font color="#F78100"><ha-icon icon="mdi:fire-alert"></ha-icon></font> '
                "**Tomorrow**: Extreme",
            ],
            [],
            id="fire-active",
        ),
        pytest.param(
            "none",
            "Fire danger",
            ["**Today**: No Rating", "**Tomorrow**: No Rating"],
            [],
            id="fire-none",
        ),
    ],
)
async def test_card_renders_fixture(
    hass: HomeAssistant, scenario: str, title: str, present: list[str], absent: list[str]
) -> None:
    rendered = await render(hass, scenario, title)

    for text in present:
        assert text in rendered
    for text in absent:
        assert text not in rendered


async def test_list_is_ranked_in_the_order_given(hass: HomeAssistant) -> None:
    rendered = await render(hass, "active", "Warnings")

    events = ["Extreme Heat", "Wind", "Riverine Flood"]
    assert sorted(events, key=rendered.index) == events


def every_field_warning() -> ActiveWarning:
    """A warning with each optional field set, so its attributes show every key a list can carry."""
    return ActiveWarning(
        product_id="IDN20400",
        event="Wind",
        headline="Strong Wind Warning for coastal waters",
        severity=Severity.MODERATE,
        effective=NOW_DT,
        expires=NOW_DT,
        sent=NOW_DT,
        area="Sydney Coast",
        summary="A summary.",
    )


def test_fixture_warnings_match_the_integrations_attributes() -> None:
    real = warning_attributes(every_field_warning(), ranked=True)

    items = [w for scenario in STATES.values() for w in scenario[COUNT]["attributes"]["warnings"]]
    assert items
    for item in items:
        assert CARD_KEYS <= item.keys()
        assert item.keys() <= real.keys()
        assert item["color"] == LEVEL_COLORS[item["level"]]


TYPE_SENSORS = {f"sensor.home_{t.key}" for t in WARNING_TYPES if isinstance(t, SensorType)}


def colour_for(level: str) -> str | None:
    """The colour a per-type sensor shows for a level: none while no warning is in force."""
    if level == "none":
        return None
    return LEVEL_COLORS["unknown" if level == "unrated" else level]


def test_fixture_type_sensors_match_the_integrations_attributes() -> None:
    real = type_attributes("Wind", [every_field_warning()])

    fixture = [
        (entity_id, entity)
        for scenario in STATES.values()
        for entity_id, entity in scenario.items()
        if entity_id in TYPE_SENSORS
    ]
    assert fixture
    for entity_id, entity in fixture:
        attributes = entity["attributes"]
        assert {"level", "color"} <= attributes.keys(), entity_id
        assert attributes.keys() <= real.keys(), entity_id
        assert attributes["level"] == entity["state"], entity_id
        assert attributes["color"] == colour_for(entity["state"]), entity_id


async def test_every_type_sensor_says_its_level_and_colour(
    hass: HomeAssistant,
    all_types: None,  # noqa: F811
) -> None:
    await setup_entry(hass, entry_with(SPREAD_CODES))

    levels = set()
    for entity_id in sorted(TYPE_SENSORS):
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.attributes["level"] == state.state, entity_id
        assert state.attributes["color"] == colour_for(state.state), entity_id
        levels.add(state.state)
    # The spread of locations puts more than one level on the sensors, so this is not all `none`.
    assert len(levels - {"none"}) >= 2


async def test_section_names_only_entities_the_integration_creates(
    hass: HomeAssistant,
    all_types: None,  # noqa: F811
) -> None:
    await setup_entry(hass, entry_with(SPREAD_CODES))
    # The fire danger ids are joined in the template, so the day is added here.
    named = set(
        re.findall(r"\b(?:sensor|binary_sensor|event)\.home_[a-z_]*[a-z]\b", section_text())
    )
    named |= {f"sensor.home_fire_danger_{day}" for day in ("today", "tomorrow")}

    assert len(named) > 3
    assert {e for e in named if hass.states.get(e) is None} == set()
