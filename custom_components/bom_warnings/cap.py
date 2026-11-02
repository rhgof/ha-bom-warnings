"""Parser for Bureau of Meteorology CAP 1.2 warning files.

No Home Assistant imports, so this can become a standalone package later.
See bom-docs/Bureau_of_Meteorology_warning_products_user_guide.pdf, Appendix A.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from xml.etree import ElementTree as ET
from xml.parsers import expat

_NS = {"c": "urn:oasis:names:tc:emergency:cap:1.2"}
_AREA_CODE = "AMOC-AreaCode"


class Phase(StrEnum):
    NEW = "new"
    UPDATE = "update"
    FINAL = "final"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    UNKNOWN = "unknown"
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    EXTREME = "extreme"


@dataclass(frozen=True, slots=True)
class Info:
    event: str
    headline: str
    severity: Severity
    effective: datetime | None
    expires: datetime | None
    area_desc: str
    area_codes: frozenset[str]
    phase: Phase

    def is_active(self, now: datetime) -> bool:
        if self.phase in (Phase.CANCELLED, Phase.FINAL):
            return False
        return self.expires is None or self.expires > now


@dataclass(frozen=True, slots=True)
class CapWarning:
    product_id: str
    identifier: str
    sent: datetime | None
    phase: Phase
    infos: tuple[Info, ...]

    @property
    def area_codes(self) -> frozenset[str]:
        return frozenset().union(*(i.area_codes for i in self.infos))

    def is_active(self, now: datetime) -> bool:
        if self.phase is Phase.CANCELLED:
            return False
        return any(i.is_active(now) for i in self.infos)


def _text(el: ET.Element, tag: str) -> str:
    return (el.findtext(f"c:{tag}", namespaces=_NS) or "").strip()


def _time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # A naive value would raise TypeError when compared with an aware "now".
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class _DoctypeError(Exception):
    pass


def _reject_doctype(*_args: object) -> None:
    raise _DoctypeError


def _safe_parse(data: bytes) -> ET.Element:
    """Parse XML, refusing any DOCTYPE so entity tricks (billion laughs) cannot run."""
    # ElementTree's C parser hides its expat handlers, so a throwaway expat pass checks for a
    # DOCTYPE first. Hooking expat also covers non-UTF-8 encodings, which a byte scan would miss.
    scanner = expat.ParserCreate()
    scanner.StartDoctypeDeclHandler = _reject_doctype
    try:
        scanner.Parse(data, True)
    except expat.ExpatError as err:
        raise ET.ParseError(str(err)) from err
    return ET.fromstring(data)


def _severity(value: str) -> Severity:
    try:
        return Severity(value.lower())
    except ValueError:
        return Severity.UNKNOWN


def _info_phase(headline: str, message_phase: Phase) -> Phase:
    lowered = headline.lower()
    if lowered.startswith("cancellation of"):
        return Phase.CANCELLED
    if lowered.startswith("final"):
        return Phase.FINAL
    return message_phase


def _parse_info(el: ET.Element, message_phase: Phase) -> Info:
    codes: set[str] = set()
    descs: list[str] = []
    for area in el.findall("c:area", _NS):
        descs.append(_text(area, "areaDesc"))
        for geocode in area.findall("c:geocode", _NS):
            if _text(geocode, "valueName") == _AREA_CODE:
                codes.add(_text(geocode, "value"))
    headline = _text(el, "headline")
    return Info(
        event=_text(el, "event"),
        headline=headline,
        severity=_severity(_text(el, "severity")),
        effective=_time(_text(el, "effective")),
        expires=_time(_text(el, "expires")),
        area_desc="; ".join(d for d in descs if d),
        area_codes=frozenset(codes),
        phase=_info_phase(headline, message_phase),
    )


_MSG_PHASE = {"alert": Phase.NEW, "update": Phase.UPDATE, "cancel": Phase.CANCELLED}


def parse_cap(data: bytes) -> CapWarning | None:
    """Parse one CAP file. Return None for empty, malformed or non-CAP input."""
    if not data.strip():
        return None
    try:
        root = _safe_parse(data)
    except ET.ParseError, _DoctypeError:
        return None
    if root.tag != f"{{{_NS['c']}}}alert":
        return None
    identifier = _text(root, "identifier")
    # identifier looks like "AusBoM-IDQ21013-2026-11-01T04:14:38+00:00"
    parts = identifier.split("-")
    product_id = parts[1] if len(parts) > 2 and parts[0] == "AusBoM" else identifier
    phase = _MSG_PHASE.get(_text(root, "msgType").lower(), Phase.UNKNOWN)
    infos = tuple(_parse_info(i, phase) for i in root.findall("c:info", _NS))
    return CapWarning(
        product_id=product_id,
        identifier=identifier,
        sent=_time(_text(root, "sent")),
        phase=phase,
        infos=infos,
    )
