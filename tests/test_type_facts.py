"""What a warning's type adds to the generic summary, worked out in one place.

A type with no entry gets the generic summary and nothing more; thunderstorm is the one entry, and
the end-to-end cases over real captures are in `test_thunderstorm_attributes.py`.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from custom_components.bom_warnings.cap import Info, Phase, Severity, parse_cap
from custom_components.bom_warnings.type_facts import Facts, facts_for, summary_of

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


SAMPLES = Path(__file__).parent / "fixtures" / "cap_samples"


def sample_info(name: str) -> Info:
    """The one block of a file from BoM's sample catalogue, unmodified."""
    cap = parse_cap((SAMPLES / f"{name}.cap.xml").read_bytes())
    assert cap is not None
    (block,) = cap.infos
    return block


@pytest.mark.parametrize(
    ("sample", "hazards", "hazard"),
    [
        pytest.param(
            "IDN21037",
            ["wind"],
            "Damaging west to northwesterly wind gusts",
            id="severe-weather-wind",
        ),
        pytest.param(
            "IDQ21137",
            ["surf"],
            "Large and powerful surf conditions",
            id="coastal-hazard-surf",
        ),
    ],
)
def test_a_weather_warning_names_its_hazard_from_the_opening_phrase(
    sample: str, hazards: list[str], hazard: str
) -> None:
    facts = facts_for(sample_info(sample), [])

    assert facts.attributes == {"hazards": hazards, "hazard": hazard}
    assert facts.badges == ()


def test_a_weather_warning_keeps_the_generic_summary() -> None:
    block = sample_info("IDN21037")

    assert facts_for(block, []).summary == summary_of(block.description)


@pytest.mark.parametrize(
    "description",
    [
        pytest.param("", id="none"),
        pytest.param("Conditions are expected to ease on Monday.", id="no-leading-phrase-or-word"),
    ],
)
@pytest.mark.parametrize("event", ["Weather", "Thunderstorm"])
def test_no_hazard_text_means_no_hazard_attribute(event: str, description: str) -> None:
    facts = facts_for(info(event, description), [])

    assert not {"hazards", "hazard"} & facts.attributes.keys()


def test_a_weather_warning_takes_its_hazards_from_the_paragraph_that_names_the_area() -> None:
    description = (
        "DAMAGING WINDS are expected in the Hunter.\n\n"
        "HEAVY RAINFALL that may lead to flash flooding is expected in Illawarra."
    )

    facts = facts_for(info("Weather", description), ["Illawarra"])

    assert facts.attributes == {"hazards": ["rain", "flood"], "hazard": "Heavy rainfall"}
