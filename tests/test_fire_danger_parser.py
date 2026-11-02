"""The pure IDN10016 parser, on the real capture and on damaged variants of it."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from custom_components.bom_warnings.fire_danger import (
    LEVEL_KEYS,
    PRODUCTS,
    FireDangerPeriod,
    parse_fire_danger,
)

CAPTURE = Path(__file__).parent / "fixtures" / "fire_danger" / "IDN10016.xml"


@pytest.fixture(scope="module")
def raw() -> bytes:
    return CAPTURE.read_bytes()


def test_all_twenty_one_districts_with_four_periods_each(raw: bytes) -> None:
    product = parse_fire_danger(raw)

    assert product is not None
    assert product.product_id == "IDN10016"
    assert sorted(product.districts) == [f"NSW_FW{n:03d}" for n in range(1, 22)]
    assert {len(d.periods) for d in product.districts.values()} == {4}


def test_issue_time_keeps_the_local_offset(raw: bytes) -> None:
    product = parse_fire_danger(raw)

    assert product is not None
    assert product.issued == datetime(2026, 11, 2, 16, 15, tzinfo=timezone(timedelta(hours=11)))


def test_greater_sydney_periods_match_the_capture(raw: bytes) -> None:
    product = parse_fire_danger(raw)

    assert product is not None
    district = product.districts["NSW_FW004"]
    assert district.name == "Greater Sydney Region"
    assert district.periods == (
        FireDangerPeriod(date(2026, 11, 3), "moderate", 16),
        FireDangerPeriod(date(2026, 11, 4), "moderate", 17),
        FireDangerPeriod(date(2026, 11, 5), "high", 28),
        FireDangerPeriod(date(2026, 11, 6), "moderate", 22),
    )


def test_no_rating_is_normalised_to_a_key(raw: bytes) -> None:
    product = parse_fire_danger(raw)

    assert product is not None
    assert product.districts["NSW_FW001"].periods[0].level == "no_rating"


def test_every_level_the_capture_uses_is_a_known_key(raw: bytes) -> None:
    product = parse_fire_danger(raw)

    assert product is not None
    levels = {p.level for d in product.districts.values() for p in d.periods}
    assert levels <= set(LEVEL_KEYS)


def test_the_region_summary_area_is_not_a_district(raw: bytes) -> None:
    product = parse_fire_danger(raw)

    assert product is not None
    assert "NSW_FA001" not in product.districts


@pytest.mark.parametrize(
    ("text", "expected_level"),
    [
        (b"High", "high"),
        (b"  HIGH ", "high"),
        (b"Catastrophic", "catastrophic"),
        (b"Extreme", "extreme"),
        (b"Code Red", "Code Red"),
    ],
)
def test_levels_are_normalised_and_unknown_ones_kept_verbatim(
    raw: bytes, text: bytes, expected_level: str
) -> None:
    # The first High in the capture is Far North Coast's third period.
    product = parse_fire_danger(raw.replace(b">High<", b">" + text + b"<", 1))

    assert product is not None
    assert product.districts["NSW_FW001"].periods[2].level == expected_level


def test_a_non_numeric_behaviour_index_becomes_none(raw: bytes) -> None:
    changed = raw.replace(b'"fire_behaviour_index">9<', b'"fire_behaviour_index">n/a<', 1)
    product = parse_fire_danger(changed)

    assert product is not None
    assert product.districts["NSW_FW001"].periods[0].fire_behaviour_index is None


def test_a_missing_district_leaves_the_others(raw: bytes) -> None:
    start = raw.index(b'<area aac="NSW_FW004"')
    end = raw.index(b'<area aac="NSW_FW005"')
    product = parse_fire_danger(raw[:start] + raw[end:])

    assert product is not None
    assert "NSW_FW004" not in product.districts
    assert len(product.districts) == 20


def test_a_missing_period_leaves_the_rest(raw: bytes) -> None:
    start = raw.index(b'<forecast-period index="4"')
    end = raw.index(b"</forecast-period>", start) + len(b"</forecast-period>")
    product = parse_fire_danger(raw[:start] + raw[end:])

    assert product is not None
    assert len(product.districts["NSW_FW001"].periods) == 3
    assert len(product.districts["NSW_FW002"].periods) == 4


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"   \n",
        b"not xml at all",
        b"<product><forecast>",
        b"<product/>",
        b"<other><area aac='NSW_FW001' type='fire-district'/></other>",
        b'<!DOCTYPE product [<!ENTITY a "b">]><product/>',
        b"\xff\xfe\x00",
    ],
)
def test_empty_or_malformed_input_returns_nothing(data: bytes) -> None:
    assert parse_fire_danger(data) is None


def test_a_product_with_no_issue_time_still_parses(raw: bytes) -> None:
    start = raw.index(b"<issue-time-local")
    end = raw.index(b"</issue-time-local>") + len(b"</issue-time-local>")
    product = parse_fire_danger(raw[:start] + raw[end:])

    assert product is not None
    assert product.issued is None


@pytest.mark.parametrize(("state", "product_id"), sorted(PRODUCTS.items()))
def test_every_state_product_has_a_real_capture_that_parses(state: str, product_id: str) -> None:
    product = parse_fire_danger((CAPTURE.parent / f"{product_id}.xml").read_bytes())

    assert product is not None
    assert product.product_id == product_id
    assert {code.split("_")[0] for code in product.districts} == {state}
    assert {len(d.periods) for d in product.districts.values()} == {4}
    assert product.issued is not None
