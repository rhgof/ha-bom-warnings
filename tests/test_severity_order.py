"""One severity order: the event entity and the ranked list must pick the same block.

The warnings are synthetic. No recorded file has one product with blocks of different severities
(thunderstorm products are all `unknown`, marine wind is Moderate and Severe), so the pairs that
disagree could not be shown with recorded data.
"""

from itertools import permutations

import pytest

from custom_components.bom_warnings.active_warnings import (
    LEVEL_OPTIONS,
    SEVERITY_ORDER,
    covering,
    product_states,
    rank_warnings,
)
from custom_components.bom_warnings.cap import Severity
from custom_components.bom_warnings.const import LEVEL_COLORS

from .test_active_warnings import HERE, NOW, info, warning


@pytest.mark.parametrize(
    ("first", "second"),
    [pytest.param(a, b, id=f"{a}-then-{b}") for a, b in permutations(Severity, 2)],
)
def test_the_block_standing_for_a_product_is_the_one_the_ranked_list_puts_first(
    first: Severity, second: Severity
) -> None:
    product = warning(
        info("Severe Thunderstorm", severity=first, headline=f"{first} block"),
        info("Severe Thunderstorm", severity=second, headline=f"{second} block"),
    )
    (standing,) = product_states([product], HERE, NOW).values()
    ranked_first = rank_warnings(covering([product], HERE, NOW))[0]
    assert standing.headline == ranked_first.headline


def test_every_severity_is_ranked_exactly_once() -> None:
    assert sorted(SEVERITY_ORDER) == sorted(Severity)


def test_unknown_ranks_between_moderate_and_severe() -> None:
    # BoM sends `unknown` for Severe Weather and Severe Thunderstorm warnings, which must not rank
    # below a minor flood.
    assert SEVERITY_ORDER == (
        Severity.MINOR,
        Severity.MODERATE,
        Severity.UNKNOWN,
        Severity.SEVERE,
        Severity.EXTREME,
    )


def test_every_ranked_severity_has_a_colour() -> None:
    assert {severity.value for severity in SEVERITY_ORDER} == set(LEVEL_COLORS)


def test_the_level_options_follow_the_order_with_unknown_called_unrated() -> None:
    assert LEVEL_OPTIONS == ["none", "minor", "moderate", "unrated", "severe", "extreme"]
