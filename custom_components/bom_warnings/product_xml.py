"""BoM's product XML (the `.xml` beside a CAP file), and what it adds to a block.

The XML of a product carries, for each hazard, BoM's type, phase and severity codes, its areas with
their codes, and some text. Two things CAP lacks are read from it:

- A marine wind CAP file has no `description`, so its blocks would have nothing to show. A block
  takes the text of the hazard whose codes overlap its own, for example "Strong Wind Warning for
  Coffs Coast, ... and Batemans Coast", and that hazard's strength code (`GALE`, `STR`).
- A final flood warning has CAP severity `Unknown` and no "Final" in its headline, but its hazard
  says `FIN`, so its block is marked final.

No Home Assistant imports, and the reader never raises: this step is optional, so whatever goes
wrong leaves the block as the CAP file says and cannot reach the warnings refresh, its failure
count or the repair issue.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

from .cap import CapWarning, Info, Phase, parse_xml
from .ftp import BomFtpClient, BomFtpError

_LOGGER = logging.getLogger(__name__)

# The thunderstorm XML embeds a map image (70 to 297 KB) and heatwave products run to 500 KB, so a
# file over this is not worth fetching on every change. Marine wind and flood files are far smaller.
MAX_XML_BYTES = 400_000

# Events whose block is marked final from the XML even though the CAP file has a description: a
# final flood warning has CAP severity `Unknown` and no "Final" in its headline, but its XML hazard
# says `FIN` (8 of the 16 flood products captured on 3 Nov 2026).
XML_PHASE_EVENTS = frozenset({"Riverine Flood"})
_FINAL_PHASE = "FIN"

_PHENOMENA = "warning_phenomena"
_AREAS = "warning_areas"
_SENTENCE = "warning"


@dataclass(frozen=True, slots=True)
class HazardArea:
    code: str
    description: str
    kind: str
    phase: str


@dataclass(frozen=True, slots=True)
class Hazard:
    """One `<hazard>`. The type, phase and severity are BoM's codes exactly as written.

    BoM publishes no code list, so none is interpreted here; an unseen code is kept, and a missing
    attribute is an empty string.
    """

    type: str
    phase: str
    severity: str
    areas: tuple[HazardArea, ...]
    # Marine wind: "Strong Wind Warning" and the coasts it covers, in words.
    phenomena: str = ""
    area_text: str = ""
    # Flood: one sentence about the warning.
    text: str = ""

    @property
    def codes(self) -> frozenset[str]:
        return frozenset(area.code for area in self.areas)

    @property
    def summary(self) -> str:
        """The one line a block shows, or an empty string for a hazard that has no such phrases."""
        return f"{self.phenomena} for {self.area_text}" if self.phenomena and self.area_text else ""


@dataclass(frozen=True, slots=True)
class Product:
    identifier: str
    sent: datetime | None
    phase: str
    hazards: tuple[Hazard, ...]


def _sent(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat((value or "").strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _hazard(el: ET.Element) -> Hazard:
    texts = {t.get("type"): (t.text or "").strip() for t in el.findall("text")}
    return Hazard(
        type=el.get("type") or "",
        phase=el.get("phase") or "",
        severity=el.get("severity") or "",
        areas=tuple(
            HazardArea(
                code, area.get("description") or "", area.get("type") or "", area.get("phase") or ""
            )
            for area in el.findall("area-list/area")
            if (code := area.get("aac"))
        ),
        phenomena=texts.get(_PHENOMENA, ""),
        area_text=texts.get(_AREAS, ""),
        text=texts.get(_SENTENCE, ""),
    )


def parse_product(data: bytes) -> Product | None:
    """Parse a product XML. None for anything that is not one.

    Only the hazards are read. The rest of the file, including any embedded map image, is parsed
    past and never kept.
    """
    root = parse_xml(data)
    if root is None or root.tag != "product":
        return None
    return Product(
        identifier=(root.findtext("amoc/identifier") or "").strip(),
        sent=_sent(root.findtext("amoc/sent-time")),
        phase=(root.findtext("amoc/phase") or "").strip(),
        hazards=tuple(_hazard(el) for el in root.iter("hazard")),
    )


def _hazard_for(info: Info, hazards: Sequence[Hazard], *, with_summary: bool) -> Hazard | None:
    """The hazard sharing the most area codes with the block, or None when none shares any.

    With `with_summary` only a hazard that has a summary line is considered, as for marine wind.
    """
    best = max(
        (h for h in hazards if h.summary or not with_summary),
        key=lambda h: len(h.codes & info.area_codes),
        default=None,
    )
    return best if best and best.codes & info.area_codes else None


def _needs_xml(info: Info, now: datetime) -> bool:
    """A current block whose CAP file leaves something the product XML supplies."""
    return info.is_active(now) and (not info.description or info.event in XML_PHASE_EVENTS)


def _enriched(info: Info, hazards: Sequence[Hazard]) -> Info:
    if not info.description and (hazard := _hazard_for(info, hazards, with_summary=True)):
        info = replace(info, xml_summary=hazard.summary, xml_severity=hazard.severity)
    if (
        info.event in XML_PHASE_EVENTS
        and info.phase is not Phase.FINAL
        and (hazard := _hazard_for(info, hazards, with_summary=False))
        and hazard.phase == _FINAL_PHASE
    ):
        info = replace(info, phase=Phase.FINAL)
    return info


class ProductSummaryReader:
    """Fills in what the product XML supplies: a summary and strength code for a block the CAP file
    gives no description (marine wind), and the final phase of a flood warning.

    It reads a product's XML only when a current block needs it, and then once per CAP
    issue: the issue's identifier changes whenever BoM re-issues, so an unchanged product costs no
    request, and a product found to have no XML is remembered the same way.
    """

    def __init__(self, ftp: BomFtpClient) -> None:
        self._ftp = ftp
        # Product id -> (identifier of the CAP issue it was read for, its hazards; none if absent).
        self._seen: dict[str, tuple[str, tuple[Hazard, ...]]] = {}

    def _read(self, warning: CapWarning) -> None:
        name = f"{warning.product_id}.xml"
        try:
            entry = next((e for e in self._ftp.list_files(name) if e.name == name), None)
            if entry is None or entry.size > MAX_XML_BYTES:
                # Absent, or too big to be worth fetching: either way not asked for again until
                # BoM re-issues the product.
                self._seen[warning.product_id] = (warning.identifier, ())
                return
            data = self._ftp.fetch(name)
        except BomFtpError as err:
            _LOGGER.debug("Could not read product XML %s: %s", name, err)
            return
        if (product := parse_product(data or b"")) is None:
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
        infos = tuple(_enriched(info, seen[1]) for info in warning.infos)
        return replace(warning, infos=infos)

    def enrich(self, warnings: Sequence[CapWarning], now: datetime) -> list[CapWarning]:
        """Blocking, so run it in an executor. Returns the warnings with summaries filled in."""
        wanted = {
            w.product_id: w for w in warnings if any(_needs_xml(info, now) for info in w.infos)
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
