"""The "next warning is due" time in zones other than New South Wales.

These are arithmetic checks, not evidence of how BoM words anything elsewhere. They take the real
Detailed warning (`IDN21035`, 15 Nov 2026) and change only what a zone changes: the local clock
times in its text and the CAP sent time that the offset is worked out from. The text gives a local
time with no zone, so the integration finds the offset by comparing "Issued at" with the sent time.
What BoM sends in Queensland, South Australia and Western Australia is checked on a live warning
(#92).
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.bom_warnings.cap import CapWarning, parse_cap
from custom_components.bom_warnings.product_text import ProductTextReader

from .fake_ftp import FakeFtp

SNAPSHOT = Path(__file__).parent / "fixtures" / "products" / "2026-11-15T0343Z-thunderstorm"
NOW = datetime(2026, 11, 15, 3, 50, tzinfo=UTC)
# The CAP file is sent seconds after the text's minute, as the real one was (03:40:53Z, 2:40 pm).
SENT_LAG = timedelta(seconds=53)

ISSUED = "Issued at 2:40 pm Sunday, 15 November 2026."
NEXT = "The next warning is due to be issued by 3:10 pm."


def reader_for(issued: str, next_clock: str) -> ProductTextReader:
    text = (SNAPSHOT / "IDN21035.txt").read_text()
    assert ISSUED in text and NEXT in text
    text = text.replace(ISSUED, issued).replace(
        NEXT, f"The next warning is due to be issued by {next_clock}."
    )
    return ProductTextReader(FakeFtp({"IDN21035.txt": text.encode()}))


def warning_sent(sent: datetime) -> CapWarning:
    cap = parse_cap((SNAPSHOT / "IDN21035.cap.xml").read_bytes())
    assert cap is not None
    return replace(cap, sent=sent)


@pytest.mark.parametrize(
    ("issued", "issued_utc", "next_clock", "next_utc"),
    [
        pytest.param(
            "Issued at 2:40 pm Sunday, 15 November 2026.",
            datetime(2026, 11, 15, 3, 40, tzinfo=UTC),
            "3:10 pm",
            datetime(2026, 11, 15, 4, 10, tzinfo=UTC),
            id="new-south-wales-plus-11",
        ),
        pytest.param(
            "Issued at 2:40 pm Sunday, 15 November 2026.",
            datetime(2026, 11, 15, 4, 40, tzinfo=UTC),
            "3:10 pm",
            datetime(2026, 11, 15, 5, 10, tzinfo=UTC),
            id="queensland-plus-10",
        ),
        pytest.param(
            "Issued at 2:40 pm Sunday, 15 November 2026.",
            datetime(2026, 11, 15, 4, 10, tzinfo=UTC),
            "3:10 pm",
            datetime(2026, 11, 15, 4, 40, tzinfo=UTC),
            id="south-australia-plus-10-30",
        ),
        pytest.param(
            "Issued at 2:40 pm Sunday, 15 November 2026.",
            datetime(2026, 11, 15, 5, 10, tzinfo=UTC),
            "3:10 pm",
            datetime(2026, 11, 15, 5, 40, tzinfo=UTC),
            id="northern-territory-plus-9-30",
        ),
        pytest.param(
            "Issued at 2:40 pm Sunday, 15 November 2026.",
            datetime(2026, 11, 15, 6, 40, tzinfo=UTC),
            "3:10 pm",
            datetime(2026, 11, 15, 7, 10, tzinfo=UTC),
            id="western-australia-plus-8",
        ),
        pytest.param(
            "Issued at 11:40 pm Sunday, 15 November 2026.",
            datetime(2026, 11, 15, 13, 40, tzinfo=UTC),
            "12:10 am",
            datetime(2026, 11, 15, 14, 10, tzinfo=UTC),
            id="next-warning-after-local-midnight",
        ),
        pytest.param(
            "Issued at 8:40 am Sunday, 15 November 2026.",
            datetime(2026, 11, 14, 22, 40, tzinfo=UTC),
            "9:10 am",
            datetime(2026, 11, 14, 23, 10, tzinfo=UTC),
            id="local-day-ahead-of-the-utc-day",
        ),
    ],
)
def test_the_next_issue_is_the_utc_time_of_the_zones_clock(
    issued: str, issued_utc: datetime, next_clock: str, next_utc: datetime
) -> None:
    reader = reader_for(issued, next_clock)

    (found,) = reader.enrich([warning_sent(issued_utc + SENT_LAG)], NOW)

    assert found.infos[0].next_issue == next_utc
