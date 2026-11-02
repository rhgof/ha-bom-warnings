"""Tests for reading current warnings through the FTP interface."""

from pathlib import Path

import pytest

from custom_components.bom_warnings.feed import WarningReader, read_current_warnings
from custom_components.bom_warnings.ftp import BomFtpError, BomFtpRejectedError, parse_listing_line
from tests.fake_ftp import FakeFtp

CAP = Path(__file__).parent / "fixtures" / "cap"


def recorded() -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in CAP.glob("*.cap.xml")}


def test_returns_one_warning_per_file():
    warnings = read_current_warnings(FakeFtp(recorded()))
    assert {w.product_id for w in warnings} == {n.removesuffix(".cap.xml") for n in recorded()}


def test_empty_files_are_skipped():
    files = recorded() | {"IDQ99999.cap.xml": b""}
    warnings = read_current_warnings(FakeFtp(files))
    assert len(warnings) == len(recorded())


def test_files_that_vanish_between_list_and_fetch_are_skipped():
    files = recorded()
    gone = next(iter(files))
    warnings = read_current_warnings(FakeFtp(files, vanished={gone}))
    assert gone.removesuffix(".cap.xml") not in {w.product_id for w in warnings}
    assert len(warnings) == len(files) - 1


def test_unparseable_files_are_skipped():
    files = recorded() | {"IDQ99998.cap.xml": b"<not-cap"}
    assert len(read_current_warnings(FakeFtp(files))) == len(recorded())


def test_no_files_gives_empty_list():
    assert read_current_warnings(FakeFtp({})) == []


def test_connection_errors_surface_as_one_type():
    with pytest.raises(BomFtpError):
        read_current_warnings(FakeFtp({}, error=BomFtpError("timed out")))


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("-rw-r--r--  1 ftp ftp  2229 Nov  2 10:14 IDQ21013.cap.xml", ("IDQ21013.cap.xml", 2229)),
        ("-rw-r--r--  1 ftp ftp     0 Nov  2 10:14 IDQ20000.cap.xml", ("IDQ20000.cap.xml", 0)),
    ],
)
def test_parse_listing_line(line: str, expected: tuple[str, int]):
    entry = parse_listing_line(line)
    assert entry is not None
    assert (entry.name, entry.size, entry.raw) == (*expected, line)


@pytest.mark.parametrize("line", ["", "total 4", "drwxr-xr-x 2 ftp ftp 4096 Nov 2 10:14 sub"])
def test_parse_listing_line_ignores_non_files(line: str):
    assert parse_listing_line(line) is None


def ids(warnings) -> set[str]:
    return {w.product_id for w in warnings}


def test_unchanged_listing_causes_no_fetches():
    ftp = FakeFtp(recorded())
    reader = WarningReader(ftp)
    first = reader.refresh()
    ftp.fetches.clear()
    assert ids(reader.refresh()) == ids(first)
    assert ftp.fetches == []


def test_removed_warning_disappears():
    ftp = FakeFtp(recorded())
    reader = WarningReader(ftp)
    reader.refresh()
    ftp.remove("IDQ21013.cap.xml")
    result = reader.refresh()
    assert "IDQ21013" not in ids(result)
    assert len(result) == len(recorded()) - 1


def test_changed_line_refetches_only_that_file():
    files = recorded()
    ftp = FakeFtp(files)
    reader = WarningReader(ftp)
    reader.refresh()
    ftp.fetches.clear()
    ftp.put("IDQ21013.cap.xml", files["IDQ21033.cap.xml"])
    result = reader.refresh()
    assert ftp.fetches == ["IDQ21013.cap.xml"]
    # The new content carries the other file's product id, so the old IDQ21013 content is gone.
    assert "IDQ21013" not in ids(result)
    assert [w.product_id for w in result].count("IDQ21033") == 2


def test_new_file_is_fetched():
    files = recorded()
    held = files.pop("IDQ21013.cap.xml")
    ftp = FakeFtp(files)
    reader = WarningReader(ftp)
    reader.refresh()
    ftp.fetches.clear()
    ftp.put("IDQ21013.cap.xml", held)
    assert "IDQ21013" in ids(reader.refresh())
    assert ftp.fetches == ["IDQ21013.cap.xml"]


def test_wildcard_listing_error_falls_back_to_full_listing():
    ftp = FakeFtp(recorded() | {"readme.txt": b"hello"})
    ftp.wildcard_error = BomFtpRejectedError("550 no match")
    result = WarningReader(ftp).refresh()
    assert ids(result) == ids(read_current_warnings(FakeFtp(recorded())))
    assert "readme.txt" not in ftp.fetches


def test_wildcard_timeout_raises_without_a_second_listing():
    ftp = FakeFtp(recorded())
    ftp.wildcard_error = BomFtpError("timed out")
    with pytest.raises(BomFtpError):
        WarningReader(ftp).refresh()
    assert ftp.listings == ["*.cap.xml"]


def test_rejected_wildcard_falls_back_to_exactly_one_full_listing():
    ftp = FakeFtp(recorded())
    ftp.wildcard_error = BomFtpRejectedError("500 bad")
    WarningReader(ftp).refresh()
    assert ftp.listings == ["*.cap.xml", "*"]


def test_full_listing_failure_surfaces():
    ftp = FakeFtp({}, error=BomFtpError("down"))
    with pytest.raises(BomFtpError):
        WarningReader(ftp).refresh()


def test_vanished_file_is_retried_next_refresh():
    ftp = FakeFtp(recorded(), vanished={"IDQ21013.cap.xml"})
    reader = WarningReader(ftp)
    assert "IDQ21013" not in ids(reader.refresh())
    ftp.vanished.clear()
    assert "IDQ21013" in ids(reader.refresh())


def test_changed_file_that_fails_refetch_keeps_previous_warning():
    files = recorded()
    ftp = FakeFtp(files)
    reader = WarningReader(ftp)
    reader.refresh()
    ftp.put("IDQ21013.cap.xml", files["IDQ21013.cap.xml"])
    ftp.vanished.add("IDQ21013.cap.xml")
    assert "IDQ21013" in ids(reader.refresh())


def test_changed_file_that_becomes_unparseable_keeps_previous_warning():
    ftp = FakeFtp(recorded())
    reader = WarningReader(ftp)
    reader.refresh()
    ftp.put("IDQ21013.cap.xml", b"<not-cap")
    assert "IDQ21013" in ids(reader.refresh())


def test_failed_changed_file_is_retried_next_refresh():
    files = recorded()
    ftp = FakeFtp(files)
    reader = WarningReader(ftp)
    reader.refresh()
    ftp.put("IDQ21013.cap.xml", files["IDQ21033.cap.xml"])
    ftp.vanished.add("IDQ21013.cap.xml")
    reader.refresh()
    ftp.vanished.clear()
    assert "IDQ21013" not in ids(reader.refresh())


def test_read_current_warnings_uses_wildcard_fallback():
    ftp = FakeFtp(recorded())
    ftp.wildcard_error = BomFtpRejectedError("550 no match")
    assert len(read_current_warnings(ftp)) == len(recorded())
