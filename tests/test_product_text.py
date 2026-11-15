"""The broadcast text of a thunderstorm warning, read from the real captured files.

The `.txt` file carries three things the CAP file does not: whether the warning is the Detailed
kind, the hazard line (`for DAMAGING WINDS and LARGE HAILSTONES`) and when the next warning is due.
"""

from datetime import datetime
from pathlib import Path

import pytest

from custom_components.bom_warnings.product_text import ProductText, parse_text

PRODUCTS = Path(__file__).parent / "fixtures" / "products"


def text(snapshot: str, product: str) -> bytes:
    return (PRODUCTS / snapshot / f"{product}.txt").read_bytes()


@pytest.mark.parametrize(
    ("snapshot", "product", "expected"),
    [
        (
            "2026-11-13T0625Z-thunderstorm",
            "IDN21033",
            ProductText(
                product_id="IDN21033",
                detailed=False,
                cancelled=False,
                hazard="Heavy rainfall, damaging winds and large hailstones",
                issued=datetime(2026, 11, 13, 17, 11),
                next_issue=datetime(2026, 11, 13, 20, 15),
            ),
        ),
        (
            "2026-11-13T0625Z-thunderstorm",
            "IDN21035",
            ProductText(
                product_id="IDN21035",
                detailed=True,
                cancelled=False,
                hazard="Heavy rainfall, damaging winds and large hailstones",
                issued=datetime(2026, 11, 13, 17, 13),
                next_issue=datetime(2026, 11, 13, 17, 45),
            ),
        ),
        (
            "2026-11-15T0343Z-thunderstorm",
            "IDN21033",
            ProductText(
                product_id="IDN21033",
                detailed=False,
                cancelled=False,
                hazard="Large, possibly giant hailstones and damaging winds",
                issued=datetime(2026, 11, 15, 14, 38),
                next_issue=datetime(2026, 11, 15, 17, 40),
            ),
        ),
        (
            "2026-11-15T0343Z-thunderstorm",
            "IDN21035",
            ProductText(
                product_id="IDN21035",
                detailed=True,
                cancelled=False,
                hazard="Damaging winds and large hailstones",
                issued=datetime(2026, 11, 15, 14, 40),
                next_issue=datetime(2026, 11, 15, 15, 10),
            ),
        ),
        (
            "2026-11-15T0516Z-thunderstorm",
            "IDN21033",
            ProductText(
                product_id="IDN21033",
                detailed=False,
                cancelled=False,
                hazard="Damaging winds and large hailstones",
                issued=datetime(2026, 11, 15, 16, 3),
                next_issue=datetime(2026, 11, 15, 19, 5),
            ),
        ),
        (
            "2026-11-15T0516Z-thunderstorm",
            "IDN21035",
            ProductText(
                product_id="IDN21035",
                detailed=True,
                cancelled=True,
                hazard="",
                issued=datetime(2026, 11, 15, 15, 34),
                next_issue=None,
            ),
        ),
    ],
    ids=lambda v: v.product_id if isinstance(v, ProductText) else v,
)
def test_a_captured_thunderstorm_text_reads_to_its_facts(
    snapshot: str, product: str, expected: ProductText
) -> None:
    assert parse_text(text(snapshot, product)) == expected


@pytest.mark.parametrize("data", [b"", b"\n\n", b"IDN21033\n"])
def test_a_text_with_no_title_is_not_a_product_text(data: bytes) -> None:
    assert parse_text(data) is None


def test_a_next_issue_after_midnight_is_the_next_day() -> None:
    data = (
        b"IDN21033\nAustralian Government Bureau of Meteorology\n\n"
        b"TOP PRIORITY FOR IMMEDIATE BROADCAST\n\nSevere Thunderstorm Warning\n"
        b"for DAMAGING WINDS\n\nFor people in X.\n\n"
        b"Issued at 11:30 pm Sunday, 15 November 2026.\n\n"
        b"The next warning is due to be issued by 12:30 am.\n"
    )

    parsed = parse_text(data)

    assert parsed is not None
    assert parsed.next_issue == datetime(2026, 11, 16, 0, 30)
