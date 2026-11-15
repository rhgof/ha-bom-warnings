"""The display fields every warning carries, so a card draws one without knowing the event.

A card used to keep its own level words, rank and "ended" list, and check for the thunderstorm
event to pick a layout. The integration knows all of it, so each entry says it instead.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from custom_components.bom_warnings.active_warnings import (
    ActiveWarning,
    type_attributes,
    warning_attributes,
)
from custom_components.bom_warnings.cap import Phase, Severity

SENT = datetime(2026, 11, 15, 3, 40, tzinfo=UTC)


def warning(
    event: str, severity: Severity, *, phase: Phase = Phase.UNKNOWN, **extra: Any
) -> ActiveWarning:
    return ActiveWarning(
        product_id="IDX1",
        event=event,
        headline=f"{event} headline",
        severity=severity,
        effective=None,
        expires=None,
        sent=SENT,
        phase=phase,
        **extra,
    )


@pytest.mark.parametrize(
    ("event", "severity", "level", "title"),
    [
        pytest.param(
            "Extreme Heat", Severity.SEVERE, "severe", "Severe Heatwave warning", id="graded"
        ),
        pytest.param("Frost", Severity.MINOR, "minor", "Minor Frost warning", id="minor"),
        pytest.param(
            "Thunderstorm",
            Severity.UNKNOWN,
            "severe",
            "Severe thunderstorm warning",
            id="a-name-that-already-says-the-level-is-not-prefixed-again",
        ),
        pytest.param(
            "Fire Weather",
            Severity.SEVERE,
            "extreme",
            "Extreme Fire weather warning",
            id="own-grade",
        ),
        pytest.param(
            "Something New",
            Severity.UNKNOWN,
            None,
            "Something New",
            id="no-grade-and-no-row-has-no-level-and-the-event-for-a-title",
        ),
    ],
)
def test_the_level_and_the_title_are_worked_out_by_the_integration(
    event: str, severity: Severity, level: str | None, title: str
) -> None:
    attributes = warning_attributes(warning(event, severity), ranked=True)

    assert attributes["level"] == level
    assert attributes["title"] == title


def test_the_display_fields_are_on_the_ranked_list_and_not_the_lean_ones() -> None:
    fields = {"level", "title", "color", "icon", "rank", "ended", "badges"}

    assert fields <= warning_attributes(warning("Frost", Severity.MINOR), ranked=True).keys()
    assert not fields & warning_attributes(warning("Frost", Severity.MINOR)).keys()


def test_the_rank_orders_warnings_across_types() -> None:
    ranks = {
        severity: warning_attributes(warning("Frost", severity), ranked=True)["rank"]
        for severity in Severity
    }

    assert ranks[Severity.MINOR] < ranks[Severity.MODERATE] < ranks[Severity.UNKNOWN]
    assert ranks[Severity.UNKNOWN] < ranks[Severity.SEVERE] < ranks[Severity.EXTREME]


@pytest.mark.parametrize(
    ("phase", "ended"),
    [
        pytest.param(Phase.NEW, False, id="new"),
        pytest.param(Phase.CANCELLED, True, id="cancelled"),
        pytest.param(Phase.FINAL, True, id="final"),
    ],
)
def test_a_warning_says_whether_it_has_ended(phase: Phase, ended: bool) -> None:
    assert (
        warning_attributes(warning("Frost", Severity.MINOR, phase=phase), ranked=True)["ended"]
        is ended
    )


@pytest.mark.parametrize(
    ("extra", "badges"),
    [
        pytest.param({}, [], id="none"),
        pytest.param({"very_dangerous": True}, ["Very dangerous"], id="very-dangerous"),
        pytest.param({"detailed": True}, ["Detailed"], id="detailed"),
        pytest.param(
            {"very_dangerous": True, "detailed": True},
            ["Very dangerous", "Detailed"],
            id="both-in-a-fixed-order",
        ),
    ],
)
def test_the_badges_are_ready_to_show(extra: dict[str, Any], badges: list[str]) -> None:
    item = warning_attributes(warning("Thunderstorm", Severity.UNKNOWN, **extra), ranked=True)

    assert item["badges"] == badges


def test_the_sensor_carries_its_top_warnings_display_fields() -> None:
    attributes = type_attributes(
        "Thunderstorm",
        [
            warning("Thunderstorm", Severity.UNKNOWN, very_dangerous=True),
            warning("Thunderstorm", Severity.UNKNOWN, phase=Phase.CANCELLED),
        ],
    )

    assert attributes["title"] == "Severe thunderstorm warning"
    assert attributes["badges"] == ["Very dangerous"]
    assert (
        attributes["rank"]
        == warning_attributes(warning("Frost", Severity.UNKNOWN), ranked=True)["rank"]
    )


def test_a_quiet_sensor_has_no_display_fields_to_show() -> None:
    attributes = type_attributes("Thunderstorm", [])

    assert attributes["title"] is None
    assert attributes["badges"] == []
    assert attributes["rank"] is None
