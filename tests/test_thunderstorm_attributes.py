"""What a thunderstorm warning says about one location, worked out from the real captured files.

A broad warning has a paragraph per group of districts, so the summary, the hazards and the
"very dangerous" tier come from the paragraph that names the entry's own area. The detailed warning
is one paragraph about a storm cell, and its summary is not cut.
"""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from custom_components.bom_warnings.active_warnings import (
    ActiveWarning,
    covering,
    type_attributes,
    warning_attributes,
)
from custom_components.bom_warnings.cap import parse_cap

PRODUCTS = Path(__file__).parent / "fixtures" / "products"
THIRTEENTH = "2026-11-13T0625Z-thunderstorm"
FIFTEENTH = "2026-11-15T0343Z-thunderstorm"
FIFTEENTH_LATER = "2026-11-15T0516Z-thunderstorm"
THIRTEENTH_NOW = datetime(2026, 11, 13, 6, 30, tzinfo=UTC)
FIFTEENTH_NOW = datetime(2026, 11, 15, 3, 50, tzinfo=UTC)
FIFTEENTH_LATER_NOW = datetime(2026, 11, 15, 5, 20, tzinfo=UTC)
FACTS = {"hazards", "very_dangerous", "detailed", "hazard", "next_issue"}


def warning_at(
    snapshot: str, product: str, code: str, name: str, now: datetime, *, detailed: bool = False
) -> ActiveWarning:
    cap = parse_cap((PRODUCTS / snapshot / f"{product}.cap.xml").read_bytes())
    assert cap is not None
    if detailed:
        cap = replace(cap, infos=tuple(replace(info, detailed=True) for info in cap.infos))
    (found,) = (
        w for w in covering([cap], frozenset({code}), now, area_names={code: name}) if w.is_current
    )
    return found


@pytest.mark.parametrize(
    ("snapshot", "product", "code", "name", "now", "starts", "very_dangerous", "hazards"),
    [
        pytest.param(
            FIFTEENTH,
            "IDN21033",
            "NSW_PW002",
            "Mid North Coast",
            FIFTEENTH_NOW,
            "VERY DANGEROUS THUNDERSTORMS are likely to produce large, possibly giant hailstones",
            True,
            ["wind", "hail"],
            id="the-tiered-paragraph-for-the-district-it-names",
        ),
        pytest.param(
            FIFTEENTH,
            "IDN21033",
            "NSW_PW003",
            "Hunter",
            FIFTEENTH_NOW,
            "Severe thunderstorms are likely to produce damaging winds and large hailstones",
            False,
            ["wind", "hail"],
            id="a-neighbouring-district-does-not-inherit-the-tier",
        ),
        pytest.param(
            THIRTEENTH,
            "IDN21033",
            "NSW_PW005",
            "Sydney Metropolitan",
            THIRTEENTH_NOW,
            "Severe thunderstorms are likely to produce heavy rainfall that may lead to flash "
            "flooding, damaging winds and large hailstones",
            False,
            ["wind", "hail", "rain", "flood"],
            id="a-district-named-in-the-second-paragraph-with-its-city-word-dropped",
        ),
        pytest.param(
            THIRTEENTH,
            "IDN21033",
            "NSW_PW001",
            "Northern Rivers",
            THIRTEENTH_NOW,
            "Severe thunderstorms are likely to produce heavy rainfall that may lead to flash "
            "flooding and damaging winds",
            False,
            ["wind", "rain", "flood"],
            id="a-district-named-in-the-first-paragraph",
        ),
        pytest.param(
            FIFTEENTH_LATER,
            "IDN21033",
            "NSW_PW003",
            "Hunter",
            FIFTEENTH_LATER_NOW,
            "Severe thunderstorms are likely to produce damaging winds and large hailstones in "
            "the warning area",
            False,
            ["wind", "hail"],
            id="a-single-paragraph-for-the-whole-area",
        ),
    ],
)
def test_the_summary_is_the_paragraph_that_names_the_entrys_area(
    snapshot: str,
    product: str,
    code: str,
    name: str,
    now: datetime,
    starts: str,
    very_dangerous: bool,
    hazards: list[str],
) -> None:
    found = warning_at(snapshot, product, code, name, now)

    assert found.summary is not None
    assert found.summary.startswith(starts)
    assert found.very_dangerous is very_dangerous
    assert list(found.hazards) == hazards


def test_an_area_no_paragraph_names_gets_the_first_paragraph() -> None:
    found = warning_at(FIFTEENTH, "IDN21033", "NSW_PW004", "Nowhere Named", FIFTEENTH_NOW)

    assert found.summary is not None
    assert found.summary.startswith("VERY DANGEROUS THUNDERSTORMS")


def test_a_detailed_summary_keeps_the_whole_forecast_sentence() -> None:
    found = warning_at(THIRTEENTH, "IDN21035", "NSW_ME014", "Sydney", THIRTEENTH_NOW, detailed=True)

    assert found.summary is not None
    assert found.summary.endswith("Richmond, Windsor and Wilberforce by 5:45 pm.")


def test_a_broad_summary_still_stops_at_the_limit() -> None:
    found = warning_at(
        THIRTEENTH, "IDN21035", "NSW_ME014", "Sydney", THIRTEENTH_NOW, detailed=False
    )

    assert found.summary is not None
    assert len(found.summary) <= 300
    assert found.summary.endswith("…")


def test_the_thunderstorm_facts_are_attributes_only_where_there_is_something_to_say() -> None:
    plain = warning_at(FIFTEENTH, "IDN21033", "NSW_PW003", "Hunter", FIFTEENTH_NOW)
    tiered = warning_at(FIFTEENTH, "IDN21033", "NSW_PW002", "Mid North Coast", FIFTEENTH_NOW)
    detailed = replace(
        warning_at(FIFTEENTH, "IDN21035", "NSW_ME015", "Newcastle", FIFTEENTH_NOW),
        detailed=True,
        hazard="Damaging winds and large hailstones",
        next_issue=datetime(2026, 11, 15, 4, 10, tzinfo=UTC),
    )

    assert {k: v for k, v in warning_attributes(plain).items() if k in FACTS} == {
        "hazards": ["wind", "hail"]
    }
    assert {k: v for k, v in warning_attributes(tiered).items() if k in FACTS} == {
        "hazards": ["wind", "hail"],
        "very_dangerous": True,
    }
    assert {k: v for k, v in warning_attributes(detailed).items() if k in FACTS} == {
        "hazards": ["wind", "hail"],
        "detailed": True,
        "hazard": "Damaging winds and large hailstones",
        "next_issue": "2026-11-15T04:10:00+00:00",
    }


def test_a_type_sensor_carries_its_top_warnings_facts_at_the_top_level() -> None:
    detailed = replace(
        warning_at(FIFTEENTH, "IDN21035", "NSW_ME015", "Newcastle", FIFTEENTH_NOW),
        detailed=True,
        next_issue=datetime(2026, 11, 15, 4, 10, tzinfo=UTC),
    )

    attributes = type_attributes("Thunderstorm", [detailed])

    assert {k: v for k, v in attributes.items() if k in FACTS} == {
        "hazards": ["wind", "hail"],
        "detailed": True,
        "next_issue": "2026-11-15T04:10:00+00:00",
    }


def test_a_type_sensor_says_how_many_warnings_of_its_type_are_current() -> None:
    broad = warning_at(FIFTEENTH, "IDN21033", "NSW_PW003", "Hunter", FIFTEENTH_NOW)
    detailed = warning_at(FIFTEENTH, "IDN21035", "NSW_ME015", "Newcastle", FIFTEENTH_NOW)

    assert type_attributes("Thunderstorm", [broad, detailed])["current"] == 2
    assert type_attributes("Thunderstorm", [])["current"] == 0
