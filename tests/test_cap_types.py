"""Every warning type BoM publishes, parsed from its real sample CAP file.

The expected values are recorded facts about the files in tests/fixtures/cap_samples, stated
literally so a parser change that alters them shows up here.
"""

import re
from pathlib import Path

import pytest

from custom_components.bom_warnings.cap import Phase, Severity, parse_cap
from custom_components.bom_warnings.warning_types import WARNING_TYPES

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLES = FIXTURES / "cap_samples"

# file, product id, event, message phase, severity of each <info> block, area-code kinds.
SAMPLE_FACTS = [
    ("IDT38200.cap.xml", "IDT38200", "Exposure", Phase.NEW, (Severity.MODERATE,), {"PW"}),
    ("IDQ21137.cap.xml", "IDQ21137", "Weather", Phase.UPDATE, (Severity.UNKNOWN,), {"PW"}),
    (
        "IDN22000.cap.xml",
        "IDN22000",
        "Fire Weather",
        Phase.UPDATE,
        (Severity.EXTREME, Severity.SEVERE),
        {"FW"},
    ),
    (
        "IDV23000.cap.xml",
        "IDV23000",
        "Frost",
        Phase.UPDATE,
        (Severity.MODERATE, Severity.UNKNOWN),
        {"PW"},
    ),
    ("IDN28522.cap.xml", "IDN28522", "Large Coastal Surf", Phase.NEW, (Severity.MODERATE,), {"MW"}),
    ("IDQ21013.cap.xml", "IDQ21013", "Extreme Heat", Phase.UPDATE, (Severity.SEVERE,), {"PW"}),
    (
        "IDD20105.cap.xml",
        "IDD20105",
        "Wind",
        Phase.UPDATE,
        (Severity.SEVERE, Severity.SEVERE, Severity.MODERATE, Severity.MODERATE),
        {"MW"},
    ),
    (
        "IDS20240.cap.xml",
        "IDS20240",
        "Hazardous Road Conditions",
        Phase.NEW,
        (Severity.MODERATE,),
        {"ME"},
    ),
    (
        "IDQ21033.cap.xml",
        "IDQ21033",
        "Thunderstorm",
        Phase.UPDATE,
        (Severity.UNKNOWN, Severity.UNKNOWN),
        {"PW"},
    ),
    ("IDN21037.cap.xml", "IDN21037", "Weather", Phase.NEW, (Severity.UNKNOWN,), {"PW"}),
    (
        "IDT29000.cap.xml",
        "IDT29000",
        "Sheep Grazier Warning",
        Phase.UPDATE,
        (Severity.MODERATE,),
        {"PW"},
    ),
    (
        "IDD24500.cap.xml",
        "IDD24500",
        "Tropical Cyclone",
        Phase.UPDATE,
        (Severity.SEVERE, Severity.SEVERE),
        {"PT", "PW"},
    ),
    ("IDY68027_cap.xml", "IDY68027", "Tsunami", Phase.UPDATE, (Severity.SEVERE,), {"TW"}),
]


def code_kind(code: str) -> str:
    """'NSW_PW006' -> 'PW'."""
    match = re.fullmatch(r"[A-Z]+_([A-Z]+)\d+", code)
    assert match, code
    return match.group(1)


@pytest.mark.parametrize(
    ("filename", "product_id", "event", "phase", "severities", "kinds"), SAMPLE_FACTS
)
def test_sample_parses_to_the_recorded_facts(
    filename: str,
    product_id: str,
    event: str,
    phase: Phase,
    severities: tuple[Severity, ...],
    kinds: set[str],
) -> None:
    warning = parse_cap((SAMPLES / filename).read_bytes())

    assert warning is not None
    assert warning.product_id == product_id
    assert warning.phase is phase
    assert {info.event for info in warning.infos} == {event}
    assert tuple(info.severity for info in warning.infos) == severities
    assert {code_kind(code) for code in warning.area_codes} == kinds


def test_every_sample_file_is_in_the_table() -> None:
    assert sorted(p.name for p in SAMPLES.glob("ID*")) == sorted(f[0] for f in SAMPLE_FACTS)


def test_tsunami_file_with_an_underscore_name_still_parses() -> None:
    assert parse_cap((SAMPLES / "IDY68027_cap.xml").read_bytes()) is not None


def fixture_events() -> set[str]:
    return {
        match
        for path in [*(FIXTURES / "cap").glob("*.xml"), *SAMPLES.glob("ID*")]
        for match in re.findall(r"<event>([^<]*)</event>", path.read_text())
    }


def test_every_event_seen_in_recorded_files_is_offered() -> None:
    assert fixture_events() <= {t.event for t in WARNING_TYPES}


def test_known_event_types_are_exactly_the_observed_ones_sorted() -> None:
    assert sorted(t.event for t in WARNING_TYPES) == [
        "Exposure",
        "Extreme Heat",
        "Fire Weather",
        "Frost",
        "Hazardous Road Conditions",
        "Large Coastal Surf",
        "Riverine Flood",
        "Sheep Grazier Warning",
        "Thunderstorm",
        "Tropical Cyclone",
        "Tsunami",
        "Weather",
        "Wind",
    ]
