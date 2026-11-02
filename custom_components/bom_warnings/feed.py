"""Read the nationwide set of current warnings. No Home Assistant imports."""

from __future__ import annotations

from .cap import CapWarning, parse_cap
from .ftp import BomFtpClient

CAP_PATTERN = "*.cap.xml"


def read_current_warnings(ftp: BomFtpClient) -> list[CapWarning]:
    """List, fetch and parse every CAP file; blocking, so run it in an executor.

    Empty, vanished and unparseable files are skipped: warning files exist only while the
    hazard is current, so they come and go between the listing and the fetch.
    """
    warnings: list[CapWarning] = []
    for entry in ftp.list_files(CAP_PATTERN):
        data = ftp.fetch(entry.name)
        if data is None:
            continue
        if (warning := parse_cap(data)) is not None:
            warnings.append(warning)
    return warnings
