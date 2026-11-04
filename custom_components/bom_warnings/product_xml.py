"""BoM's product XML (the `.xml` beside a CAP file), and the summary it gives a marine wind block.

A marine wind CAP file has no `description`, so its blocks would have nothing to show. The product
XML of the same name carries, for each hazard, the phenomenon ("Strong Wind Warning"), the areas it
covers in words, and the area codes. A block takes the text of the hazard whose codes overlap its
own, for example "Strong Wind Warning for Coffs Coast, ... and Batemans Coast".

No Home Assistant imports, and the reader never raises: this step is optional, so whatever goes
wrong leaves the summary out and cannot reach the warnings refresh, its failure count or the repair
issue.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from .cap import CapWarning, Info, parse_xml
from .ftp import BomFtpClient, BomFtpError

_LOGGER = logging.getLogger(__name__)

_PHENOMENA = "warning_phenomena"
_AREAS = "warning_areas"


@dataclass(frozen=True, slots=True)
class HazardText:
    """One XML hazard: the area codes it covers and the two phrases that name it."""

    area_codes: frozenset[str]
    phenomena: str
    areas: str

    @property
    def summary(self) -> str:
        return f"{self.phenomena} for {self.areas}"


@dataclass(frozen=True, slots=True)
class ProductText:
    sent: datetime | None
    hazards: tuple[HazardText, ...]


def _sent(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat((value or "").strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_product_text(data: bytes) -> ProductText | None:
    """Parse the text of each hazard. None for anything that is not a product XML.

    A hazard without both phrases (floods carry a `warning` sentence instead) is left out, so a
    product of that kind gives no hazards and no summary.
    """
    root = parse_xml(data)
    if root is None or root.tag != "product":
        return None
    hazards: list[HazardText] = []
    for hazard in root.iter("hazard"):
        texts = {t.get("type"): (t.text or "").strip() for t in hazard.findall("text")}
        codes = frozenset(
            code for area in hazard.findall("area-list/area") if (code := area.get("aac"))
        )
        if codes and texts.get(_PHENOMENA) and texts.get(_AREAS):
            hazards.append(HazardText(codes, texts[_PHENOMENA], texts[_AREAS]))
    return ProductText(_sent(root.findtext("amoc/sent-time")), tuple(hazards))


def _hazard_for(info: Info, hazards: Sequence[HazardText]) -> HazardText | None:
    """The hazard sharing the most area codes with the block, or None when none shares any."""
    best = max(hazards, key=lambda h: len(h.area_codes & info.area_codes), default=None)
    return best if best and best.area_codes & info.area_codes else None


class ProductSummaryReader:
    """Fills `Info.xml_summary` for blocks the CAP file gives no description.

    It reads a product's XML only when a current block has no description, and then once per CAP
    issue: the issue's identifier changes whenever BoM re-issues, so an unchanged product costs no
    request, and a product found to have no XML is remembered the same way.
    """

    def __init__(self, ftp: BomFtpClient) -> None:
        self._ftp = ftp
        # Product id -> (identifier of the CAP issue it was read for, its hazards; none if absent).
        self._seen: dict[str, tuple[str, tuple[HazardText, ...]]] = {}

    def _read(self, warning: CapWarning) -> None:
        name = f"{warning.product_id}.xml"
        try:
            entries = self._ftp.list_files(name)
            if not any(entry.name == name for entry in entries):
                self._seen[warning.product_id] = (warning.identifier, ())
                return
            data = self._ftp.fetch(name)
        except BomFtpError as err:
            _LOGGER.debug("Could not read product XML %s: %s", name, err)
            return
        if (product := parse_product_text(data or b"")) is None:
            # Not remembered, so the next refresh tries the file again.
            _LOGGER.debug("Product XML %s is empty or unreadable", name)
            return
        if product.sent and warning.sent and product.sent < warning.sent:
            # The CAP file landed first; this is the previous issue's XML.
            _LOGGER.debug("Product XML %s is older than its CAP file", name)
            return
        self._seen[warning.product_id] = (warning.identifier, product.hazards)

    def _apply(self, warning: CapWarning) -> CapWarning:
        seen = self._seen.get(warning.product_id)
        if seen is None or seen[0] != warning.identifier:
            return warning
        infos = tuple(
            replace(info, xml_summary=hazard.summary)
            if not info.description and (hazard := _hazard_for(info, seen[1]))
            else info
            for info in warning.infos
        )
        return replace(warning, infos=infos)

    def enrich(self, warnings: Sequence[CapWarning], now: datetime) -> list[CapWarning]:
        """Blocking, so run it in an executor. Returns the warnings with summaries filled in."""
        wanted = {
            w.product_id: w
            for w in warnings
            if any(not i.description and i.is_active(now) for i in w.infos)
        }
        self._seen = {
            pid: seen
            for pid, seen in self._seen.items()
            if pid in wanted and seen[0] == wanted[pid].identifier
        }
        for product_id, warning in wanted.items():
            if product_id not in self._seen:
                self._read(warning)
        return [self._apply(w) for w in warnings]
