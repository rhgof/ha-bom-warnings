"""Tests for the CAP parser, run against recorded anonymous-FTP fixtures."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from custom_components.bom_warnings.cap import Phase, Severity, parse_cap

FIXTURES = Path(__file__).parent / "fixtures" / "cap"
NOW = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)


def load(product_id: str):
    return parse_cap((FIXTURES / f"{product_id}.cap.xml").read_bytes())


def test_product_id_comes_from_identifier():
    assert load("IDQ21013").product_id == "IDQ21013"


def test_heatwave_basic_fields():
    w = load("IDQ21013")
    (info,) = w.infos
    assert info.event == "Extreme Heat"
    assert info.severity is Severity.SEVERE
    assert info.expires == datetime(2026, 11, 2, 10, 14, 38, tzinfo=UTC)
    assert "QLD_PW001" in info.area_codes
    assert w.phase is Phase.UPDATE
    assert w.is_active(NOW)


def test_multiple_info_blocks_flood():
    w = load("IDQ20855")
    assert [i.severity for i in w.infos] == [Severity.MODERATE, Severity.MINOR]
    assert {"QLD_RC125", "QLD_RC126"} <= w.area_codes


def test_only_amoc_area_codes_are_kept():
    w = load("IDW21013")
    assert "AU-WA" not in w.area_codes
    assert {"WA_PW001", "WA_PW002"} <= w.area_codes


def test_alert_message_is_new():
    assert load("IDW21013").phase is Phase.NEW


def test_cancel_message_is_cancelled_and_inactive_even_before_expiry():
    w = load("IDN20400")
    assert w.phase is Phase.CANCELLED
    assert w.infos[0].expires > NOW
    assert not w.is_active(NOW)


def test_expired_warning_is_inactive():
    late = datetime(2026, 11, 5, tzinfo=UTC)
    assert not load("IDQ20855").is_active(late)


def test_thunderstorm_uses_metro_and_district_codes():
    assert any(c.startswith("QLD_ME") for c in load("IDQ21035").area_codes)
    assert any(c.startswith("QLD_PW") for c in load("IDQ21033").area_codes)


def test_unknown_severity_is_tolerated():
    assert load("IDQ21033").infos[0].severity is Severity.UNKNOWN


@pytest.mark.parametrize("raw", [b"", b"   ", b"<not-cap/>", b"garbage"])
def test_empty_or_invalid_input_returns_none(raw):
    assert parse_cap(raw) is None


def test_info_headline_cancellation_and_final_are_detected():
    xml = (FIXTURES / "IDQ20855.cap.xml").read_bytes()
    minor = b"Minor Flood Warning for Bulloo River downstream"
    final = xml.replace(minor, b"Final Flood Warning for Bulloo River downstream")
    w = parse_cap(final)
    assert [i.phase for i in w.infos] == [Phase.UPDATE, Phase.FINAL]
    cancel = xml.replace(minor, b"Cancellation of Flood Warning for Bulloo River downstream")
    assert parse_cap(cancel).infos[1].phase is Phase.CANCELLED
    assert w.is_active(NOW)  # the Moderate block is still current


def test_timestamps_without_offset_are_utc():
    raw = (FIXTURES / "IDQ21013.cap.xml").read_bytes().replace(b"+00:00</", b"</")
    w = parse_cap(raw)
    assert w.infos[0].expires.tzinfo is UTC
    assert w.is_active(NOW)


@pytest.mark.parametrize(
    "prolog",
    [
        b'<!DOCTYPE alert [<!ENTITY a "x">]>',
        b'<!DOCTYPE alert SYSTEM "http://example.invalid/x.dtd">',
    ],
)
def test_doctype_is_rejected(prolog: bytes):
    raw = (FIXTURES / "IDQ21013.cap.xml").read_bytes()
    head, _, body = raw.partition(b"?>")
    assert parse_cap(head + b"?>" + prolog + body) is None
