"""A Fire Weather Warning's grade is BoM's own, which its CAP severity is one step off.

The Warning Products User Guide, Table 24, pairs them: High is CAP Moderate, Extreme is CAP Severe
and Catastrophic is CAP Extreme. The headline and the XML code carry the grade, so a sensor that
showed the CAP word would say `severe` for an "Extreme Fire Weather Warning". Reading the grade
back from the CAP severity is lossless, so the fire weather sensor shows the grade, in the colours
of the fire danger rating, and every other type keeps CAP's words.
"""

import pytest

from custom_components.bom_warnings.active_warnings import (
    LEVEL_OPTIONS,
    ActiveWarning,
    highest_level,
    level_options,
    rank_warnings,
    type_attributes,
    warning_attributes,
)
from custom_components.bom_warnings.cap import Phase, Severity
from custom_components.bom_warnings.const import FIRE_DANGER_COLORS, LEVEL_COLORS


def warning(event: str, severity: Severity, *, phase: Phase = Phase.NEW) -> ActiveWarning:
    return ActiveWarning(
        product_id="IDN22000",
        event=event,
        headline="Extreme Fire Weather Warning for Greater Hunter",
        severity=severity,
        effective=None,
        expires=None,
        phase=phase,
    )


def fire(severity: Severity) -> ActiveWarning:
    return warning("Fire Weather", severity)


FIRE_GRADES = [
    (Severity.MODERATE, "high", FIRE_DANGER_COLORS["high"]),
    (Severity.SEVERE, "extreme", FIRE_DANGER_COLORS["extreme"]),
    (Severity.EXTREME, "catastrophic", FIRE_DANGER_COLORS["catastrophic"]),
]


@pytest.mark.parametrize(("severity", "grade", "colour"), FIRE_GRADES)
def test_a_fire_weather_warning_shows_the_bureaus_grade_and_the_rating_colour(
    severity: Severity, grade: str, colour: str
) -> None:
    item = warning_attributes(fire(severity), ranked=True)

    assert (item["level"], item["color"]) == (grade, colour)


@pytest.mark.parametrize(("severity", "grade", "colour"), FIRE_GRADES)
def test_the_fire_weather_sensor_state_and_colour_are_the_grade(
    severity: Severity, grade: str, colour: str
) -> None:
    attributes = type_attributes("Fire Weather", [fire(severity)])

    assert highest_level([fire(severity)]) == grade
    assert (attributes["level"], attributes["color"]) == (grade, colour)


@pytest.mark.parametrize(("severity", "grade", "colour"), FIRE_GRADES)
def test_the_cap_severity_stays_what_the_file_said(
    severity: Severity, grade: str, colour: str
) -> None:
    assert warning_attributes(fire(severity))["severity"] == str(severity)


@pytest.mark.parametrize(
    ("severity", "level", "state", "colour"),
    [
        (Severity.MINOR, "minor", "minor", LEVEL_COLORS["minor"]),
        (Severity.UNKNOWN, "unknown", "unrated", LEVEL_COLORS["unknown"]),
    ],
)
def test_a_severity_with_no_grade_keeps_cap_s_word_and_colour(
    severity: Severity, level: str, state: str, colour: str
) -> None:
    item = warning_attributes(fire(severity), ranked=True)

    assert (item["level"], item["color"]) == (level, colour)
    assert highest_level([fire(severity)]) == state


@pytest.mark.parametrize(
    ("event", "severity"),
    [
        ("Extreme Heat", Severity.SEVERE),
        ("Extreme Heat", Severity.EXTREME),
        ("Weather", Severity.MODERATE),
    ],
)
def test_every_other_type_keeps_cap_s_words_and_colours(event: str, severity: Severity) -> None:
    item = warning_attributes(warning(event, severity), ranked=True)

    assert (item["level"], item["color"]) == (severity.value, LEVEL_COLORS[severity.value])
    assert highest_level([warning(event, severity)]) == severity.value


def test_the_grades_are_ranked_by_cap_severity_so_catastrophic_is_on_top() -> None:
    ranked = rank_warnings([fire(Severity.MODERATE), fire(Severity.EXTREME), fire(Severity.SEVERE)])

    assert [w.severity for w in ranked] == [Severity.EXTREME, Severity.SEVERE, Severity.MODERATE]


def test_a_fire_warning_ranks_against_other_types_by_cap_severity() -> None:
    heat = warning("Extreme Heat", Severity.SEVERE)

    assert rank_warnings([heat, fire(Severity.EXTREME)])[0].event == "Fire Weather"
    assert rank_warnings([fire(Severity.MODERATE), heat])[0].event == "Extreme Heat"


def test_an_ended_fire_warning_does_not_set_the_state() -> None:
    ended = warning("Fire Weather", Severity.EXTREME, phase=Phase.CANCELLED)

    assert highest_level([ended]) == "none"
    assert type_attributes("Fire Weather", [ended])["color"] is None


def test_the_fire_weather_sensor_offers_the_grades_and_every_other_type_the_cap_levels() -> None:
    assert level_options("Fire Weather") == [
        "none",
        "minor",
        "high",
        "unrated",
        "extreme",
        "catastrophic",
    ]
    for event in ("Extreme Heat", "Weather", "Thunderstorm", "Wind"):
        assert level_options(event) == LEVEL_OPTIONS, event


def test_every_state_the_fire_weather_sensor_can_have_is_one_of_its_options() -> None:
    options = set(level_options("Fire Weather"))

    for severity in Severity:
        assert highest_level([fire(severity)]) in options, severity
