"""When the weekly shapefile layer check is due, and the record that survives a restart.

Plain values and files: every time is an argument and nothing is patched.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.bom_warnings.layer_check import (
    LAYER_CHECK_INTERVAL,
    LAYER_CHECK_RECORD,
    LayerSchedule,
    read_record,
    write_record,
)

NOW = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)
WEEK = timedelta(days=7)


def test_the_interval_is_weekly() -> None:
    assert LAYER_CHECK_INTERVAL == WEEK


@pytest.mark.parametrize(
    ("record_age", "due_in"),
    [
        pytest.param(None, timedelta(0), id="no-record-is-due-at-once"),
        pytest.param(timedelta(days=1), timedelta(days=6), id="recent-record-waits"),
        pytest.param(timedelta(days=6, hours=23), timedelta(hours=1), id="nearly-a-week-waits"),
        pytest.param(WEEK, timedelta(0), id="a-week-old-is-due"),
        pytest.param(timedelta(days=30), timedelta(0), id="an-old-record-is-due"),
        # A clock change can leave a record ahead of now, which would postpone the check too long.
        pytest.param(timedelta(days=-2), timedelta(0), id="a-future-record-is-due"),
    ],
)
def test_a_loaded_schedule_follows_the_record(
    record_age: timedelta | None, due_in: timedelta
) -> None:
    record = None if record_age is None else NOW - record_age
    schedule = LayerSchedule.loaded(record, NOW)
    assert schedule.due(NOW + due_in)
    if due_in:
        assert not schedule.due(NOW + due_in - timedelta(seconds=1))


def test_a_started_check_is_not_due_again_for_a_week() -> None:
    schedule = LayerSchedule.loaded(None, NOW).started(NOW)
    assert not schedule.due(NOW)
    assert not schedule.due(NOW + WEEK - timedelta(seconds=1))
    assert schedule.due(NOW + WEEK)


def test_a_check_that_never_reached_the_server_is_due_again_at_once() -> None:
    schedule = LayerSchedule.loaded(None, NOW).started(NOW)
    assert not schedule.due(NOW + timedelta(minutes=10))
    assert schedule.unreached(NOW + timedelta(minutes=10)).due(NOW + timedelta(minutes=10))


def test_a_schedule_is_a_value_not_something_that_changes() -> None:
    first = LayerSchedule.loaded(None, NOW)
    first.started(NOW)
    assert first.due(NOW)


def test_a_missing_record_reads_as_nothing(tmp_path: Path) -> None:
    assert read_record(tmp_path) is None


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("not a time", id="garbage"),
        pytest.param("", id="empty"),
        # Without a timezone it cannot be compared with now, so it counts as no record.
        pytest.param("2026-11-03T06:00:00", id="no-timezone"),
    ],
)
def test_a_record_that_cannot_be_trusted_reads_as_nothing(tmp_path: Path, text: str) -> None:
    (tmp_path / LAYER_CHECK_RECORD).write_text(text)
    assert read_record(tmp_path) is None


def test_a_written_record_reads_back(tmp_path: Path) -> None:
    write_record(tmp_path, NOW)
    assert read_record(tmp_path) == NOW


def test_writing_creates_the_directory(tmp_path: Path) -> None:
    directory = tmp_path / "bom_warnings" / "spatial"
    write_record(directory, NOW)
    assert read_record(directory) == NOW


def test_a_record_that_cannot_be_written_is_not_an_error(tmp_path: Path) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("in the way")
    # A directory cannot be created under a file. The next start just checks again.
    write_record(blocker / "spatial", NOW)
    assert read_record(blocker / "spatial") is None
