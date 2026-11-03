"""Ranking the warnings that cover a location, and the level states derived from it.

Plain values, no Home Assistant. The severity order itself is tested in `test_severity_order`.
"""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.bom_warnings.active_warnings import (
    LEVEL_OPTIONS,
    STATE_NONE,
    ActiveWarning,
    current_then_ended,
    highest_level,
    level_of,
    rank_warnings,
)
from custom_components.bom_warnings.cap import Phase, Severity

NOW = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)


def active(
    severity: Severity = Severity.SEVERE,
    *,
    product_id: str = "IDQ1",
    sent: datetime | None = None,
    phase: Phase = Phase.NEW,
) -> ActiveWarning:
    return ActiveWarning(
        product_id=product_id,
        event="Severe Thunderstorm",
        headline=f"{product_id} {severity}",
        severity=severity,
        effective=None,
        expires=None,
        sent=sent,
        phase=phase,
    )


def ids(warnings: list[ActiveWarning]) -> list[str]:
    return [w.product_id for w in warnings]


def test_ranking_puts_unknown_between_moderate_and_severe() -> None:
    shuffled = [
        active(severity, product_id=str(severity))
        for severity in (
            Severity.MINOR,
            Severity.EXTREME,
            Severity.UNKNOWN,
            Severity.MODERATE,
            Severity.SEVERE,
        )
    ]
    assert ids(rank_warnings(shuffled)) == ["extreme", "severe", "unknown", "moderate", "minor"]


def test_ties_go_to_the_most_recently_sent_then_undated_then_product_id() -> None:
    old = active(product_id="IDQ5", sent=NOW - timedelta(hours=2))
    new = active(product_id="IDQ9", sent=NOW - timedelta(hours=1))
    undated_b = active(product_id="IDQ2")
    undated_a = active(product_id="IDQ1")
    assert ids(rank_warnings([undated_b, old, undated_a, new])) == ["IDQ9", "IDQ5", "IDQ1", "IDQ2"]


def test_warnings_sent_at_the_same_moment_go_by_product_id() -> None:
    later_id = active(product_id="IDQ8", sent=NOW)
    earlier_id = active(product_id="IDQ3", sent=NOW)
    assert ids(rank_warnings([later_id, earlier_id])) == ["IDQ3", "IDQ8"]


def test_a_more_severe_warning_beats_a_more_recent_one() -> None:
    recent_minor = active(Severity.MINOR, product_id="IDQ1", sent=NOW)
    old_extreme = active(Severity.EXTREME, product_id="IDQ2", sent=NOW - timedelta(days=1))
    assert ids(rank_warnings([recent_minor, old_extreme])) == ["IDQ2", "IDQ1"]


def test_ranking_nothing_gives_nothing() -> None:
    assert rank_warnings([]) == []


@pytest.mark.parametrize(
    ("severities", "expected"),
    [
        pytest.param([], "none", id="none-in-force"),
        pytest.param([Severity.MINOR], "minor", id="one"),
        pytest.param([Severity.MINOR, Severity.EXTREME], "extreme", id="the-top-one"),
        pytest.param([Severity.UNKNOWN], "unrated", id="unknown-is-called-unrated"),
        pytest.param([Severity.UNKNOWN, Severity.MINOR], "unrated", id="unknown-beats-minor"),
        pytest.param([Severity.UNKNOWN, Severity.SEVERE], "severe", id="severe-beats-unknown"),
    ],
)
def test_the_highest_level_among_those_in_force(severities: list[Severity], expected: str) -> None:
    warnings = [active(s, product_id=f"IDQ{i}") for i, s in enumerate(severities)]
    assert highest_level(warnings) == expected


@pytest.mark.parametrize("phase", [Phase.CANCELLED, Phase.FINAL])
def test_an_ended_warning_never_counts_towards_the_highest_level(phase: Phase) -> None:
    ended = active(Severity.EXTREME, product_id="IDQ1", phase=phase)
    assert highest_level([ended, active(Severity.MINOR, product_id="IDQ2")]) == "minor"
    assert highest_level([ended]) == STATE_NONE


def test_the_level_options_are_none_then_the_ranked_levels_with_unknown_called_unrated() -> None:
    assert STATE_NONE == "none"
    assert LEVEL_OPTIONS == ["none", "minor", "moderate", "unrated", "severe", "extreme"]


def test_current_warnings_come_before_ended_ones_each_in_rank_order() -> None:
    warnings = [
        active(Severity.EXTREME, product_id="ended-extreme", phase=Phase.FINAL),
        active(Severity.MINOR, product_id="current-minor"),
        active(Severity.SEVERE, product_id="current-severe"),
        active(Severity.MINOR, product_id="ended-minor", phase=Phase.CANCELLED),
    ]
    assert ids(current_then_ended(warnings)) == [
        "current-severe",
        "current-minor",
        "ended-extreme",
        "ended-minor",
    ]


def test_a_warnings_level_is_its_raw_severity() -> None:
    # The ranked list shows `unknown` where the type sensors say `unrated`: a recorded quirk.
    assert level_of(active(Severity.UNKNOWN)) == "unknown"
    assert level_of(active(Severity.MODERATE)) == "moderate"
