"""Fetching fire danger products: change detection and isolation from every failure."""

from pathlib import Path

import pytest

from custom_components.bom_warnings.fire_danger import FireDangerReader, fire_product_ids
from custom_components.bom_warnings.ftp import BomFtpError, BomFtpRejectedError

from .fake_ftp import FakeFtp

FIXTURES = Path(__file__).parent / "fixtures" / "fire_danger"
NSW = "IDN10016"
NSW_FILE = f"{NSW}.xml"
CAPTURE = (FIXTURES / NSW_FILE).read_bytes()


def greater_sydney(reader_result: dict) -> str:
    return reader_result[NSW].districts["NSW_FW004"].periods[0].level


def test_first_refresh_lists_the_exact_file_and_fetches_it_once() -> None:
    ftp = FakeFtp({NSW_FILE: CAPTURE, "IDN36631.cap.xml": b"<alert/>"})

    result = FireDangerReader(ftp).refresh({NSW})

    assert greater_sydney(result) == "moderate"
    assert ftp.listings == [NSW_FILE]
    assert ftp.fetches == [NSW_FILE]


def test_an_unchanged_listing_line_is_not_fetched_again() -> None:
    ftp = FakeFtp({NSW_FILE: CAPTURE})
    reader = FireDangerReader(ftp)
    reader.refresh({NSW})

    result = reader.refresh({NSW})

    assert greater_sydney(result) == "moderate"
    assert ftp.listings == [NSW_FILE, NSW_FILE]
    assert ftp.fetches == [NSW_FILE]


def test_a_changed_listing_line_fetches_exactly_once_more() -> None:
    ftp = FakeFtp({NSW_FILE: CAPTURE})
    reader = FireDangerReader(ftp)
    reader.refresh({NSW})
    ftp.put(NSW_FILE, CAPTURE.replace(b">Moderate<", b">Extreme<", 1))

    result = reader.refresh({NSW})
    reader.refresh({NSW})

    # The first "Moderate" in the file is Far North Coast's second period.
    assert result[NSW].districts["NSW_FW001"].periods[1].level == "extreme"
    assert ftp.fetches == [NSW_FILE, NSW_FILE]


def test_only_the_requested_products_are_listed() -> None:
    ftp = FakeFtp({NSW_FILE: CAPTURE})

    result = FireDangerReader(ftp).refresh(set())

    assert result == {}
    assert ftp.listings == []


@pytest.mark.parametrize(
    "failure",
    ["list_timeout", "list_rejected", "fetch_timeout", "missing_from_listing", "empty", "garbage"],
)
def test_a_failing_step_keeps_the_previous_product_and_never_raises(failure: str) -> None:
    ftp = FakeFtp({NSW_FILE: CAPTURE})
    reader = FireDangerReader(ftp)
    reader.refresh({NSW})
    ftp.put(NSW_FILE, CAPTURE)  # a new listing line, so the next refresh tries to fetch
    changes = {
        "list_timeout": lambda: setattr(ftp, "error", BomFtpError("timed out")),
        "list_rejected": lambda: setattr(ftp, "error", BomFtpRejectedError("550 no")),
        "fetch_timeout": lambda: setattr(ftp, "fetch_error", BomFtpError("stalled")),
        "missing_from_listing": lambda: ftp.files.pop(NSW_FILE),
        "empty": lambda: ftp.vanished.add(NSW_FILE),
        "garbage": lambda: ftp.files.update({NSW_FILE: b"<html>nope</html>"}),
    }
    changes[failure]()

    result = reader.refresh({NSW})

    assert greater_sydney(result) == "moderate"


@pytest.mark.parametrize(
    "files",
    [{}, {NSW_FILE: b""}, {NSW_FILE: b"garbage"}],
    ids=["missing", "empty", "malformed"],
)
def test_without_a_previous_product_a_bad_file_gives_nothing(files: dict[str, bytes]) -> None:
    result = FireDangerReader(FakeFtp(files)).refresh({NSW})

    assert result == {}


def test_a_failed_fetch_is_retried_on_the_next_refresh() -> None:
    ftp = FakeFtp({NSW_FILE: CAPTURE}, vanished={NSW_FILE})
    reader = FireDangerReader(ftp)
    assert reader.refresh({NSW}) == {}

    ftp.vanished.clear()

    assert greater_sydney(reader.refresh({NSW})) == "moderate"
    assert ftp.fetches == [NSW_FILE, NSW_FILE]


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        (["NSW_FW004", "NSW_PW005"], {"IDN10016"}),
        (["NSW_FW008"], {"IDN10016"}),  # the ACT is published in the NSW product
        (["QLD_FW002", "VIC_FW001"], {"IDQ13016", "IDV18555"}),
        (["NSW_PW005", "NSW_ME001"], set()),
        (["XX_FW001"], set()),
        ([], set()),
    ],
)
def test_products_wanted_come_from_the_fire_weather_codes(
    codes: list[str], expected: set[str]
) -> None:
    assert fire_product_ids(codes) == expected
