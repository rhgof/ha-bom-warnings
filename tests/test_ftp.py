"""Tests for BomFtp and parse_host against a scripted ftplib.FTP, never the network."""

import ftplib
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from custom_components.bom_warnings import ftp as ftp_module
from custom_components.bom_warnings.feed import WarningReader
from custom_components.bom_warnings.ftp import (
    ATTEMPTS,
    DEFAULT_HOST,
    BomFtp,
    BomFtpError,
    BomFtpRejectedError,
    parse_host,
)

LINE = "-rw-r--r-- 1 ftp ftp 10 Nov  2 10:14 IDQ1.cap.xml"


class ScriptedFTP:
    instances: list[ScriptedFTP] = []
    list_replies: dict[str, Any] = {}
    # Consumed one per data command (LIST, RETR, MDTM) across all connections.
    failures: list[Exception] = []
    attempts = 0

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

    def _maybe_fail(self) -> None:
        ScriptedFTP.attempts += 1
        if ScriptedFTP.failures:
            raise ScriptedFTP.failures.pop(0)

    def voidcmd(self, cmd: str) -> str:
        self._maybe_fail()
        return "213 20261101080000"

    def retrlines(self, cmd: str, callback: Callable[[str], None]) -> None:
        self._maybe_fail()
        reply = self.list_replies.get(cmd.removeprefix("LIST "), [LINE])
        if isinstance(reply, Exception):
            raise reply
        for line in reply:
            callback(line)

    def retrbinary(self, cmd: str, callback: Callable[[bytes], None]) -> None:
        self._maybe_fail()
        if "missing" in cmd:
            raise ftplib.error_perm("550 no such file")
        if "broken" in cmd:
            raise ftplib.error_temp("421 gone")
        callback(b"data")


@pytest.fixture(autouse=True)
def scripted(monkeypatch: pytest.MonkeyPatch) -> type[ScriptedFTP]:
    ScriptedFTP.instances = []
    ScriptedFTP.list_replies = {}
    ScriptedFTP.failures = []
    ScriptedFTP.attempts = 0
    monkeypatch.setattr(ftp_module, "RETRY_DELAY", 0)
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
    assert len(scripted.instances) == ATTEMPTS + 1


def operations(tmp_path: Any) -> dict[str, Callable[[BomFtp], object]]:
    return {
        "list": lambda c: c.list_files("*.cap.xml"),
        "fetch": lambda c: c.fetch("a"),
        "modified": lambda c: c.modified("a"),
        "download": lambda c: c.download("/x.zip", str(tmp_path / "x.zip")),
    }


OPERATIONS = ["list", "fetch", "modified", "download"]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("failed", [1, 2])
def test_transient_failures_are_retried(
    scripted: type[ScriptedFTP], tmp_path: Any, operation: str, failed: int
):
    scripted.failures = [TimeoutError("timed out")] * failed
    operations(tmp_path)[operation](BomFtp())
    assert scripted.attempts == failed + 1


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("error", [ftplib.error_temp("421 gone"), ConnectionResetError("reset")])
def test_gives_up_after_the_attempt_limit(
    scripted: type[ScriptedFTP], tmp_path: Any, operation: str, error: Exception
):
    scripted.failures = [error] * (ATTEMPTS + 1)
    with pytest.raises(BomFtpError) as raised:
        operations(tmp_path)[operation](BomFtp())
    assert not isinstance(raised.value, BomFtpRejectedError)
    assert scripted.attempts == ATTEMPTS
    assert len(scripted.failures) == 1


@pytest.mark.parametrize("operation", OPERATIONS)
def test_rejection_is_not_retried(scripted: type[ScriptedFTP], tmp_path: Any, operation: str):
    scripted.failures = [ftplib.error_perm("500 bad command")] * 2
    with pytest.raises(BomFtpRejectedError):
        operations(tmp_path)[operation](BomFtp())
    assert scripted.attempts == 1


def test_wildcard_550_is_a_rejection_not_retried(scripted: type[ScriptedFTP]):
    scripted.failures = [ftplib.error_perm("550 no match")]
    with pytest.raises(BomFtpRejectedError):
        BomFtp().list_files("*.cap.xml")
    assert scripted.attempts == 1


@pytest.mark.parametrize("operation", ["fetch", "modified"])
def test_missing_file_is_neither_retried_nor_an_error(
    scripted: type[ScriptedFTP], tmp_path: Any, operation: str
):
    scripted.failures = [ftplib.error_perm("550 no such file")]
    assert operations(tmp_path)[operation](BomFtp()) is None
    assert scripted.attempts == 1


def test_plain_listing_550_is_empty_not_retried(scripted: type[ScriptedFTP]):
    scripted.failures = [ftplib.error_perm("550 empty")]
    assert BomFtp().list_files("*") == []
    assert scripted.attempts == 1


def test_session_reconnects_after_a_drop_and_keeps_sharing(scripted: type[ScriptedFTP]):
    scripted.failures = [TimeoutError("stalled")]
    client = BomFtp()
    with client.session():
        client.list_files("*")  # fails once, retried on a fresh connection
        client.fetch("a")
        client.modified("a")
        assert not scripted.instances[-1].closed
    assert len(scripted.instances) == 2
    assert scripted.instances[0].closed
    assert scripted.instances[1].logins == 1
    assert all(i.closed for i in scripted.instances)


def test_connection_is_not_reused_after_the_session(scripted: type[ScriptedFTP]):
    client = BomFtp()
    with client.session():
        client.fetch("a")
    client.fetch("a")
    assert len(scripted.instances) == 2


def run_in_threads(*jobs: Callable[[], None]) -> None:
    threads = [threading.Thread(target=job) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def test_sessions_on_different_threads_use_their_own_connections(scripted: type[ScriptedFTP]):
    client = BomFtp()
    # Both sessions are open before either reads, and neither closes before both have read.
    barrier = threading.Barrier(2)

    def job() -> None:
        with client.session():
            barrier.wait()
            client.list_files("*")
            client.fetch("a")
            barrier.wait()

    run_in_threads(job, job)
    assert len(scripted.instances) == 2
    assert [i.logins for i in scripted.instances] == [1, 1]
    assert all(i.closed for i in scripted.instances)


def test_call_outside_a_session_does_not_borrow_another_threads_connection(
    scripted: type[ScriptedFTP],
):
    client = BomFtp()
    with client.session():
        run_in_threads(lambda: client.fetch("a"))
        assert len(scripted.instances) == 2
        assert scripted.instances[1].closed
        assert not scripted.instances[0].closed
        client.fetch("a")
    assert len(scripted.instances) == 2


def test_a_reused_thread_does_not_see_the_previous_session(scripted: type[ScriptedFTP]):
    client = BomFtp()

    def in_session() -> None:
        with client.session():
            client.fetch("a")

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(in_session).result()
        pool.submit(client.fetch, "a").result()
    assert len(scripted.instances) == 2
    assert all(i.closed for i in scripted.instances)
