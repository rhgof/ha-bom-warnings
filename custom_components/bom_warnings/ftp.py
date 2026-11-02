"""Shared anonymous-FTP access to the BoM server.

No Home Assistant imports. Every method blocks, so callers run them in an executor.
"""

from __future__ import annotations

import ftplib
from collections.abc import Iterator
from contextlib import contextmanager
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
    """Split a `host`, `host:port` or `[ipv6]:port` override; raises BomFtpError if invalid.

    A bare IPv6 literal such as `::1` is a host on the default port.
    """
    if not value:
        return DEFAULT_HOST, DEFAULT_PORT
    if value.startswith("["):
        host, bracket, rest = value[1:].partition("]")
        if not bracket or (rest and not rest.startswith(":")):
            raise BomFtpError(f"invalid host: {value}")
        port = rest[1:]
    elif value.count(":") == 1:
        host, _, port = value.partition(":")
    else:
        host, port = value, ""
    if not port:
        return host, DEFAULT_PORT
    if not port.isdecimal() or not 0 < int(port) < 65536:
        raise BomFtpError(f"invalid port in host: {value}")
    return host, int(port)


class BomFtp:
    """Anonymous, passive-mode FTP client.

    Each call opens its own connection, unless run inside `session()`, which shares one.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        directory: str = WARNINGS_DIR,
    ) -> None:
        self._host = host
        self._port = port
        self._directory = directory
        self._shared: ftplib.FTP | None = None

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

    @contextmanager
    def session(self) -> Iterator[BomFtp]:
        """Share one connection across calls, e.g. one refresh instead of N+1 logins."""
        self._shared = self._connect()
        try:
            yield self
        finally:
            if self._shared:
                self._shared.close()
            self._shared = None

    @contextmanager
    def _conn(self) -> Iterator[ftplib.FTP]:
        ftp = self._shared or self._connect()
        try:
            yield ftp
        except BaseException:
            # The control channel may be out of sync after a failure, so never reuse it.
            ftp.close()
            if ftp is self._shared:
                self._shared = None
            raise
        if ftp is not self._shared:
            ftp.close()

    def list_files(self, pattern: str) -> list[FileEntry]:
        lines: list[str] = []
        with self._conn() as ftp:
            try:
                ftp.retrlines(f"LIST {pattern}", lines.append)
            except ftplib.error_perm as err:
                # A plain `*` that matches nothing is an empty directory. Any other 550 is a
                # server rejecting the wildcard form, which the caller handles by falling back.
                if pattern != "*" or not str(err).startswith("550"):
                    raise BomFtpError(str(err)) from err
            except (OSError, ftplib.Error) as err:
                raise BomFtpError(str(err)) from err
        return [entry for line in lines if (entry := parse_listing_line(line))]

    def fetch(self, name: str) -> bytes | None:
        chunks: list[bytes] = []
        with self._conn() as ftp:
            try:
                ftp.retrbinary(f"RETR {name}", chunks.append)
            except ftplib.error_perm as err:
                if str(err).startswith("550"):
                    return None
                raise BomFtpError(str(err)) from err
            except (OSError, ftplib.Error) as err:
                raise BomFtpError(str(err)) from err
        return b"".join(chunks) or None

    def modified(self, name: str) -> datetime | None:
        with self._conn() as ftp:
            try:
                reply = ftp.voidcmd(f"MDTM {name}")
            except ftplib.error_perm as err:
                if str(err).startswith("550"):
                    return None
                raise BomFtpError(str(err)) from err
            except (OSError, ftplib.Error) as err:
                raise BomFtpError(str(err)) from err
        # Reply is "213 YYYYMMDDHHMMSS[.sss]" in UTC.
        try:
            stamp = reply.split()[1].split(".")[0]
            return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        except (IndexError, ValueError) as err:
            raise BomFtpError(f"bad MDTM reply: {reply}") from err

    def download(self, remote_path: str, local_path: str) -> None:
        with self._conn() as ftp:
            try:
                with open(local_path, "wb") as handle:
                    ftp.retrbinary(f"RETR {remote_path}", handle.write)
            except (OSError, ftplib.Error) as err:
                raise BomFtpError(str(err)) from err
