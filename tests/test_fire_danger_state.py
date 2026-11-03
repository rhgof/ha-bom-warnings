"""What fire danger remembers between issues, tested without Home Assistant.

Time and the default timezone are arguments, so every day-boundary case is a plain function call.
"""

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from custom_components.bom_warnings.fire_danger import (
    FireDangerPeriod,
    FireDangerProduct,
    FireDistrict,
    FireMemory,
    derive,
)

SYDNEY = timezone(timedelta(hours=11))
PERTH = timezone(timedelta(hours=8))
CODE = "NSW_FW008"


def period(day: str, level: str = "high", index: int | None = 20) -> FireDangerPeriod:
    return FireDangerPeriod(date.fromisoformat(day), level, index)


def products(
    issued: str | None, *periods: FireDangerPeriod, code: str = CODE
) -> Mapping[str, FireDangerProduct]:
    district = FireDistrict(code, f"District {code}", periods)
    return {
        "IDN10016": FireDangerProduct(
            "IDN10016", datetime.fromisoformat(issued) if issued else None, {code: district}
        )
    }


def at(local: str) -> datetime:
    """A moment given in Sydney local time."""
    return datetime.fromisoformat(local).replace(tzinfo=SYDNEY).astimezone(UTC)


def today_of(memory_and_view: tuple[FireMemory, Any], now: datetime) -> FireDangerPeriod | None:
    _, view = memory_and_view
    return view.by_date.get(view.local_date(now))


MORNING = products(
    "2026-11-02T05:05:00+11:00",
    period("2026-11-02", "moderate"),
    period("2026-11-03", "high"),
    period("2026-11-04", "extreme"),
)
AFTERNOON = products(
    "2026-11-02T16:30:00+11:00",
    period("2026-11-03", "high"),
    period("2026-11-04", "extreme"),
    period("2026-11-05", "moderate"),
)


def test_the_latest_issue_wins_for_a_day_both_cover() -> None:
    first = derive(FireMemory(), MORNING, [CODE], at("2026-11-02T06:00"), SYDNEY)
    revised = products("2026-11-02T16:30:00+11:00", period("2026-11-03", "catastrophic"))
    _, view = derive(first[0], revised, [CODE], at("2026-11-02T17:00"), SYDNEY)
    assert view is not None
    assert view.by_date[date(2026, 11, 3)].level == "catastrophic"


def test_a_period_is_shown_on_its_own_local_date() -> None:
    result = derive(FireMemory(), MORNING, [CODE], at("2026-11-03T08:00"), SYDNEY)
    found = today_of(result, at("2026-11-03T08:00"))
    assert found is not None
    assert (found.date, found.level) == (date(2026, 11, 3), "high")


def test_a_local_date_that_differs_from_utc_picks_the_local_day() -> None:
    # 20:00 UTC on 2 November is 07:00 on 3 November in Sydney.
    now = datetime(2026, 11, 2, 20, 0, tzinfo=UTC)
    found = today_of(derive(FireMemory(), MORNING, [CODE], now, SYDNEY), now)
    assert found is not None
    assert found.date == date(2026, 11, 3)


def test_the_afternoon_issue_keeps_todays_rating() -> None:
    morning_memory, _ = derive(FireMemory(), MORNING, [CODE], at("2026-11-02T06:00"), SYDNEY)
    now = at("2026-11-02T17:00")
    # The afternoon issue starts tomorrow, so on its own it has nothing for today.
    result = derive(morning_memory, AFTERNOON, [CODE], now, SYDNEY)
    found = today_of(result, now)
    assert found is not None
    assert (found.date, found.level) == (date(2026, 11, 2), "moderate")


def test_a_restart_in_the_afternoon_keeps_todays_rating() -> None:
    morning_memory, _ = derive(FireMemory(), MORNING, [CODE], at("2026-11-02T06:00"), SYDNEY)
    restored = FireMemory.from_dict(json.loads(json.dumps(morning_memory.to_dict())))
    assert restored is not None
    now = at("2026-11-02T17:30")
    found = today_of(derive(restored, AFTERNOON, [CODE], now, SYDNEY), now)
    assert found is not None
    assert found.level == "moderate"


def test_a_new_district_forgets_the_old_one() -> None:
    old, _ = derive(FireMemory(), MORNING, [CODE], at("2026-11-02T06:00"), SYDNEY)
    other = products("2026-11-02T16:30:00+11:00", period("2026-11-03", "high"), code="NSW_FW001")
    memory, view = derive(old, other, ["NSW_FW001"], at("2026-11-02T17:00"), SYDNEY)
    assert memory.district == "NSW_FW001"
    assert view is not None
    assert date(2026, 11, 2) not in view.by_date


@pytest.mark.parametrize(
    ("now", "kept"),
    [
        ("2026-11-03T08:00", [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)]),
        ("2026-11-04T08:00", [date(2026, 11, 3), date(2026, 11, 4)]),
        ("2026-11-05T08:00", [date(2026, 11, 4)]),
    ],
)
def test_periods_older_than_yesterday_are_pruned(now: str, kept: list[date]) -> None:
    held = FireMemory(CODE, tuple(MORNING["IDN10016"].districts[CODE].periods))
    memory, _ = derive(held, {}, [CODE], at(now), SYDNEY)
    # With no product to match, nothing changes; pruning happens when a product matches.
    assert memory == held
    pruned, _ = derive(held, products("2026-11-05T05:05:00+11:00"), [CODE], at(now), SYDNEY)
    assert [p.date for p in pruned.periods] == kept


def test_no_match_gives_no_view_and_leaves_the_memory_alone() -> None:
    held, _ = derive(FireMemory(), MORNING, [CODE], at("2026-11-02T06:00"), SYDNEY)
    memory, view = derive(held, MORNING, ["VIC_FW001"], at("2026-11-02T06:00"), SYDNEY)
    assert view is None
    assert memory is held


def test_deriving_again_from_the_same_issue_changes_nothing() -> None:
    now = at("2026-11-02T06:00")
    first, _ = derive(FireMemory(), MORNING, [CODE], now, SYDNEY)
    second, _ = derive(first, MORNING, [CODE], now + timedelta(minutes=10), SYDNEY)
    assert second == first


def test_the_products_own_offset_decides_today() -> None:
    perth = products("2026-11-03T05:05:00+08:00", period("2026-11-03"), code="WA_FW001")
    # 23:00 UTC on 2 November is 07:00 on 3 November in Perth, whatever the default zone is.
    now = datetime(2026, 11, 2, 23, 0, tzinfo=UTC)
    _, view = derive(FireMemory(), perth, ["WA_FW001"], now, SYDNEY)
    assert view is not None
    assert view.tz.utcoffset(None) == PERTH.utcoffset(None)
    assert view.local_date(now) == date(2026, 11, 3)


def test_a_product_without_an_issue_time_falls_back_to_the_default_zone() -> None:
    untimed = products(None, period("2026-11-03"))
    now = datetime(2026, 11, 2, 20, 0, tzinfo=UTC)
    _, view = derive(FireMemory(), untimed, [CODE], now, SYDNEY)
    assert view is not None
    assert view.tz == SYDNEY


def test_the_view_describes_the_latest_issue() -> None:
    _, view = derive(FireMemory(), AFTERNOON, [CODE], at("2026-11-02T17:00"), SYDNEY)
    assert view is not None
    assert (view.product_id, view.district_code, view.district_name) == (
        "IDN10016",
        CODE,
        f"District {CODE}",
    )
    assert [p.date for p in view.forecast] == [date(2026, 11, d) for d in (3, 4, 5)]


def test_memory_survives_a_trip_through_a_dict() -> None:
    memory, _ = derive(FireMemory(), MORNING, [CODE], at("2026-11-02T06:00"), SYDNEY)
    assert FireMemory.from_dict(json.loads(json.dumps(memory.to_dict()))) == memory


def test_a_value_stored_before_the_state_machine_still_loads() -> None:
    stored = {
        "district": CODE,
        "periods": [
            {"date": "2026-11-02", "level": "moderate", "fire_behaviour_index": 12},
            {"date": "2026-11-03", "level": "high", "fire_behaviour_index": None},
        ],
    }
    memory = FireMemory.from_dict(stored)
    assert memory == FireMemory(
        CODE, (period("2026-11-02", "moderate", 12), period("2026-11-03", "high", None))
    )
    assert memory is not None
    assert memory.to_dict() == stored


@pytest.mark.parametrize(
    "stored",
    [
        None,
        {},
        "not a dict",
        {"district": CODE},
        {"periods": []},
        {"district": CODE, "periods": 5},
        {
            "district": CODE,
            "periods": [{"date": "nope", "level": "high", "fire_behaviour_index": 1}],
        },
        {"district": CODE, "periods": [{"level": "high", "fire_behaviour_index": 1}]},
    ],
)
def test_damaged_or_empty_stored_data_gives_nothing(stored: object) -> None:
    assert FireMemory.from_dict(stored) is None
