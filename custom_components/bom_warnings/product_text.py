"""The broadcast text (`<id>.txt`) of a warning product.

It holds three facts the CAP file does not: whether a thunderstorm warning is the Detailed kind
(which names a storm cell and where it is heading), the hazard line, and when the next warning is
due. The text is 2 to 3 KB; the product XML beside it is up to 250 KB of embedded images.

Times in the text are local to the warning and carry no zone, so they are returned as naive
datetimes. The caller knows the CAP sent time and works out the offset from it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from .cap import CapWarning, Info
from .ftp import BomFtpError
from .sibling_files import PerIssueReader, Read
from .warning_types import THUNDERSTORM_EVENT

_LOGGER = logging.getLogger(__name__)

_PRODUCT_ID = re.compile(r"ID[A-Z0-9]+")
_ISSUED = re.compile(r"^Issued at (\d{1,2}:\d{2} [ap]m) \w+, (\d{1,2} \w+ \d{4})\.", re.MULTILINE)
_NEXT = re.compile(r"next warning is due to be issued by (\d{1,2}:\d{2} [ap]m)")
_SENDER = "Australian Government Bureau of Meteorology"
_CANCELLATION = "Cancellation of "
_DETAILED = "Detailed "


@dataclass(frozen=True, slots=True)
class ProductText:
    product_id: str
    detailed: bool
    cancelled: bool
    # The "for ..." line in sentence case, such as "Damaging winds and large hailstones". Empty for
    # a cancellation, which has none.
    hazard: str
    issued: datetime | None
    next_issue: datetime | None


def _title(lines: list[str]) -> tuple[str, str] | None:
    """The title line and the hazard line under it, or None when the text has no title."""
    try:
        start = lines.index(_SENDER) + 1
    except ValueError:
        return None
    body = [line.strip() for line in lines[start:]]
    # The priority line ("TOP PRIORITY FOR IMMEDIATE BROADCAST") sits between sender and title.
    titles = iter(line for line in body if line and "PRIORITY" not in line)
    title = next(titles, None)
    if title is None:
        return None
    after = body[body.index(title) + 1 :]
    hazard = after[0] if after and after[0].startswith("for ") else ""
    return title, hazard


def _sentence(line: str) -> str:
    phrase = line.removeprefix("for ").strip().lower()
    return phrase[:1].upper() + phrase[1:]


def _strptime(value: str, fmt: str) -> datetime | None:
    # The template is fixed, but a change to it, or a month spelled another way, must leave the
    # date out and not raise: the reader runs inside the refresh and may never fail it.
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def _when(clock: str, day: datetime) -> datetime | None:
    parsed = _strptime(clock, "%I:%M %p")
    return day.replace(hour=parsed.hour, minute=parsed.minute) if parsed else None


def parse_text(data: bytes) -> ProductText | None:
    lines = data.decode("utf-8", errors="replace").splitlines()
    if not lines or not _PRODUCT_ID.fullmatch(lines[0].strip()):
        return None
    if (found := _title(lines)) is None:
        return None
    title, hazard_line = found
    cancelled = title.startswith(_CANCELLATION)
    detailed = title.removeprefix(_CANCELLATION).startswith(_DETAILED)

    issued = next_issue = None
    if match := _ISSUED.search("\n".join(lines)):
        issued = _strptime(f"{match[1]} {match[2]}", "%I:%M %p %d %B %Y")
    if issued and (match := _NEXT.search("\n".join(lines))):
        next_issue = _when(match[1], issued)
        if next_issue and next_issue < issued:
            # Past midnight: "issued by 12:30 am" after an evening issue.
            next_issue += timedelta(days=1)

    return ProductText(
        product_id=lines[0].strip(),
        detailed=detailed,
        cancelled=cancelled,
        hazard=_sentence(hazard_line) if hazard_line else "",
        issued=issued,
        next_issue=next_issue,
    )


def _utc_offset(local: datetime, sent: datetime) -> timedelta:
    """The zone's offset from UTC, from a local clock time and the UTC time it was sent at.

    The text gives the time to the minute and the CAP file to the second, so the difference is
    rounded to the nearest quarter hour, which is the finest offset any Australian zone has.
    """
    difference = local - sent.astimezone(UTC).replace(tzinfo=None)
    quarters = round(difference.total_seconds() / 900)
    return timedelta(minutes=15 * quarters)


def _wants_text(info: Info, now: datetime) -> bool:
    return info.event == THUNDERSTORM_EVENT and info.is_active(now)


def _with_text(info: Info, text: ProductText, sent: datetime | None) -> Info:
    next_issue = None
    if text.next_issue and text.issued and sent:
        next_issue = (text.next_issue - _utc_offset(text.issued, sent)).replace(tzinfo=UTC)
    return replace(info, detailed=text.detailed, hazard=text.hazard, next_issue=next_issue)


class ProductTextReader(PerIssueReader[ProductText | None]):
    """Adds the broadcast text's facts to the current thunderstorm blocks of each warning.

    It reads a product's text only when a current thunderstorm block needs it, and then once per
    CAP issue (see `PerIssueReader`). The file is fetched by name without listing it first, because
    it is 2 to 3 KB.
    """

    def _wants(self, info: Info, now: datetime) -> bool:
        return _wants_text(info, now)

    def _read(self, warning: CapWarning) -> Read[ProductText | None] | None:
        name = f"{warning.product_id}.txt"
        try:
            data = self._ftp.fetch(name)
        except BomFtpError as err:
            _LOGGER.debug("Could not read product text %s: %s", name, err)
            return None
        # An absent or unreadable file is remembered as such until BoM re-issues the product, so it
        # costs one request and not one every refresh. The text lands with the CAP file; if it were
        # ever late, a Detailed warning would lack its facts for one 30 minute cycle.
        if (text := parse_text(data or b"")) is None:
            _LOGGER.debug("Product text %s is absent, empty or unreadable", name)
        return Read(text)

    def _apply(self, warning: CapWarning, value: ProductText | None, now: datetime) -> CapWarning:
        if value is None:
            return warning
        infos = tuple(
            _with_text(info, value, warning.sent) if _wants_text(info, now) else info
            for info in warning.infos
        )
        return replace(warning, infos=infos)
