"""The cycle every sibling-file reader shares.

BoM puts more than one file beside a warning's CAP file (the product XML, the broadcast text). A
reader fetches one of them for the blocks that need it, and does so once per CAP issue: the issue's
identifier changes whenever BoM re-issues, so an unchanged product costs no request. A subclass
says which blocks want its file, how to read it, and how to apply what it said.

No Home Assistant imports, and a reader never raises: these steps are optional, so whatever goes
wrong leaves the warning as the CAP file described it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from .cap import CapWarning, Info
from .ftp import BomFtpClient


@dataclass(frozen=True, slots=True)
class Read[T]:
    """What one read found, to be remembered until BoM re-issues the product.

    A reader that finds the file absent or empty returns a `Read` that says so, so the absence is
    not asked about again. A read that failed returns None instead, and is tried at the next
    refresh.
    """

    value: T


class PerIssueReader[T](ABC):
    """Reads a sibling file once per CAP issue and applies it to the warning's blocks."""

    def __init__(self, ftp: BomFtpClient) -> None:
        self._ftp = ftp
        # Product id -> (identifier of the CAP issue it was read for, what the read found).
        self._seen: dict[str, tuple[str, T]] = {}

    @abstractmethod
    def _wants(self, info: Info, now: datetime) -> bool:
        """Whether this block needs the file."""

    @abstractmethod
    def _read(self, warning: CapWarning) -> Read[T] | None:
        """Fetch and parse the file, or None to try again at the next refresh."""

    @abstractmethod
    def _apply(self, warning: CapWarning, value: T, now: datetime) -> CapWarning:
        """The warning with what the file said added to its blocks."""

    def enrich(self, warnings: Sequence[CapWarning], now: datetime) -> list[CapWarning]:
        """Blocking, so run it in an executor. Returns the warnings with the file's facts added."""
        wanted = {
            w.product_id: w for w in warnings if any(self._wants(info, now) for info in w.infos)
        }
        self._seen = {
            pid: seen
            for pid, seen in self._seen.items()
            if pid in wanted and seen[0] == wanted[pid].identifier
        }
        for product_id, warning in wanted.items():
            if product_id not in self._seen and (found := self._read(warning)) is not None:
                self._seen[product_id] = (warning.identifier, found.value)
        return [self._with_seen(w, now) for w in warnings]

    def _with_seen(self, warning: CapWarning, now: datetime) -> CapWarning:
        seen = self._seen.get(warning.product_id)
        if seen is None or seen[0] != warning.identifier:
            return warning
        return self._apply(warning, seen[1], now)
