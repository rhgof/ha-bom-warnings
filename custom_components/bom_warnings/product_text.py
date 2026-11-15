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
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from .cap import CapWarning, Info
from .ftp import BomFtpClient, BomFtpError
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


def _when(clock: str, day: datetime) -> datetime:
    parsed = datetime.strptime(clock, "%I:%M %p")
    return day.replace(hour=parsed.hour, minute=parsed.minute)


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
        issued = datetime.strptime(f"{match[1]} {match[2]}", "%I:%M %p %d %B %Y")
    if issued and (match := _NEXT.search("\n".join(lines))):
        next_issue = _when(match[1], issued)
        if next_issue < issued:
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


class ProductTextReader:
    """Adds the broadcast text's facts to the current thunderstorm blocks of each warning.

    It reads a product's text only when a current thunderstorm block needs it, and then once per
    CAP issue: the issue's identifier changes whenever BoM re-issues, so an unchanged product costs
    no request. The file is fetched by name without listing it first, because it is 2 to 3 KB.
    """

    def __init__(self, ftp: BomFtpClient) -> None:
        self._ftp = ftp
        # Product id -> (identifier of the CAP issue it was read for, what the text said; None when
        # the file was absent or empty).
        self._seen: dict[str, tuple[str, ProductText | None]] = {}

    def _read(self, warning: CapWarning) -> None:
        name = f"{warning.product_id}.txt"
        try:
            data = self._ftp.fetch(name)
        except BomFtpError as err:
            _LOGGER.debug("Could not read product text %s: %s", name, err)
            return
        # An absent or unreadable file is remembered as such until BoM re-issues the product, so it
        # costs one request and not one every refresh. The text lands with the CAP file; if it were
        # ever late, a Detailed warning would lack its facts for one 30 minute cycle.
        if (text := parse_text(data or b"")) is None:
            _LOGGER.debug("Product text %s is absent, empty or unreadable", name)
        self._seen[warning.product_id] = (warning.identifier, text)

    def _apply(self, warning: CapWarning, now: datetime) -> CapWarning:
        seen = self._seen.get(warning.product_id)
        if seen is None or seen[0] != warning.identifier or seen[1] is None:
            return warning
        infos = tuple(
            _with_text(info, seen[1], warning.sent) if _wants_text(info, now) else info
            for info in warning.infos
        )
        return replace(warning, infos=infos)

    def enrich(self, warnings: Sequence[CapWarning], now: datetime) -> list[CapWarning]:
        """Blocking, so run it in an executor. Returns the warnings with the text's facts added."""
        wanted = {
            w.product_id: w for w in warnings if any(_wants_text(info, now) for info in w.infos)
        }
        self._seen = {
            pid: seen
            for pid, seen in self._seen.items()
            if pid in wanted and seen[0] == wanted[pid].identifier
        }
        for product_id, warning in wanted.items():
            if product_id not in self._seen:
                self._read(warning)
        return [self._apply(w, now) for w in warnings]
