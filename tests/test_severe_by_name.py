"""A Severe Thunderstorm or Severe Weather warning is severe by name, but BoM sends no severity.

CAP gives these two events the severity `Unknown`, and the product XML a code (`STD`) that grades
nothing. So their sensors say `severe`, the warning's own word, and not `unrated`. Ranking is
unchanged: it uses CAP's severity, so an unknown one still ranks between moderate and severe.
"""

import pytest

from custom_components.bom_warnings.active_warnings import (
    ActiveWarning,
    highest_level,
    level_of,
    level_options,
    rank_warnings,
    type_attributes,
    warning_attributes,
)
from custom_components.bom_warnings.cap import Severity
from custom_components.bom_warnings.const import LEVEL_COLORS

SEVERE_BY_NAME = ("Thunderstorm", "Weather")


def warning(event: str, severity: Severity, product_id: str = "IDX") -> ActiveWarning:
    return ActiveWarning(
        product_id=product_id,
        event=event,
        headline=f"{event} warning",
        severity=severity,
        effective=None,
        expires=None,
    )


@pytest.mark.parametrize("event", SEVERE_BY_NAME)
def test_an_unknown_severity_is_called_severe_and_keeps_its_orange(event: str) -> None:
    unknown = warning(event, Severity.UNKNOWN)

    assert level_of(unknown) == "severe"
    assert highest_level([unknown]) == "severe"
    attributes = type_attributes(event, [unknown])
    assert attributes["level"] == "severe"
    assert attributes["color"] == LEVEL_COLORS["unknown"]
    assert warning_attributes(unknown, ranked=True)["level"] == "severe"
    assert warning_attributes(unknown, ranked=True)["severity"] == "unknown"


@pytest.mark.parametrize("event", SEVERE_BY_NAME)
def test_a_real_severe_severity_is_red_so_the_two_stay_apart(event: str) -> None:
    attributes = type_attributes(event, [warning(event, Severity.SEVERE)])

    assert attributes["level"] == "severe"
    assert attributes["color"] == LEVEL_COLORS["severe"]


@pytest.mark.parametrize("event", SEVERE_BY_NAME)
def test_the_sensor_has_no_unrated_state(event: str) -> None:
    assert level_options(event) == ["none", "minor", "moderate", "severe", "extreme"]


@pytest.mark.parametrize("event", ["Extreme Heat", "Wind", "Riverine Flood"])
def test_every_other_type_still_says_unrated(event: str) -> None:
    assert highest_level([warning(event, Severity.UNKNOWN)]) == "unrated"
    assert "unrated" in level_options(event)


def test_ranking_still_puts_an_unknown_between_moderate_and_severe() -> None:
    storm = warning("Thunderstorm", Severity.UNKNOWN, "STORM")
    moderate = warning("Riverine Flood", Severity.MODERATE, "MOD")
    severe = warning("Extreme Heat", Severity.SEVERE, "SEV")

    assert [w.product_id for w in rank_warnings([moderate, storm, severe])] == [
        "SEV",
        "STORM",
        "MOD",
    ]
