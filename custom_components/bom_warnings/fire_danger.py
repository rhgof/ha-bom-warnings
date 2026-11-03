"""BoM fire danger ratings (IDN10016 and its state equivalents): the parser, and what an entry
remembers between issues.

No Home Assistant imports. Every state's product has the same shape: `fire-district` areas keyed
by the same code as the fire weather district shapefile (`IDM00007`), each with four daily
`forecast-period`s carrying a `fire_danger` text and a `fire_behaviour_index`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any
from xml.etree import ElementTree as ET

from .cap import parse_xml
from .ftp import BomFtpClient, BomFtpError

_LOGGER = logging.getLogger(__name__)

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


@dataclass(frozen=True, slots=True)
class FireMemory:
    """Ratings seen in earlier issues of one district, so the afternoon issue (which starts
    tomorrow) does not erase today's. Immutable, so "did it change" is a plain comparison."""

    district: str = ""
    # In date order. A period is only ever shown on its own local date, so it expires with its day.
    periods: tuple[FireDangerPeriod, ...] = ()

    @property
    def by_date(self) -> dict[date, FireDangerPeriod]:
        return {p.date: p for p in self.periods}

    def to_dict(self) -> dict[str, Any]:
        return {
            "district": self.district,
            "periods": [
                {
                    "date": p.date.isoformat(),
                    "level": p.level,
                    "fire_behaviour_index": p.fire_behaviour_index,
                }
                for p in self.periods
            ],
        }

    @classmethod
    def from_dict(cls, data: object) -> FireMemory | None:
        """Read what `to_dict` wrote. None for empty or damaged data; the next issue refills it."""
        if not isinstance(data, Mapping):
            return None
        try:
            periods = (
                FireDangerPeriod(
                    date.fromisoformat(item["date"]), item["level"], item["fire_behaviour_index"]
                )
                for item in data["periods"]
            )
            return cls(data["district"], tuple(sorted(periods, key=lambda p: p.date)))
        except KeyError, TypeError, ValueError:
            return None


@dataclass(frozen=True, slots=True)
class FireDangerView:
    """One entry's fire district: the latest issue, plus days remembered from earlier issues."""

    product_id: str
    issued: datetime | None
    district_code: str
    district_name: str
    # Every period of the latest issue, in date order.
    forecast: tuple[FireDangerPeriod, ...]
    by_date: Mapping[date, FireDangerPeriod]
    # The product's own local offset, which decides what "today" means for its district.
    tz: tzinfo

    def period(self, day_offset: int, now: datetime) -> FireDangerPeriod | None:
        """The rating for today (offset 0) or a later day, where today is the district's own."""
        day = now.astimezone(self.tz).date() + timedelta(days=day_offset)
        return self.by_date.get(day)


def derive(
    memory: FireMemory,
    products: Mapping[str, FireDangerProduct],
    area_codes: Iterable[str],
    now: datetime,
    default_tz: tzinfo,
) -> tuple[FireMemory, FireDangerView | None]:
    """This entry's fire district and what it now remembers.

    With no matching district the memory is returned as it was, so a product that goes missing
    for a while does not make the entry forget.
    """
    match = match_district(products, area_codes)
    if match is None:
        return memory, None
    product, district = match
    remembered = memory.by_date if memory.district == district.code else {}
    # The latest issue wins for any day both cover.
    remembered = {**remembered, **{p.date: p for p in district.periods}}
    tz = product.issued.tzinfo if product.issued and product.issued.tzinfo else default_tz
    local_today = now.astimezone(tz).date()
    kept = {d: p for d, p in remembered.items() if d >= local_today - timedelta(days=1)}
    view = FireDangerView(
        product_id=product.product_id,
        issued=product.issued,
        district_code=district.code,
        district_name=district.name,
        forecast=district.periods,
        by_date=kept,
        tz=tz,
    )
    return FireMemory(district.code, tuple(kept[d] for d in sorted(kept))), view


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


class FireDangerReader:
    """Keeps the parsed fire danger products and fetches one only when its listing line changes.

    This step is optional: it never raises, so a failure here cannot reach the warnings refresh.
    Whatever goes wrong, the previous parse (or none) stays.
    """

    def __init__(self, ftp: BomFtpClient) -> None:
        self._ftp = ftp
        # Product id -> (listing line it was fetched under, parsed product).
        self._seen: dict[str, tuple[str, FireDangerProduct]] = {}

    def _refresh_one(self, product_id: str) -> None:
        name = f"{product_id}.xml"
        try:
            entries = self._ftp.list_files(name)
            entry = next((e for e in entries if e.name == name), None)
            known = self._seen.get(product_id)
            if entry is None or (known and known[0] == entry.raw):
                return
            data = self._ftp.fetch(name)
        except BomFtpError as err:
            _LOGGER.debug("Could not read fire danger product %s: %s", product_id, err)
            return
        if (product := parse_fire_danger(data or b"")) is None:
            # Not recorded under this line, so the next refresh tries the file again.
            _LOGGER.debug("Fire danger product %s is empty or unreadable", product_id)
            return
        self._seen[product_id] = (entry.raw, product)

    def refresh(self, product_ids: Iterable[str]) -> dict[str, FireDangerProduct]:
        """Blocking, so run it in an executor. Returns the latest parse of each wanted product."""
        wanted = set(product_ids)
        self._seen = {pid: seen for pid, seen in self._seen.items() if pid in wanted}
        for product_id in sorted(wanted):
            self._refresh_one(product_id)
        return {pid: product for pid, (_, product) in self._seen.items()}
