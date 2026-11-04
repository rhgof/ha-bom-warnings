"""The product XML parser against every captured product, and against codes it has not seen.

The captures in `tests/fixtures/products/` are real BoM output. The two variants made inside a test
(codes it has never seen, an embedded map image) change a real file in memory; no thunderstorm
product, which is the one that embeds a map, was current when the captures were taken.
"""

import base64
from datetime import UTC, datetime
from pathlib import Path

import pytest

from custom_components.bom_warnings.cap import parse_cap
from custom_components.bom_warnings.product_xml import HazardArea, parse_product

CAPTURES = Path(__file__).parent / "fixtures" / "products" / "2026-11-03T2348Z"
PRODUCT_XMLS = sorted(p for p in CAPTURES.glob("*.xml") if not p.name.endswith(".cap.xml"))


def capture(name: str) -> bytes:
    return (CAPTURES / name).read_bytes()


@pytest.mark.parametrize("path", PRODUCT_XMLS, ids=lambda p: p.stem)
def test_every_captured_product_parses_and_covers_the_codes_its_cap_file_names(path: Path) -> None:
    product = parse_product(path.read_bytes())
    warning = parse_cap(capture(f"{path.stem}.cap.xml"))

    assert product is not None
    assert warning is not None
    assert product.identifier == path.stem
    assert product.hazards
    assert all(h.type and h.phase and h.areas for h in product.hazards)
    assert warning.area_codes <= {code for h in product.hazards for code in h.codes}


def test_a_flood_product_has_its_hazard_phase_severity_areas_and_sentence() -> None:
    product = parse_product(capture("IDQ20829.xml"))

    assert product is not None
    assert (product.identifier, product.phase) == ("IDQ20829", "UPD")
    assert product.sent == datetime(2026, 11, 3, 2, 30, 36, tzinfo=UTC)
    (hazard,) = product.hazards
    assert (hazard.type, hazard.phase, hazard.severity) == ("FLW", "UPD", "MOD")
    assert hazard.areas == (
        HazardArea(
            "QLD_RC170",
            "Condamine River downstream of Oakey Creek to Cotswold",
            "river-basin",
            "UPD",
        ),
        HazardArea("QLD_RS067", "Condamine River at Chinchilla Weir TW", "river-site", "UPD"),
        HazardArea("QLD_RS112", "Condamine River at Condamine", "river-site", "UPD"),
    )
    assert hazard.text.startswith("Moderate flooding is occurring along the Condamine River")


def test_a_final_flood_warning_says_fin_in_its_xml_though_its_cap_file_does_not() -> None:
    product = parse_product(capture("IDQ20835.xml"))
    warning = parse_cap(capture("IDQ20835.cap.xml"))

    assert product is not None
    assert warning is not None
    assert {h.phase for h in product.hazards} == {"FIN"}
    assert product.phase == "FIN"
    assert "final" not in warning.infos[0].headline.lower()


def test_the_marine_product_gives_each_hazard_its_strength_code() -> None:
    product = parse_product(capture("IDN20400.xml"))

    assert product is not None
    assert product.phase == "REN"
    assert [(h.type, h.severity) for h in product.hazards] == [("MWW", "GALE"), ("MWW", "STR")]


def test_codes_it_has_never_seen_are_kept_as_written() -> None:
    changed = (
        capture("IDN20400.xml")
        .replace(b'type="MWW"', b'type="NEWTYPE"')
        .replace(b'severity="STR"', b'severity="HURRICANE"')
        .replace(b'phase="REN"', b'phase="ODDPHASE"')
        .replace(b"<phase>REN</phase>", b"<phase>ODDPHASE</phase>")
    )

    product = parse_product(changed)

    assert product is not None
    assert {h.type for h in product.hazards} == {"NEWTYPE"}
    assert {h.severity for h in product.hazards} == {"GALE", "HURRICANE"}
    assert {h.phase for h in product.hazards} == {"ODDPHASE"}
    assert product.phase == "ODDPHASE"


def test_a_missing_attribute_is_an_empty_string_not_an_error() -> None:
    product = parse_product(capture("IDN20400.xml").replace(b'severity="STR"', b""))

    assert product is not None
    assert [h.severity for h in product.hazards] == ["GALE", ""]


def test_an_embedded_map_image_is_read_past_and_never_kept() -> None:
    payload = base64.b64encode(b"\x89PNG" + b"x" * 150_000).decode()
    image = f'<element type="warning_image">{payload}</element>'.encode()
    with_map = capture("IDN20400.xml").replace(
        b"</forecast-period>", image + b"</forecast-period>", 1
    )

    product = parse_product(with_map)

    assert product is not None
    assert len(with_map) > 200_000
    assert payload[:200] not in repr(product)
    assert len(repr(product)) < 5_000
    assert [h.severity for h in product.hazards] == ["GALE", "STR"]
