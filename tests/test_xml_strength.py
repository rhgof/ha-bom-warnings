"""A marine wind warning's strength from BoM's XML code, with the headline as the fallback.

CAP gives a gale and a strong wind block the same severity (Moderate), so the headline wording was
the only signal. The product XML carries a code for it: `STR` for strong and `GALE` for gale (both
seen on the NSW product `IDN20400`). The storm code has not been seen, so storm still comes from
the headline.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from custom_components.bom_warnings.active_warnings import ActiveWarning, covering
from custom_components.bom_warnings.cap import Phase, Severity, parse_cap
from custom_components.bom_warnings.ftp import BomFtpError
from custom_components.bom_warnings.product_xml import ProductSummaryReader

from .fake_ftp import FakeFtp

CAPTURES = Path(__file__).parent / "fixtures" / "products" / "2026-11-03T2348Z"
NOW = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)


def wind(headline: str, xml_severity: str = "", event: str = "Wind") -> ActiveWarning:
    return ActiveWarning(
        product_id="IDN20400",
        event=event,
        headline=headline,
        severity=Severity.MODERATE,
        effective=NOW,
        expires=NOW,
        phase=Phase.UPDATE,
        xml_severity=xml_severity,
    )


@pytest.mark.parametrize(
    ("headline", "code", "strength"),
    [
        pytest.param("Wind Warning for Moreton Bay", "STR", "strong", id="code-alone-strong"),
        pytest.param("Wind Warning for Moreton Bay", "GALE", "gale", id="code-alone-gale"),
        pytest.param("Strong Wind Warning for Moreton Bay", "GALE", "gale", id="code-wins"),
        pytest.param("Strong Wind Warning for Moreton Bay", "", "strong", id="headline-alone"),
        pytest.param("Storm Force Wind Warning for Moreton Bay", "", "storm", id="storm-headline"),
        pytest.param("Storm Force Wind Warning for Moreton Bay", "SEV", "storm", id="unknown-code"),
        pytest.param("Cancellation of Strong Wind Warning", "CAN", None, id="cancelled"),
    ],
)
def test_the_code_gives_the_strength_and_the_headline_is_the_fallback(
    headline: str, code: str, strength: str | None
) -> None:
    assert wind(headline, code).strength == strength


def test_a_code_on_an_event_without_a_strength_rule_is_ignored() -> None:
    assert wind("Severe Thunderstorm Warning", "GALE", event="Thunderstorm").strength is None


def strengths(xml: bool = True) -> dict[str, str | None]:
    """Each coast's strength from the real NSW product, with or without its XML beside it."""
    warning = parse_cap((CAPTURES / "IDN20400.cap.xml").read_bytes())
    assert warning is not None
    files = {"IDN20400.xml": (CAPTURES / "IDN20400.xml").read_bytes()} if xml else {}
    (enriched,) = ProductSummaryReader(FakeFtp(files)).enrich([warning], NOW)
    return {
        "eden": next(w.strength for w in covering([enriched], frozenset({"NSW_MW001"}), NOW)),
        "sydney": next(w.strength for w in covering([enriched], frozenset({"NSW_MW004"}), NOW)),
    }


def test_the_real_product_gives_gale_for_eden_and_strong_for_sydney() -> None:
    assert strengths() == {"eden": "gale", "sydney": "strong"}


def test_without_the_xml_the_headline_still_gives_the_same_strengths() -> None:
    assert strengths(xml=False) == {"eden": "gale", "sydney": "strong"}


def test_the_reader_passes_each_blocks_code_to_the_block() -> None:
    warning = parse_cap((CAPTURES / "IDN20400.cap.xml").read_bytes())
    assert warning is not None
    fake = FakeFtp({"IDN20400.xml": (CAPTURES / "IDN20400.xml").read_bytes()})

    (enriched,) = ProductSummaryReader(fake).enrich([warning], NOW)

    assert [info.xml_severity for info in enriched.infos] == ["GALE", "STR"]


def test_a_failed_read_leaves_the_code_out() -> None:
    warning = parse_cap((CAPTURES / "IDN20400.cap.xml").read_bytes())
    assert warning is not None
    fake = FakeFtp({"IDN20400.xml": (CAPTURES / "IDN20400.xml").read_bytes()})
    fake.fetch_error = BomFtpError("stalled")

    (enriched,) = ProductSummaryReader(fake).enrich([warning], NOW)

    assert [info.xml_severity for info in enriched.infos] == ["", ""]
