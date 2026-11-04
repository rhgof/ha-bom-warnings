"""BoM's product XML beside a CAP file: the parser, and the reader that fills a missing summary.

Pure Python, no Home Assistant, against the real marine wind product `IDN20400` (NSW, issued
4 Nov 2026) in `tests/fixtures/products/`. Its CAP file has no description, so the one-line
summary of each block comes from the XML hazard whose area codes overlap the block.
"""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from custom_components.bom_warnings.cap import CapWarning, parse_cap
from custom_components.bom_warnings.ftp import BomFtpError
from custom_components.bom_warnings.product_xml import (
    HazardText,
    ProductSummaryReader,
    parse_product_text,
)

from .fake_ftp import FakeFtp

CAPTURES = Path(__file__).parent / "fixtures" / "products" / "2026-11-03T2348Z"
NOW = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)
AFTER_EXPIRY = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)

GALE = "Gale Warning for Eden Coast"
STRONG = (
    "Strong Wind Warning for Coffs Coast, Macquarie Coast, Hunter Coast, Sydney Coast, "
    "Illawarra Coast and Batemans Coast"
)
CAP_SENT = b"2026-11-03T23:29:52+00:00"


def capture(name: str) -> bytes:
    return (CAPTURES / name).read_bytes()


def cap(name: str = "IDN20400.cap.xml") -> CapWarning:
    warning = parse_cap(capture(name))
    assert warning is not None
    return warning


def marine_ftp() -> FakeFtp:
    return FakeFtp({"IDN20400.xml": capture("IDN20400.xml")})


def summaries(warning: CapWarning) -> list[str]:
    return [info.xml_summary for info in warning.infos]


def test_the_parser_reads_each_hazard_with_its_codes_and_text() -> None:
    product = parse_product_text(capture("IDN20400.xml"))

    assert product is not None
    assert product.sent == datetime(2026, 11, 3, 23, 29, 52, tzinfo=UTC)
    assert product.hazards == (
        HazardText(frozenset({"NSW_MW001"}), "Gale Warning", "Eden Coast"),
        HazardText(
            frozenset({f"NSW_MW00{n}" for n in range(2, 8)}),
            "Strong Wind Warning",
            "Coffs Coast, Macquarie Coast, Hunter Coast, Sydney Coast, Illawarra Coast and "
            "Batemans Coast",
        ),
    )


def test_a_product_whose_hazards_carry_no_phenomena_text_yields_no_hazards() -> None:
    product = parse_product_text(capture("IDQ20829.xml"))

    assert product is not None
    assert product.hazards == ()


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"<product><oops", id="malformed"),
        pytest.param(capture("IDN20400.cap.xml"), id="a-cap-file"),
        pytest.param(b'<!DOCTYPE product [<!ENTITY a "b">]><product/>', id="doctype"),
    ],
)
def test_input_that_is_not_a_product_gives_nothing(data: bytes) -> None:
    assert parse_product_text(data) is None


def test_each_block_gets_the_summary_of_the_hazard_that_overlaps_its_codes() -> None:
    reader = ProductSummaryReader(marine_ftp())

    (warning,) = reader.enrich([cap()], NOW)

    assert summaries(warning) == [GALE, STRONG]


def test_the_xml_is_listed_by_exact_name_and_fetched_once() -> None:
    fake = marine_ftp()

    ProductSummaryReader(fake).enrich([cap()], NOW)

    assert fake.listings == ["IDN20400.xml"]
    assert fake.fetches == ["IDN20400.xml"]


def test_an_unchanged_product_costs_no_request_on_the_next_refresh() -> None:
    fake = marine_ftp()
    reader = ProductSummaryReader(fake)
    reader.enrich([cap()], NOW)

    (warning,) = reader.enrich([cap()], NOW)

    assert fake.listings == ["IDN20400.xml"]
    assert fake.fetches == ["IDN20400.xml"]
    assert summaries(warning) == [GALE, STRONG]


def test_a_reissued_product_is_read_again() -> None:
    fake = marine_ftp()
    reader = ProductSummaryReader(fake)
    reader.enrich([cap()], NOW)
    reissued = capture("IDN20400.cap.xml").replace(
        b"AusBoM-IDN20400-2026-11-03T23:29:52+00:00", b"AusBoM-IDN20400-2026-11-03T23:29:51+00:00"
    )
    warning = parse_cap(reissued)
    assert warning is not None

    reader.enrich([warning], NOW)

    assert fake.fetches == ["IDN20400.xml", "IDN20400.xml"]


def test_a_block_with_a_description_costs_no_request() -> None:
    fake = FakeFtp({})
    warning = cap("IDQ20829.cap.xml")

    (result,) = ProductSummaryReader(fake).enrich([warning], NOW)

    assert (fake.listings, fake.fetches) == ([], [])
    assert result == warning


def test_an_ended_block_costs_no_request() -> None:
    fake = marine_ftp()

    ProductSummaryReader(fake).enrich([cap()], AFTER_EXPIRY)

    assert (fake.listings, fake.fetches) == ([], [])


def test_a_product_with_no_xml_is_remembered_and_costs_nothing_on_the_next_refresh() -> None:
    fake = FakeFtp({})
    reader = ProductSummaryReader(fake)

    first = reader.enrich([cap()], NOW)
    second = reader.enrich([cap()], NOW)

    assert summaries(first[0]) == ["", ""]
    assert summaries(second[0]) == ["", ""]
    assert fake.listings == ["IDN20400.xml"]
    assert fake.fetches == []


@pytest.mark.parametrize("failing", ["error", "fetch_error"])
def test_a_failed_read_leaves_the_summary_out_and_is_tried_again(failing: str) -> None:
    fake = marine_ftp()
    setattr(fake, failing, BomFtpError("stalled"))
    reader = ProductSummaryReader(fake)

    (broken,) = reader.enrich([cap()], NOW)
    setattr(fake, failing, None)
    (recovered,) = reader.enrich([cap()], NOW)

    assert summaries(broken) == ["", ""]
    assert summaries(recovered) == [GALE, STRONG]


def test_an_empty_xml_is_not_remembered_so_the_next_refresh_tries_again() -> None:
    fake = FakeFtp({"IDN20400.xml": b""})
    reader = ProductSummaryReader(fake)

    (first,) = reader.enrich([cap()], NOW)
    fake.put("IDN20400.xml", capture("IDN20400.xml"))
    (second,) = reader.enrich([cap()], NOW)

    assert summaries(first) == ["", ""]
    assert summaries(second) == [GALE, STRONG]


def test_an_xml_older_than_its_cap_file_is_not_used_and_is_tried_again() -> None:
    newer = capture("IDN20400.cap.xml").replace(CAP_SENT, b"2026-11-04T00:24:50+00:00")
    warning = parse_cap(newer)
    assert warning is not None
    fake = marine_ftp()
    reader = ProductSummaryReader(fake)

    first = reader.enrich([warning], NOW)
    reader.enrich([warning], NOW)

    assert summaries(first[0]) == ["", ""]
    assert fake.fetches == ["IDN20400.xml", "IDN20400.xml"]


def test_a_block_whose_codes_match_no_hazard_gets_no_summary() -> None:
    warning = cap()
    elsewhere = replace(
        warning,
        infos=(replace(warning.infos[0], area_codes=frozenset({"NSW_MW099"})), warning.infos[1]),
    )

    (result,) = ProductSummaryReader(marine_ftp()).enrich([elsewhere], NOW)

    assert summaries(result) == ["", STRONG]


def test_the_reader_forgets_a_product_that_has_left_the_feed() -> None:
    fake = marine_ftp()
    reader = ProductSummaryReader(fake)
    reader.enrich([cap()], NOW)
    reader.enrich([], NOW)

    reader.enrich([cap()], NOW)

    assert fake.fetches == ["IDN20400.xml", "IDN20400.xml"]
