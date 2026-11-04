"""The short summary a warning shows: the first paragraph of its CAP description, cut to length.

Pure Python, no Home Assistant. The real-capture cases read BoM's own files from
`tests/fixtures/products/`; the entities are covered in `test_warning_summary_entities.py`.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.bom_warnings.active_warnings import (
    ActiveWarning,
    covering,
    summary_of,
    type_attributes,
    warning_attributes,
)
from custom_components.bom_warnings.cap import Phase, Severity, parse_cap

CAPTURES = Path(__file__).parent / "fixtures" / "products" / "2026-11-03T2348Z"
# Inside the validity window of every product used below.
CAPTURE_NOW = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)
LIMIT = 300
NOW = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        pytest.param("First paragraph.\n\nSecond paragraph.", "First paragraph.", id="first"),
        pytest.param("Only one paragraph.", "Only one paragraph.", id="single"),
        pytest.param("Line one\nline two.\n\nNext.", "Line one line two.", id="joined-lines"),
        pytest.param("\n\n  Hello   world.\n\nMore", "Hello world.", id="leading-blank-lines"),
        pytest.param("x" * LIMIT, "x" * LIMIT, id="exactly-the-limit"),
        pytest.param("", None, id="empty"),
        pytest.param("  \n\n  ", None, id="blank"),
        pytest.param(None, None, id="none"),
    ],
)
def test_the_summary_is_the_first_paragraph_on_one_line(
    description: str | None, expected: str | None
) -> None:
    assert summary_of(description) == expected


def test_a_long_paragraph_is_cut_on_a_word_boundary_with_an_ellipsis() -> None:
    summary = summary_of("word " * 100)

    assert summary is not None
    assert len(summary) <= LIMIT
    assert summary.endswith("word…")
    assert summary.removesuffix("…").split(" ") == ["word"] * summary.count("word")


def test_one_unbroken_word_longer_than_the_limit_is_cut_hard() -> None:
    summary = summary_of("x" * 400)

    assert summary == "x" * (LIMIT - 1) + "…"


def summaries(product: str) -> list[str | None]:
    """Each block's summary, for a location covered by every block of the captured product."""
    warning = parse_cap((CAPTURES / f"{product}.cap.xml").read_bytes())
    assert warning is not None
    return [w.summary for w in covering([warning], warning.area_codes, CAPTURE_NOW)]


def test_a_flood_warning_summary_is_its_first_description_paragraph() -> None:
    assert summaries("IDQ20829") == [
        "Moderate flooding is occurring along the Condamine River downstream of Oakey Creek to "
        "Cotswold."
    ]


def test_a_block_with_a_short_first_paragraph_does_not_borrow_from_the_next() -> None:
    assert summaries("IDQ20770") == [
        "Flooding is no longer expected along the Burnett River to Mundubbera.",
        "Flooding is no longer expected along the Stuart and Boyne Rivers.",
        "Flooding is no longer expected along the Burnett River downstream of Mundubbera to "
        "Paradise Dam.",
    ]


def test_marine_wind_blocks_have_no_description_so_no_summary() -> None:
    assert summaries("IDN20400") == [None, None]


def test_a_real_long_paragraph_is_cut_at_the_limit() -> None:
    (summary,) = summaries("IDN29000")
    assert summary is not None
    assert len(summary) <= LIMIT
    assert summary.endswith("…")
    assert summary.startswith("Sheep graziers are warned that cold temperatures")


def warning(summary: str | None = None, *, event: str = "Riverine Flood") -> ActiveWarning:
    return ActiveWarning(
        product_id="IDQ1",
        event=event,
        headline="Flood Warning for the Condamine",
        severity=Severity.MODERATE,
        effective=NOW,
        expires=NOW + timedelta(hours=1),
        sent=NOW,
        phase=Phase.UPDATE,
        summary=summary,
    )


@pytest.mark.parametrize("ranked", [False, True])
def test_a_list_entry_carries_the_summary_only_when_there_is_one(ranked: bool) -> None:
    assert warning_attributes(warning("Rising."), ranked=ranked)["summary"] == "Rising."
    assert "summary" not in warning_attributes(warning(None), ranked=ranked)


def test_a_type_sensor_shows_its_top_warnings_summary_at_the_top_level() -> None:
    attributes = type_attributes("Riverine Flood", [warning("Rising.")])

    assert attributes["summary"] == "Rising."
    assert attributes["warnings"][0]["summary"] == "Rising."


def test_a_type_sensor_whose_top_warning_has_no_summary_leaves_it_out() -> None:
    assert "summary" not in type_attributes("Riverine Flood", [warning(None)])


def test_a_type_sensor_with_no_warnings_shows_no_summary() -> None:
    assert "summary" not in type_attributes("Riverine Flood", [])
