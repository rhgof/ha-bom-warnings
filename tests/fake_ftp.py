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
        self.downloads: list[tuple[str, str]] = []

    def list_files(self, pattern: str) -> list[FileEntry]:
        if self.error:
            raise self.error
        suffix = pattern.removeprefix("*")
        return [
            FileEntry(name, len(data), f"-rw-r--r-- 1 ftp ftp {len(data)} Nov  2 10:00 {name}")
            for name, data in sorted(self.files.items())
            if name.endswith(suffix)
        ]

    def fetch(self, name: str) -> bytes | None:
        if self.error:
            raise self.error
        if name in self.vanished:
            return None
        return self.files.get(name) or None

    def modified(self, name: str) -> datetime | None:
        return self.mtimes.get(name)

    def download(self, remote_path: str, local_path: str) -> None:
        if self.error:
            raise self.error
        self.downloads.append((remote_path, local_path))
        Path(local_path).write_bytes(self.files.get(remote_path, b""))
