"""Read the nationwide set of current warnings. No Home Assistant imports."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from .cap import CapWarning, parse_cap
from .fire_danger import FireDangerProduct, parse_fire_danger
from .ftp import BomFtpClient, BomFtpError, BomFtpRejectedError, FileEntry

_LOGGER = logging.getLogger(__name__)

CAP_SUFFIX = ".cap.xml"
CAP_PATTERN = f"*{CAP_SUFFIX}"


def read_current_warnings(ftp: BomFtpClient) -> list[CapWarning]:
    """One-shot read of every current warning; blocking, so run it in an executor."""
    return WarningReader(ftp).refresh()


class WarningReader:
    """Keeps parsed warnings between refreshes and fetches only new or changed files.

    Change detection keys on the whole listing line, because the listing carries no year.
    """

    def __init__(self, ftp: BomFtpClient) -> None:
        self._ftp = ftp
        # File name -> (listing line it was fetched under, parsed warning).
        self._seen: dict[str, tuple[str, CapWarning]] = {}

    def _list(self) -> list[FileEntry]:
        try:
            return self._ftp.list_files(CAP_PATTERN)
        except BomFtpRejectedError:
            # Only a refusal means the server dislikes the wildcard form; the plain listing names
            # the same files. A timeout is not a refusal: the client already retried it, and a
            # second 400 KB listing would only stack up another wait.
            entries = self._ftp.list_files("*")
            return [e for e in entries if e.name.endswith(CAP_SUFFIX)]

    def refresh(self) -> list[CapWarning]:
        """Blocking, so run it in an executor. Raises BomFtpError if the listing fails."""
        current: dict[str, tuple[str, CapWarning]] = {}
        for entry in self._list():
            known = self._seen.get(entry.name)
            if known and known[0] == entry.raw:
                current[entry.name] = known
                continue
            data = self._ftp.fetch(entry.name)
            if data is not None and (warning := parse_cap(data)) is not None:
                current[entry.name] = (entry.raw, warning)
            elif known:
                # Keep the old warning under its old line, so the next refresh retries the
                # file instead of dropping a warning that may still be current.
                current[entry.name] = known
        self._seen = current
        return [warning for _, warning in current.values()]


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
