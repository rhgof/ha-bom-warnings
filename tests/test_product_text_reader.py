"""The reader that adds the broadcast text's facts to a thunderstorm warning's blocks.

Against the real products in `tests/fixtures/products/2026-11-15T0343Z-thunderstorm`. It fetches the
2 to 3 KB `.txt`, never the 100 to 250 KB product XML, and only for a current thunderstorm block.
"""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from custom_components.bom_warnings.cap import CapWarning, Phase, parse_cap
from custom_components.bom_warnings.ftp import BomFtpError
from custom_components.bom_warnings.product_text import ProductTextReader

from .fake_ftp import FakeFtp

SNAPSHOT = Path(__file__).parent / "fixtures" / "products" / "2026-11-15T0343Z-thunderstorm"
NOW = datetime(2026, 11, 15, 3, 50, tzinfo=UTC)


def cap(product: str) -> CapWarning:
    warning = parse_cap((SNAPSHOT / f"{product}.cap.xml").read_bytes())
    assert warning is not None
    return warning


def ftp(*products: str) -> FakeFtp:
    return FakeFtp({f"{p}.txt": (SNAPSHOT / f"{p}.txt").read_bytes() for p in products})


def test_a_detailed_warning_gets_its_kind_hazard_and_next_issue_in_utc() -> None:
    reader = ProductTextReader(ftp("IDN21035"))

    (warning,) = reader.enrich([cap("IDN21035")], NOW)

    update = warning.infos[0]
    assert update.detailed is True
    assert update.hazard == "Damaging winds and large hailstones"
    # 3:10 pm in a +11:00 zone, which the CAP sent time (03:40:53Z) and "Issued at 2:40 pm" give.
    assert update.next_issue == datetime(2026, 11, 15, 4, 10, tzinfo=UTC)


def test_a_broad_warning_is_not_detailed() -> None:
    reader = ProductTextReader(ftp("IDN21033"))

    (warning,) = reader.enrich([cap("IDN21033")], NOW)

    assert warning.infos[0].detailed is False
    assert warning.infos[0].next_issue == datetime(2026, 11, 15, 6, 40, tzinfo=UTC)


def test_the_cancelling_block_of_a_product_is_left_alone() -> None:
    reader = ProductTextReader(ftp("IDN21035"))

    (warning,) = reader.enrich([cap("IDN21035")], NOW)

    cancelled = next(i for i in warning.infos if i.phase is Phase.CANCELLED)
    assert (cancelled.detailed, cancelled.hazard, cancelled.next_issue) == (False, "", None)


def test_the_text_is_listed_by_exact_name_fetched_once_and_not_fetched_again() -> None:
    fake = ftp("IDN21035")
    reader = ProductTextReader(fake)

    reader.enrich([cap("IDN21035")], NOW)
    reader.enrich([cap("IDN21035")], NOW)

    assert fake.fetches == ["IDN21035.txt"]
    assert fake.listings == []


def test_a_reissued_product_is_read_again() -> None:
    fake = ftp("IDN21035")
    reader = ProductTextReader(fake)
    reader.enrich([cap("IDN21035")], NOW)

    reissued = replace(cap("IDN21035"), identifier="AusBoM-IDN21035-2026-11-15T04:10:00+00:00")
    reader.enrich([reissued], NOW)

    assert fake.fetches == ["IDN21035.txt", "IDN21035.txt"]


def test_a_block_of_another_type_costs_no_request() -> None:
    fake = ftp("IDN21035")
    reader = ProductTextReader(fake)
    flood = cap("IDN21035")
    flood = replace(flood, infos=tuple(replace(i, event="Riverine Flood") for i in flood.infos))

    reader.enrich([flood], NOW)

    assert fake.fetches == []


def test_an_ended_block_costs_no_request() -> None:
    fake = ftp("IDN21035")
    reader = ProductTextReader(fake)
    after_expiry = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)

    reader.enrich([cap("IDN21035")], after_expiry)

    assert fake.fetches == []


def test_a_failed_read_leaves_the_facts_out_and_is_tried_again() -> None:
    fake = ftp("IDN21035")
    fake.fetch_error = BomFtpError("timed out")
    reader = ProductTextReader(fake)

    (warning,) = reader.enrich([cap("IDN21035")], NOW)
    assert warning.infos[0].detailed is False
    fake.fetch_error = None
    (warning,) = reader.enrich([cap("IDN21035")], NOW)

    assert warning.infos[0].detailed is True


@pytest.mark.parametrize("content", [None, b""], ids=["absent", "empty"])
def test_an_absent_or_empty_text_is_remembered_and_costs_nothing_on_the_next_refresh(
    content: bytes | None,
) -> None:
    fake = ftp()
    if content is not None:
        fake.files["IDN21035.txt"] = content
    reader = ProductTextReader(fake)

    reader.enrich([cap("IDN21035")], NOW)
    (warning,) = reader.enrich([cap("IDN21035")], NOW)

    assert fake.fetches == ["IDN21035.txt"]
    assert warning.infos[0].detailed is False


def test_the_reader_forgets_a_product_that_has_left_the_feed() -> None:
    fake = ftp("IDN21035")
    reader = ProductTextReader(fake)
    reader.enrich([cap("IDN21035")], NOW)

    reader.enrich([], NOW)
    reader.enrich([cap("IDN21035")], NOW)

    assert fake.fetches == ["IDN21035.txt", "IDN21035.txt"]
