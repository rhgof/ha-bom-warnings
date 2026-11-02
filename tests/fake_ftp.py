"""In-memory stand-in for the shared FTP interface, for tests that must not touch the network."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from custom_components.bom_warnings.ftp import BomFtpError, FileEntry


class FakeFtp:
    def __init__(
        self,
        files: dict[str, bytes],
        *,
        vanished: set[str] | None = None,
        error: BomFtpError | None = None,
        mtimes: dict[str, datetime] | None = None,
    ) -> None:
        self.files = files
        # Listed but gone by fetch time, like a warning that expired mid-poll.
        self.vanished = vanished or set()
        self.error = error
        self.mtimes = mtimes or {}
        # Raise only from MDTM, so a refresh check can fail while downloads still work.
        self.modified_error: BomFtpError | None = None
        self.downloads: list[tuple[str, str]] = []
        self.fetches: list[str] = []
        # Raise only for the wildcard listing, like a server that rejects `LIST *.cap.xml`.
        self.wildcard_error: BomFtpError | None = None
        # Bumped on every change so the listing line differs, as a new mtime would.
        self._versions: dict[str, int] = {}

    def put(self, name: str, data: bytes) -> None:
        self.files[name] = data
        self._versions[name] = self._versions.get(name, 0) + 1

    def remove(self, name: str) -> None:
        del self.files[name]

    def _line(self, name: str, data: bytes) -> str:
        minute = self._versions.get(name, 0)
        return f"-rw-r--r-- 1 ftp ftp {len(data)} Nov  2 10:{minute:02d} {name}"

    def list_files(self, pattern: str) -> list[FileEntry]:
        if self.error:
            raise self.error
        if self.wildcard_error and pattern != "*":
            raise self.wildcard_error
        suffix = pattern.removeprefix("*")
        return [
            FileEntry(name, len(data), self._line(name, data))
            for name, data in sorted(self.files.items())
            if name.endswith(suffix)
        ]

    def fetch(self, name: str) -> bytes | None:
        if self.error:
            raise self.error
        self.fetches.append(name)
        if name in self.vanished:
            return None
        return self.files.get(name) or None

    def modified(self, name: str) -> datetime | None:
        if self.modified_error:
            raise self.modified_error
        return self.mtimes.get(name)

    def download(self, remote_path: str, local_path: str) -> None:
        if self.error:
            raise self.error
        self.downloads.append((remote_path, local_path))
        Path(local_path).write_bytes(self.files.get(remote_path, b""))
