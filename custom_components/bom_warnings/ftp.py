"""Shared anonymous-FTP access to the BoM server.

No Home Assistant imports. Every method blocks, so callers run them in an executor.
"""

from __future__ import annotations

import ftplib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

DEFAULT_HOST = "ftp.bom.gov.au"
DEFAULT_PORT = 21
WARNINGS_DIR = "/anon/gen/fwo/"
TIMEOUT = 30.0


class BomFtpError(Exception):
    """Any connection, timeout or protocol failure talking to the BoM FTP server."""


@dataclass(frozen=True, slots=True)
class FileEntry:
    name: str
    size: int
    # The whole listing line: it carries the modified time, so a change in it flags a new version.
    raw: str


class BomFtpClient(Protocol):
    def list_files(self, pattern: str) -> list[FileEntry]: ...
    def fetch(self, name: str) -> bytes | None: ...
    def modified(self, name: str) -> datetime | None: ...
    def download(self, remote_path: str, local_path: str) -> None: ...


def parse_listing_line(line: str) -> FileEntry | None:
    """Parse one Unix-style LIST line; return None for anything that is not a plain file."""
    parts = line.split(None, 8)
    if len(parts) < 9 or not parts[0].startswith("-") or not parts[4].isdigit():
        return None
    return FileEntry(name=parts[8], size=int(parts[4]), raw=line)


def parse_host(value: str | None) -> tuple[str, int]:
    """Split a `host` or `host:port` override, defaulting to the BoM server."""
    if not value:
        return DEFAULT_HOST, DEFAULT_PORT
    host, _, port = value.partition(":")
    return host, int(port) if port else DEFAULT_PORT


class BomFtp:
    """Anonymous, passive-mode FTP client. One short-lived connection per call."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        directory: str = WARNINGS_DIR,
    ) -> None:
        self._host = host
        self._port = port
        self._directory = directory

    def _connect(self) -> ftplib.FTP:
        ftp = ftplib.FTP(timeout=TIMEOUT)  # noqa: S321
        try:
            ftp.connect(self._host, self._port)
            ftp.login()
            ftp.set_pasv(True)
            ftp.cwd(self._directory)
        except (OSError, ftplib.Error) as err:
            ftp.close()
            raise BomFtpError(str(err)) from err
        return ftp

    def list_files(self, pattern: str) -> list[FileEntry]:
        ftp = self._connect()
        lines: list[str] = []
        try:
            ftp.retrlines(f"LIST {pattern}", lines.append)
        except ftplib.error_perm as err:
            # Some servers answer 550 when a wildcard matches nothing.
            if not str(err).startswith("550"):
                raise BomFtpError(str(err)) from err
        except (OSError, ftplib.Error) as err:
            raise BomFtpError(str(err)) from err
        finally:
            ftp.close()
        return [entry for line in lines if (entry := parse_listing_line(line))]

    def fetch(self, name: str) -> bytes | None:
        ftp = self._connect()
        chunks: list[bytes] = []
        try:
            ftp.retrbinary(f"RETR {name}", chunks.append)
        except ftplib.error_perm as err:
            if str(err).startswith("550"):
                return None
            raise BomFtpError(str(err)) from err
        except (OSError, ftplib.Error) as err:
            raise BomFtpError(str(err)) from err
        finally:
            ftp.close()
        return b"".join(chunks) or None

    def modified(self, name: str) -> datetime | None:
        ftp = self._connect()
        try:
            reply = ftp.voidcmd(f"MDTM {name}")
        except ftplib.error_perm as err:
            if str(err).startswith("550"):
                return None
            raise BomFtpError(str(err)) from err
        except (OSError, ftplib.Error) as err:
            raise BomFtpError(str(err)) from err
        finally:
            ftp.close()
        # Reply is "213 YYYYMMDDHHMMSS[.sss]" in UTC.
        try:
            stamp = reply.split()[1].split(".")[0]
            return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        except (IndexError, ValueError) as err:
            raise BomFtpError(f"bad MDTM reply: {reply}") from err

    def download(self, remote_path: str, local_path: str) -> None:
        ftp = self._connect()
        try:
            with open(local_path, "wb") as handle:
                ftp.retrbinary(f"RETR {remote_path}", handle.write)
        except (OSError, ftplib.Error) as err:
            raise BomFtpError(str(err)) from err
        finally:
            ftp.close()
