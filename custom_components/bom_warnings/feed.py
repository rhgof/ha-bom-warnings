"""Read the nationwide set of current warnings. No Home Assistant imports."""

from __future__ import annotations

from .cap import CapWarning, parse_cap
from .ftp import BomFtpClient, BomFtpError, FileEntry

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
        except BomFtpError:
            # The wildcard form is the fragile one; the plain listing names the same files.
            entries = self._ftp.list_files("*")
            return [e for e in entries if e.name.endswith(CAP_SUFFIX)]

    def refresh(self) -> list[CapWarning]:
        """Blocking, so run it in an executor. Raises BomFtpError if both listings fail."""
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
