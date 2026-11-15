"""The Most severe warning sensor says how bad the worst warning is, as a level, like the others.

Its state used to be the top warning's headline. That is free text, so Home Assistant coloured its
history by first-seen order and a tile had a sentence for a state. Now the state is the top
warning's level and the headline is an attribute, so it works like a per-type sensor.
"""

from datetime import UTC, datetime

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import HomeAssistant

from custom_components.bom_warnings.active_warnings import (
    ActiveWarning,
    all_level_options,
    highest_level,
    top_attributes,
)
from custom_components.bom_warnings.cap import Severity
from custom_components.bom_warnings.warning_types import WARNING_TYPES

from .test_ranked_list import (  # noqa: F401
    HOME_CODES,
    SPREAD_CODES,
    all_types,
    entry_with,
)
from .test_sensor import MOST_SEVERE, setup_entry, state_of

NOW = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)


def warning(event: str, severity: Severity) -> ActiveWarning:
    return ActiveWarning(
        product_id="IDX1",
        event=event,
        headline=f"{event} headline",
        severity=severity,
        effective=None,
        expires=None,
        sent=NOW,
    )


@pytest.mark.parametrize("severity", list(Severity))
@pytest.mark.parametrize("event", [t.event for t in WARNING_TYPES])
def test_whatever_the_top_warning_is_its_level_is_a_declared_option(
    event: str, severity: Severity
) -> None:
    assert highest_level([warning(event, severity)]) in all_level_options()


def test_the_options_start_at_none_and_list_each_word_once() -> None:
    options = all_level_options()

    assert options[0] == "none"
    assert len(options) == len(set(options))
    # The fire weather grades are levels of a top warning too.
    assert {"minor", "unrated", "severe", "extreme", "high", "catastrophic"} <= set(options)


def test_the_shared_top_attributes_never_ask_for_a_detail_layout() -> None:
    attributes = top_attributes([warning("Thunderstorm", Severity.UNKNOWN)])

    assert "layout" not in attributes
    assert attributes["title"] == "Severe thunderstorm warning"
    assert attributes["level"] == "severe"


async def test_the_state_is_the_top_warnings_level_and_the_headline_is_an_attribute(
    hass: HomeAssistant,
    all_types: None,  # noqa: F811
) -> None:
    await setup_entry(hass, entry_with(SPREAD_CODES))

    most = state_of(hass, MOST_SEVERE)

    assert most.attributes["device_class"] == SensorDeviceClass.ENUM
    assert most.state == most.attributes["level"] == "catastrophic"
    assert most.state in most.attributes["options"]
    assert "Fire Weather Warning" in most.attributes["headline"]
    assert {"title", "rank", "badges", "current"} <= most.attributes.keys()


async def test_a_long_headline_is_kept_whole_since_it_is_no_longer_the_state(
    hass: HomeAssistant,
    all_types: None,  # noqa: F811
) -> None:
    await setup_entry(hass, entry_with(HOME_CODES))

    most = state_of(hass, MOST_SEVERE)

    assert len(most.attributes["headline"]) > 255
    assert most.state == most.attributes["level"]
