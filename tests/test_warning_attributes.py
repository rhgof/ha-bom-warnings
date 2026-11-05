"""The attributes entities show for a warning, as exact dictionaries, without Home Assistant.

Dashboards read these, so every key and value is pinned.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.bom_warnings.active_warnings import (
    ActiveWarning,
    event_icon,
    type_attributes,
    warning_attributes,
)
from custom_components.bom_warnings.cap import Phase, Severity
from custom_components.bom_warnings.const import (
    DEFAULT_EVENT_ICON,
    LEVEL_COLORS,
)
from custom_components.bom_warnings.warning_types import WARNING_TYPES

EVENT_ICONS = {t.event: t.icon for t in WARNING_TYPES}
WARNING_TYPE_NOTES = {t.event: t.note for t in WARNING_TYPES if t.note}

NOW = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)
LATER = NOW + timedelta(hours=1)
LEAN_KEYS = {
    "product_id",
    "event",
    "headline",
    "severity",
    "phase",
    "effective",
    "expires",
    "in_force",
}
RANKED_EXTRAS = {"level", "icon", "color", "sent"}


def active(
    event: str = "Severe Thunderstorm",
    headline: str = "Severe Thunderstorm Warning for Brisbane",
    severity: Severity = Severity.SEVERE,
    *,
    product_id: str = "IDQ1",
    phase: Phase = Phase.NEW,
    sent: datetime | None = NOW,
    area: str = "",
) -> ActiveWarning:
    return ActiveWarning(
        product_id=product_id,
        event=event,
        headline=headline,
        severity=severity,
        effective=EARLIER,
        expires=LATER,
        sent=sent,
        phase=phase,
        area=area,
    )


def test_a_lean_item_is_exactly_these_fields() -> None:
    assert warning_attributes(active()) == {
        "product_id": "IDQ1",
        "event": "Severe Thunderstorm",
        "headline": "Severe Thunderstorm Warning for Brisbane",
        "severity": "severe",
        "phase": "new",
        "effective": EARLIER.isoformat(),
        "expires": LATER.isoformat(),
        "in_force": True,
    }


def test_an_item_for_a_warning_that_has_not_started_says_so() -> None:
    upcoming = replace(active(), effective=LATER, in_force=False)
    item = warning_attributes(upcoming)
    assert (item["in_force"], item["effective"]) == (False, LATER.isoformat())


def test_an_item_names_the_areas_it_matched_and_only_then() -> None:
    assert warning_attributes(active(area="Illawarra"))["area"] == "Illawarra"
    assert warning_attributes(active(area="Illawarra"), ranked=True)["area"] == "Illawarra"
    assert "area" not in warning_attributes(active())


def test_a_ranked_item_is_the_lean_item_plus_level_icon_colour_and_sent() -> None:
    warning = active("Thunderstorm")
    assert warning_attributes(warning, ranked=True) == {
        **warning_attributes(warning),
        "level": "severe",
        "icon": EVENT_ICONS["Thunderstorm"],
        "color": LEVEL_COLORS["severe"],
        "sent": NOW.isoformat(),
    }


def test_a_ranked_item_keeps_the_raw_unknown_level_and_its_colour() -> None:
    item = warning_attributes(active(severity=Severity.UNKNOWN), ranked=True)
    assert (item["severity"], item["level"], item["color"]) == (
        "unknown",
        "unknown",
        LEVEL_COLORS["unknown"],
    )


def test_a_ranked_item_without_a_sent_time_says_so() -> None:
    assert warning_attributes(active(sent=None), ranked=True)["sent"] is None


def test_the_lean_item_leaves_out_what_only_the_ranked_item_has() -> None:
    assert set(warning_attributes(active())) == LEAN_KEYS
    assert set(warning_attributes(active(), ranked=True)) == LEAN_KEYS | RANKED_EXTRAS


@pytest.mark.parametrize("ranked", [False, True])
@pytest.mark.parametrize(
    ("event", "headline", "strength"),
    [
        pytest.param("Wind", "Gale Force Wind Warning for Moreton Bay", "gale", id="wind"),
        pytest.param("Wind", "Cancellation of Strong Wind Warning", None, id="cancelled-wind"),
        pytest.param("Severe Thunderstorm", "Gale Force Wind Warning", None, id="other-event"),
    ],
)
def test_strength_is_added_in_both_shapes_only_for_a_wind_warning_with_a_class(
    ranked: bool, event: str, headline: str, strength: str | None
) -> None:
    item = warning_attributes(active(event, headline), ranked=ranked)
    assert item.get("strength") == strength
    assert ("strength" in item) is (strength is not None)


def test_the_icon_follows_the_event_with_a_default_for_one_we_do_not_know() -> None:
    assert event_icon("Thunderstorm") == EVENT_ICONS["Thunderstorm"]
    assert event_icon("A Type BoM Adds Later") == DEFAULT_EVENT_ICON


def test_a_type_with_no_warnings_has_empty_top_attributes() -> None:
    attributes = type_attributes("Flood", [])
    expected: dict[str, Any] = {
        "level": "none",
        "color": None,
        "headline": None,
        "expires": None,
        "product_id": None,
        "event": None,
        "in_force": None,
        "warnings": [],
    }
    if note := WARNING_TYPE_NOTES.get("Flood"):
        expected["note"] = note
    assert attributes == expected


def test_the_top_attributes_come_from_the_highest_ranked_current_warning() -> None:
    ended = active(
        "Flood", "Final flood warning", Severity.EXTREME, product_id="IDQ1", phase=Phase.FINAL
    )
    minor = active("Flood", "Minor flood warning", Severity.MINOR, product_id="IDQ2")
    severe = active("Flood", "Severe flood warning", Severity.SEVERE, product_id="IDQ3")
    attributes = type_attributes("Flood", [ended, minor, severe])
    assert attributes["headline"] == "Severe flood warning"
    assert attributes["product_id"] == "IDQ3"
    assert attributes["event"] == "Flood"
    assert attributes["expires"] == LATER.isoformat()


def test_the_warnings_attribute_lists_every_warning_in_the_order_given_lean() -> None:
    ended = active(
        "Flood", "Final flood warning", Severity.EXTREME, product_id="IDQ1", phase=Phase.FINAL
    )
    minor = active("Flood", "Minor flood warning", Severity.MINOR, product_id="IDQ2")
    attributes = type_attributes("Flood", [minor, ended])
    assert attributes["warnings"] == [warning_attributes(minor), warning_attributes(ended)]


@pytest.mark.parametrize(
    ("warnings", "strength"),
    [
        pytest.param([], None, id="no-warning"),
        pytest.param(
            [active("Wind", "Gale Force Wind Warning", product_id="IDQ1")], "gale", id="one"
        ),
        pytest.param(
            [active("Wind", "Gale Force Wind Warning", phase=Phase.FINAL)], None, id="only-ended"
        ),
    ],
)
def test_the_wind_type_always_has_a_strength_attribute(
    warnings: list[ActiveWarning], strength: str | None
) -> None:
    attributes = type_attributes("Wind", warnings)
    assert "strength" in attributes
    assert attributes["strength"] == strength


@pytest.mark.parametrize("event", ["Flood", "Weather"])
def test_no_other_type_has_a_strength_attribute(event: str) -> None:
    assert "strength" not in type_attributes(event, [active(event, "A Warning")])


@pytest.mark.parametrize("event", ["Wind", "Weather", "Flood"])
def test_a_note_is_added_for_the_types_that_have_one(event: str) -> None:
    attributes = type_attributes(event, [])
    if event in WARNING_TYPE_NOTES:
        assert attributes["note"] == WARNING_TYPE_NOTES[event]
    else:
        assert "note" not in attributes


def test_a_lean_item_without_times_has_them_as_none() -> None:
    open_ended = ActiveWarning("IDQ1", "Flood", "Flood Watch", Severity.MINOR, None, None)
    item = warning_attributes(open_ended)
    assert (item["effective"], item["expires"]) == (None, None)


def test_a_type_sensor_says_whether_its_top_warning_is_in_force() -> None:
    upcoming = replace(active(event="Thunderstorm"), in_force=False)
    assert type_attributes("Thunderstorm", [upcoming])["in_force"] is False
    assert type_attributes("Thunderstorm", [active(event="Thunderstorm")])["in_force"] is True
    assert type_attributes("Thunderstorm", [])["in_force"] is None
