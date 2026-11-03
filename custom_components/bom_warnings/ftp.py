"""Shared anonymous-FTP access to the BoM server.

No Home Assistant imports. Every method blocks, so callers run them in an executor.
"""

from __future__ import annotations

import ftplib
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar

DEFAULT_HOST = "ftp.bom.gov.au"
DEFAULT_PORT = 21
WARNINGS_DIR = "/anon/gen/fwo/"
# Short on purpose: the server's data transfer sometimes stalls and then works a second later, so
# a quick retry beats one long wait.
TIMEOUT = 10.0
# Tries per call, and the pause between them. A module constant so tests can set it to 0.
ATTEMPTS = 3
RETRY_DELAY = 1.0


class BomFtpError(Exception):
    """Any connection, timeout or protocol failure talking to the BoM FTP server."""


class BomFtpRejectedError(BomFtpError):
    """The server answered with a permanent (5xx) refusal, so asking again will not help."""


_T = TypeVar("_T")


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

    def session(self) -> AbstractContextManager[object]:
        """Share one connection across the calls made inside the `with` block."""
        ...


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


HOST_ENV_VAR = "BOM_WARNINGS_FTP_HOST"


def client_from_env(environ: Mapping[str, str], directory: str = WARNINGS_DIR) -> BomFtp:
    """Build the client, honouring the dev-only `BOM_WARNINGS_FTP_HOST` override.

    Call this once at setup, not per refresh, and never expose the override in the UI.
    """
    host, port = parse_host(environ.get(HOST_ENV_VAR))
    return BomFtp(host, port, directory)


class _SessionState(threading.local):
    """The open session of the calling thread; each thread starts with none."""

    shared: ftplib.FTP | None = None
    in_session = False


class BomFtp:
    """Anonymous, passive-mode FTP client, safe to share between threads.

    Each call opens its own connection, unless run inside `session()`, which shares one with the
    other calls on the same thread. Transient failures are retried up to `ATTEMPTS` times; a
    rejection (5xx) never is.
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
        # An ftplib connection must never be used by two threads, and the feed's refresh, its layer
        # check and every entry's resolver run on different executor threads at once.
        self._state = _SessionState()

    def _connect(self) -> ftplib.FTP:
        ftp = ftplib.FTP(timeout=TIMEOUT)  # noqa: S321
        try:
            ftp.connect(self._host, self._port)
            ftp.login()
            ftp.set_pasv(True)
            ftp.cwd(self._directory)
        except ftplib.error_perm as err:
            ftp.close()
            raise BomFtpRejectedError(str(err)) from err
        except (OSError, ftplib.Error) as err:
            ftp.close()
            raise BomFtpError(str(err)) from err
        return ftp

    @contextmanager
    def session(self) -> Iterator[BomFtp]:
        """Share one connection across calls, e.g. one refresh instead of N+1 logins.

        If the connection drops, the next call (or retry) opens a new shared one. The session
        belongs to the calling thread: calls from any other thread open their own connections.
        """
        state = self._state
        state.shared = self._connect()
        state.in_session = True
        try:
            yield self
        finally:
            state.in_session = False
            if state.shared:
                state.shared.close()
            state.shared = None

    @contextmanager
    def _conn(self) -> Iterator[ftplib.FTP]:
        state = self._state
        if state.in_session and state.shared is None:
            state.shared = self._connect()
        ftp = state.shared or self._connect()
        try:
            yield ftp
        except BaseException:
            # The control channel may be out of sync after a failure, so never reuse it.
            ftp.close()
            if ftp is state.shared:
                state.shared = None
            raise
        if ftp is not state.shared:
            ftp.close()

    @staticmethod
    def _retrying(operation: Callable[[], _T]) -> _T:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                return operation()
            except BomFtpRejectedError:
                raise
            except BomFtpError:
                if attempt == ATTEMPTS:
                    raise
                time.sleep(RETRY_DELAY)
        raise AssertionError("unreachable")  # pragma: no cover

    def list_files(self, pattern: str) -> list[FileEntry]:
        return self._retrying(lambda: self._list_files(pattern))

    def fetch(self, name: str) -> bytes | None:
        return self._retrying(lambda: self._fetch(name))

    def modified(self, name: str) -> datetime | None:
        return self._retrying(lambda: self._modified(name))

    def download(self, remote_path: str, local_path: str) -> None:
        self._retrying(lambda: self._download(remote_path, local_path))

    def _list_files(self, pattern: str) -> list[FileEntry]:
        lines: list[str] = []
        with self._conn() as ftp:
            try:
                ftp.retrlines(f"LIST {pattern}", lines.append)
            except ftplib.error_perm as err:
                # A plain `*` that matches nothing is an empty directory. Any other refusal is
                # a server rejecting the wildcard form, which the caller handles by falling back.
                if pattern != "*" or not str(err).startswith("550"):
                    raise BomFtpRejectedError(str(err)) from err
            except (OSError, ftplib.Error) as err:
                raise BomFtpError(str(err)) from err
        return [entry for line in lines if (entry := parse_listing_line(line))]

    def _fetch(self, name: str) -> bytes | None:
        chunks: list[bytes] = []
        with self._conn() as ftp:
            try:
                ftp.retrbinary(f"RETR {name}", chunks.append)
            except ftplib.error_perm as err:
                if str(err).startswith("550"):
                    return None
                raise BomFtpRejectedError(str(err)) from err
            except (OSError, ftplib.Error) as err:
                raise BomFtpError(str(err)) from err
        return b"".join(chunks) or None

    def _modified(self, name: str) -> datetime | None:
        with self._conn() as ftp:
            try:
                reply = ftp.voidcmd(f"MDTM {name}")
            except ftplib.error_perm as err:
                if str(err).startswith("550"):
                    return None
                raise BomFtpRejectedError(str(err)) from err
            except (OSError, ftplib.Error) as err:
                raise BomFtpError(str(err)) from err
        # Reply is "213 YYYYMMDDHHMMSS[.sss]" in UTC.
        try:
            stamp = reply.split()[1].split(".")[0]
            return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        except (IndexError, ValueError) as err:
            raise BomFtpError(f"bad MDTM reply: {reply}") from err

    def _download(self, remote_path: str, local_path: str) -> None:
        with self._conn() as ftp:
            try:
                with open(local_path, "wb") as handle:
                    ftp.retrbinary(f"RETR {remote_path}", handle.write)
            except ftplib.error_perm as err:
                raise BomFtpRejectedError(str(err)) from err
            except (OSError, ftplib.Error) as err:
                raise BomFtpError(str(err)) from err
