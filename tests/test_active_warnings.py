"""What one location sees of the parsed warnings, tested without Home Assistant.

The warnings are built from the CAP types directly: this is about the filtering rules, not about
parsing, which has its own tests against recorded files.
"""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.bom_warnings.active_warnings import (
    ActiveWarning,
    WarningState,
    covering,
    product_states,
)
from custom_components.bom_warnings.cap import CapWarning, Info, Phase, Severity

NOW = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
EARLIER = NOW - timedelta(hours=1)
HERE = frozenset({"QLD_ME008"})
ELSEWHERE = frozenset({"WA_ME001"})


def info(
    event: str = "Severe Thunderstorm",
    *,
    codes: frozenset[str] = HERE,
    phase: Phase = Phase.NEW,
    severity: Severity = Severity.SEVERE,
    expires: datetime | None = LATER,
    headline: str = "Severe Thunderstorm Warning for Brisbane",
) -> Info:
    return Info(
        event=event,
        headline=headline,
        severity=severity,
        effective=EARLIER,
        expires=expires,
        area_desc="Brisbane",
        area_codes=codes,
        phase=phase,
    )


def warning(*infos: Info, product_id: str = "IDQ1", phase: Phase = Phase.NEW) -> CapWarning:
    return CapWarning(
        product_id=product_id,
        identifier=f"AusBoM-{product_id}-1",
        sent=EARLIER,
        phase=phase,
        infos=infos,
    )


def test_a_current_matching_block_is_reported_with_its_fields() -> None:
    (found,) = covering([warning(info())], HERE, NOW)
    assert found == ActiveWarning(
        product_id="IDQ1",
        event="Severe Thunderstorm",
        headline="Severe Thunderstorm Warning for Brisbane",
        severity=Severity.SEVERE,
        effective=EARLIER,
        expires=LATER,
        sent=EARLIER,
        phase=Phase.NEW,
    )


def test_a_block_for_another_area_is_not_reported() -> None:
    assert covering([warning(info(codes=ELSEWHERE))], HERE, NOW) == ()


def test_an_expired_block_is_not_reported_whatever_hide_final_says() -> None:
    expired = warning(info(expires=EARLIER))
    assert covering([expired], HERE, NOW) == ()
    assert covering([expired], HERE, NOW, hide_final=False) == ()


@pytest.mark.parametrize("phase", [Phase.CANCELLED, Phase.FINAL])
@pytest.mark.parametrize(
    ("hide_final", "expires", "listed"),
    [
        pytest.param(True, LATER, False, id="hidden-by-default"),
        pytest.param(False, LATER, True, id="listed-until-it-expires"),
        pytest.param(False, None, True, id="listed-when-it-never-expires"),
        pytest.param(False, EARLIER, False, id="gone-once-expired"),
    ],
)
def test_an_ended_block_is_listed_only_when_asked_and_until_it_expires(
    phase: Phase, hide_final: bool, expires: datetime | None, listed: bool
) -> None:
    ended = warning(info(phase=phase, expires=expires))
    found = covering([ended], HERE, NOW, hide_final=hide_final)
    assert [w.phase for w in found] == ([phase] if listed else [])


def test_an_ended_block_is_listed_but_not_current() -> None:
    (found,) = covering([warning(info(phase=Phase.FINAL))], HERE, NOW, hide_final=False)
    assert not found.is_current


def test_a_type_that_is_off_is_not_reported() -> None:
    mixed = warning(info("Severe Thunderstorm"), info("Flood"))
    found = covering([mixed], HERE, NOW, type_on=lambda event: event != "Flood")
    assert [w.event for w in found] == ["Severe Thunderstorm"]


def test_a_mixed_file_matches_per_block_not_per_file() -> None:
    # The matching block has ended and the active one is for somewhere else: the file as a whole
    # touches this location and is active, but no block both covers it and is active.
    mixed = warning(
        info(codes=HERE, expires=EARLIER),
        info(codes=ELSEWHERE, expires=LATER),
    )
    assert covering([mixed], HERE, NOW) == ()


def test_each_block_of_a_file_is_reported_on_its_own() -> None:
    two = warning(
        info("Severe Thunderstorm", severity=Severity.SEVERE),
        info("Flood", severity=Severity.MINOR),
    )
    assert {w.event for w in covering([two], HERE, NOW)} == {"Severe Thunderstorm", "Flood"}


def test_a_product_with_no_covering_block_has_no_state() -> None:
    assert product_states([warning(info(codes=ELSEWHERE))], HERE, NOW) == {}


def test_a_state_is_one_per_product_and_carries_the_files_identifier() -> None:
    result = product_states([warning(info(headline="Severe Thunderstorm Warning"))], HERE, NOW)
    assert result == {
        "IDQ1": WarningState(
            product_id="IDQ1",
            identifier="AusBoM-IDQ1-1",
            phase=Phase.NEW,
            event="Severe Thunderstorm",
            headline="Severe Thunderstorm Warning",
            severity=Severity.SEVERE,
        )
    }


def test_the_most_severe_covering_block_stands_for_the_product() -> None:
    two = warning(
        info("Heatwave", severity=Severity.MINOR),
        info("Heatwave", severity=Severity.EXTREME, headline="Extreme Heatwave Warning"),
        info("Heatwave", severity=Severity.SEVERE),
    )
    state = product_states([two], HERE, NOW)["IDQ1"]
    assert (state.severity, state.headline) == (Severity.EXTREME, "Extreme Heatwave Warning")


@pytest.mark.parametrize("phase", [Phase.CANCELLED, Phase.FINAL])
def test_an_ended_block_stays_in_the_states_so_the_transition_can_be_seen(phase: Phase) -> None:
    ended = warning(info(phase=phase))
    assert product_states([ended], HERE, NOW)["IDQ1"].phase is phase


def test_a_block_that_merely_expired_without_a_cancel_is_not_news() -> None:
    assert product_states([warning(info(expires=EARLIER))], HERE, NOW) == {}


def test_the_type_filter_applies_to_states_even_for_ended_blocks() -> None:
    final = warning(info("Flood", phase=Phase.FINAL))
    assert product_states([final], HERE, NOW, lambda event: False) == {}
    assert "IDQ1" in product_states([final], HERE, NOW, lambda event: True)
