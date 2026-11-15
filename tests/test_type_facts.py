"""What a warning's type adds to the generic summary, worked out in one place.

A type with no entry gets the generic summary and nothing more; thunderstorm is the one entry, and
the end-to-end cases over real captures are in `test_thunderstorm_attributes.py`.
"""

from datetime import UTC, datetime

import pytest

from custom_components.bom_warnings.cap import Info, Phase, Severity
from custom_components.bom_warnings.type_facts import Facts, facts_for

NOW = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)


def info(event: str, description: str, **extra: object) -> Info:
    return Info(
        event=event,
        headline=f"{event} warning",
        severity=Severity.MINOR,
        effective=NOW,
        expires=NOW,
        area_desc="",
        area_codes=frozenset({"X"}),
        phase=Phase.NEW,
        description=description,
        **extra,  # type: ignore[arg-type]
    )


def test_a_type_with_no_entry_gets_the_generic_summary_and_nothing_more() -> None:
    facts = facts_for(info("Frost", "Frost is likely.\n\nSecond paragraph."), ["Hunter"])

    assert facts == Facts(summary="Frost is likely.")


def test_the_generic_summary_prefers_the_paragraph_naming_the_area() -> None:
    facts = facts_for(info("Frost", "First.\n\nFrost in the Hunter tonight."), ["Hunter"])

    assert facts.summary == "Frost in the Hunter tonight."


@pytest.mark.parametrize("event", ["Frost", "Thunderstorm"])
def test_a_block_with_no_description_falls_back_to_the_product_xml_line(event: str) -> None:
    facts = facts_for(info(event, "", xml_summary="A line from the XML."), [])

    assert facts.summary == "A line from the XML."


def test_a_thunderstorm_says_its_hazards_tier_and_badges() -> None:
    description = (
        "VERY DANGEROUS THUNDERSTORMS are likely to produce large hail and damaging winds."
    )

    facts = facts_for(info("Thunderstorm", description), [])

    assert facts.attributes == {"hazards": ["wind", "hail"], "very_dangerous": True}
    assert facts.badges == ("Very dangerous",)
