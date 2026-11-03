"""Parser for the BoM fire danger ratings products (IDN10016 and its state equivalents).

No Home Assistant imports. Every state's product has the same shape: `fire-district` areas keyed
by the same code as the fire weather district shapefile (`IDM00007`), each with four daily
`forecast-period`s carrying a `fire_danger` text and a `fire_behaviour_index`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from xml.etree import ElementTree as ET

from .cap import parse_xml

# One product per state, keyed by the prefix of the district code (`NSW_FW004`). The ACT has no
# product of its own: BoM publishes it in the NSW one as `NSW_FW008`. Adding a state is one line.
PRODUCTS = {
    "NSW": "IDN10016",
    "NT": "IDD10731",
    "QLD": "IDQ13016",
    "SA": "IDS10070",
    "TAS": "IDT13151",
    "VIC": "IDV18555",
    "WA": "IDW15100",
}

# Lowest first. The key is what the parser stores and what the enum sensor offers as an option.
LEVEL_KEYS = ("no_rating", "moderate", "high", "extreme", "catastrophic")

_DISTRICT = "fire-district"


@dataclass(frozen=True, slots=True)
class FireDangerPeriod:
    date: date
    # A key from LEVEL_KEYS, or the product's own text for a level this code does not know.
    level: str
    fire_behaviour_index: int | None


@dataclass(frozen=True, slots=True)
class FireDistrict:
    code: str
    name: str
    periods: tuple[FireDangerPeriod, ...]


@dataclass(frozen=True, slots=True)
class FireDangerProduct:
    product_id: str
    # Aware, in the offset BoM wrote (the state's local time); None if the product has no time.
    issued: datetime | None
    districts: dict[str, FireDistrict]


def fire_product_ids(area_codes: Iterable[str]) -> set[str]:
    """The products needed for these area codes: those with a fire weather district (`_FW`)."""
    return {
        PRODUCTS[prefix]
        for code in area_codes
        if (prefix := code.partition("_FW")[0]) in PRODUCTS and "_FW" in code
    }


def match_district(
    products: Mapping[str, FireDangerProduct], area_codes: Iterable[str]
) -> tuple[FireDangerProduct, FireDistrict] | None:
    """The district the codes name, by exact code (never by name), with the product it is in."""
    wanted = set(area_codes)
    for product_id in sorted(products):
        product = products[product_id]
        for code in sorted(wanted & product.districts.keys()):
            return product, product.districts[code]
    return None


def normalise_level(text: str) -> str:
    """`No Rating` becomes `no_rating`; a level this code does not know is kept verbatim."""
    key = "_".join(text.lower().split())
    return key if key in LEVEL_KEYS else " ".join(text.split())


def _timestamp(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat((value or "").strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _period(el: ET.Element) -> FireDangerPeriod | None:
    start = _timestamp(el.get("start-time-local"))
    level = (el.findtext("text[@type='fire_danger']") or "").strip()
    if start is None or not level:
        return None
    index = (el.findtext("element[@type='fire_behaviour_index']") or "").strip()
    return FireDangerPeriod(
        start.date(), normalise_level(level), int(index) if index.isdecimal() else None
    )


def parse_fire_danger(data: bytes) -> FireDangerProduct | None:
    """Parse one product. Return None for empty, malformed or district-less input."""
    root = parse_xml(data)
    if root is None or root.tag != "product":
        return None
    districts: dict[str, FireDistrict] = {}
    for area in root.iter("area"):
        code = area.get("aac")
        if area.get("type") != _DISTRICT or not code:
            continue
        periods = tuple(p for el in area.findall("forecast-period") if (p := _period(el)))
        if periods:
            districts[code] = FireDistrict(code, area.get("description") or code, periods)
    if not districts:
        return None
    return FireDangerProduct(
        product_id=(root.findtext("amoc/identifier") or "").strip(),
        issued=_timestamp(root.findtext("amoc/issue-time-local")),
        districts=districts,
    )
