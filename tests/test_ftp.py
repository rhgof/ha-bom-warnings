"""Tests for BomFtp and parse_host against a scripted ftplib.FTP, never the network."""

import ftplib
from collections.abc import Callable
from typing import Any

import pytest

from custom_components.bom_warnings import ftp as ftp_module
from custom_components.bom_warnings.feed import WarningReader
from custom_components.bom_warnings.ftp import DEFAULT_HOST, BomFtp, BomFtpError, parse_host

LINE = "-rw-r--r-- 1 ftp ftp 10 Nov  2 10:14 IDQ1.cap.xml"


class ScriptedFTP:
    instances: list[ScriptedFTP] = []
    list_replies: dict[str, Any] = {}

    def __init__(self, timeout: float | None = None) -> None:
        self.closed = False
        self.logins = 0
        ScriptedFTP.instances.append(self)

    def connect(self, host: str, port: int) -> None:
        pass

    def login(self) -> None:
        self.logins += 1

    def set_pasv(self, flag: bool) -> None:
        pass

    def cwd(self, path: str) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def retrlines(self, cmd: str, callback: Callable[[str], None]) -> None:
        reply = self.list_replies.get(cmd.removeprefix("LIST "), [LINE])
        if isinstance(reply, Exception):
            raise reply
        for line in reply:
            callback(line)

    def retrbinary(self, cmd: str, callback: Callable[[bytes], None]) -> None:
        if "missing" in cmd:
            raise ftplib.error_perm("550 no such file")
        if "broken" in cmd:
            raise ftplib.error_temp("421 gone")
        callback(b"data")


@pytest.fixture(autouse=True)
def scripted(monkeypatch: pytest.MonkeyPatch) -> type[ScriptedFTP]:
    ScriptedFTP.instances = []
    ScriptedFTP.list_replies = {}
    monkeypatch.setattr(ftp_module.ftplib, "FTP", ScriptedFTP)
    return ScriptedFTP


def test_wildcard_550_raises_and_reader_falls_back(scripted: type[ScriptedFTP]):
    scripted.list_replies = {"*.cap.xml": ftplib.error_perm("550 no match")}
    with pytest.raises(BomFtpError):
        BomFtp().list_files("*.cap.xml")
    reader = WarningReader(BomFtp())
    assert reader.refresh() == []  # listed via the fallback; the fetched b"data" is not CAP
    assert any(i.closed for i in scripted.instances)


def test_full_listing_550_is_empty(scripted: type[ScriptedFTP]):
    scripted.list_replies = {"*": ftplib.error_perm("550 empty")}
    assert BomFtp().list_files("*") == []


def test_both_listings_failing_propagates(scripted: type[ScriptedFTP]):
    scripted.list_replies = {
        "*.cap.xml": ftplib.error_perm("550 no"),
        "*": ftplib.error_temp("421 down"),
    }
    with pytest.raises(BomFtpError):
        WarningReader(BomFtp()).refresh()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, (DEFAULT_HOST, 21)),
        ("", (DEFAULT_HOST, 21)),
        ("localhost", ("localhost", 21)),
        ("localhost:2121", ("localhost", 2121)),
        ("[::1]:2121", ("::1", 2121)),
        ("[::1]", ("::1", 21)),
        ("::1", ("::1", 21)),
    ],
)
def test_parse_host(value: str | None, expected: tuple[str, int]):
    assert parse_host(value) == expected


@pytest.mark.parametrize("value", ["host:abc", "[::1]:abc", "host:99999", "[::1"])
def test_parse_host_rejects_bad_values(value: str):
    with pytest.raises(BomFtpError):
        parse_host(value)


def test_each_call_uses_its_own_connection_by_default(scripted: type[ScriptedFTP]):
    client = BomFtp()
    client.list_files("*")
    client.fetch("a")
    assert len(scripted.instances) == 2
    assert all(i.closed for i in scripted.instances)


def test_session_reuses_one_connection(scripted: type[ScriptedFTP]):
    client = BomFtp()
    with client.session():
        client.list_files("*")
        assert client.fetch("missing") is None
        client.fetch("a")
        assert not scripted.instances[0].closed
    assert len(scripted.instances) == 1
    assert scripted.instances[0].logins == 1
    assert scripted.instances[0].closed


def test_session_drops_connection_after_error(scripted: type[ScriptedFTP]):
    client = BomFtp()
    with client.session():
        with pytest.raises(BomFtpError):
            client.fetch("broken")
        assert scripted.instances[0].closed
        assert client.fetch("a") == b"data"
    assert len(scripted.instances) == 2
