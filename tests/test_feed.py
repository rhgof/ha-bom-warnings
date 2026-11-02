"""Tests for reading current warnings through the FTP interface."""

from pathlib import Path

import pytest

from custom_components.bom_warnings.feed import read_current_warnings
from custom_components.bom_warnings.ftp import BomFtpError, parse_listing_line
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
