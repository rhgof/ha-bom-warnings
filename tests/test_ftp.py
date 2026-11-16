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
    client_from_env,
    parse_host,
)

LINE = "-rw-r--r-- 1 ftp ftp 10 Nov  2 10:14 IDQ1.cap.xml"


class Script:
    """What the fake `ftplib.FTP` does in one test, and what it saw."""

    def __init__(self) -> None:
        self.instances: list[ScriptedFTP] = []
        self.list_replies: dict[str, Any] = {}
        # Consumed one per data command (LIST, RETR, MDTM) across all connections.
        self.failures: list[Exception] = []
        self.attempts = 0
        self.mdtm_reply = "213 20261101080000"
        self.connected: list[tuple[str, int]] = []
        # Connections on different threads share one script.
        self._lock = threading.Lock()

    def record_connect(self, host: str, port: int) -> None:
        with self._lock:
            self.connected.append((host, port))

    def next_failure(self) -> Exception | None:
        with self._lock:
            self.attempts += 1
            return self.failures.pop(0) if self.failures else None

    def connection(self) -> ScriptedFTP:
        with self._lock:
            connection = ScriptedFTP(self)
            self.instances.append(connection)
            return connection


class ScriptedFTP:
    def __init__(self, script: Script) -> None:
        self.script = script
        self.closed = False
        self.logins = 0

    def connect(self, host: str, port: int) -> None:
        self.script.record_connect(host, port)

    def login(self) -> None:
        self.logins += 1

    def set_pasv(self, flag: bool) -> None:
        pass

    def cwd(self, path: str) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def _maybe_fail(self) -> None:
        if (failure := self.script.next_failure()) is not None:
            raise failure

    def voidcmd(self, cmd: str) -> str:
        self._maybe_fail()
        return self.script.mdtm_reply

    def retrlines(self, cmd: str, callback: Callable[[str], None]) -> None:
        self._maybe_fail()
        reply = self.script.list_replies.get(cmd.removeprefix("LIST "), [LINE])
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


class ScriptedFtplib:
    """The `ftplib` module as the client sees it, with `FTP` swapped for the script's fake.

    Everything else falls through to the real module, so a new `ftplib` name in the client does
    not need adding here.
    """

    def __init__(self, script: Script) -> None:
        self._script = script

    def FTP(self, timeout: float | None = None) -> ScriptedFTP:  # noqa: N802
        return self._script.connection()

    def __getattr__(self, name: str) -> Any:
        return getattr(ftplib, name)


@pytest.fixture(autouse=True)
def scripted(monkeypatch: pytest.MonkeyPatch) -> Script:
    script = Script()
    monkeypatch.setattr(ftp_module, "RETRY_DELAY", 0)
    # The client's own name for the module, not the stdlib's attribute, so nothing else in the
    # process (another test, another thread) ever sees the fake.
    monkeypatch.setattr(ftp_module, "ftplib", ScriptedFtplib(script))
    return script


def test_wildcard_550_raises_and_reader_falls_back(scripted: Script):
    scripted.list_replies = {"*.cap.xml": ftplib.error_perm("550 no match")}
    with pytest.raises(BomFtpError):
        BomFtp().list_files("*.cap.xml")
    reader = WarningReader(BomFtp())
    assert reader.refresh() == []  # listed via the fallback; the fetched b"data" is not CAP
    assert any(i.closed for i in scripted.instances)


def test_full_listing_550_is_empty(scripted: Script):
    scripted.list_replies = {"*": ftplib.error_perm("550 empty")}
    assert BomFtp().list_files("*") == []


def test_both_listings_failing_propagates(scripted: Script):
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


def test_each_call_uses_its_own_connection_by_default(scripted: Script):
    client = BomFtp()
    client.list_files("*")
    client.fetch("a")
    assert len(scripted.instances) == 2
    assert all(i.closed for i in scripted.instances)


def test_session_reuses_one_connection(scripted: Script):
    client = BomFtp()
    with client.session():
        client.list_files("*")
        assert client.fetch("missing") is None
        client.fetch("a")
        assert not scripted.instances[0].closed
    assert len(scripted.instances) == 1
    assert scripted.instances[0].logins == 1
    assert scripted.instances[0].closed


def test_session_drops_connection_after_error(scripted: Script):
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
    scripted: Script, tmp_path: Any, operation: str, failed: int
):
    scripted.failures = [TimeoutError("timed out")] * failed
    operations(tmp_path)[operation](BomFtp())
    assert scripted.attempts == failed + 1


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    "error", [ftplib.error_temp("421 gone"), ConnectionResetError("reset"), EOFError()]
)
def test_gives_up_after_the_attempt_limit(
    scripted: Script, tmp_path: Any, operation: str, error: Exception
):
    scripted.failures = [error] * (ATTEMPTS + 1)
    with pytest.raises(BomFtpError) as raised:
        operations(tmp_path)[operation](BomFtp())
    assert not isinstance(raised.value, BomFtpRejectedError)
    assert scripted.attempts == ATTEMPTS
    assert len(scripted.failures) == 1


@pytest.mark.parametrize("operation", OPERATIONS)
def test_rejection_is_not_retried(scripted: Script, tmp_path: Any, operation: str):
    scripted.failures = [ftplib.error_perm("500 bad command")] * 2
    with pytest.raises(BomFtpRejectedError):
        operations(tmp_path)[operation](BomFtp())
    assert scripted.attempts == 1


@pytest.mark.parametrize("reply", ["", "213", "213 not-a-date", "500 what"])
def test_a_bad_mdtm_reply_is_a_connection_failure_after_the_retries(scripted: Script, reply: str):
    scripted.mdtm_reply = reply
    with pytest.raises(BomFtpError, match="bad MDTM reply"):
        BomFtp().modified("a")
    assert scripted.attempts == ATTEMPTS


def test_the_client_from_env_connects_to_bom_by_default(scripted: Script):
    client_from_env({}).list_files("*")
    assert scripted.connected == [(DEFAULT_HOST, 21)]


def test_wildcard_550_is_a_rejection_not_retried(scripted: Script):
    scripted.failures = [ftplib.error_perm("550 no match")]
    with pytest.raises(BomFtpRejectedError):
        BomFtp().list_files("*.cap.xml")
    assert scripted.attempts == 1


@pytest.mark.parametrize("operation", ["fetch", "modified"])
def test_missing_file_is_neither_retried_nor_an_error(
    scripted: Script, tmp_path: Any, operation: str
):
    scripted.failures = [ftplib.error_perm("550 no such file")]
    assert operations(tmp_path)[operation](BomFtp()) is None
    assert scripted.attempts == 1


def test_plain_listing_550_is_empty_not_retried(scripted: Script):
    scripted.failures = [ftplib.error_perm("550 empty")]
    assert BomFtp().list_files("*") == []
    assert scripted.attempts == 1


def test_session_reconnects_after_a_drop_and_keeps_sharing(scripted: Script):
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


def test_connection_is_not_reused_after_the_session(scripted: Script):
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


def test_sessions_on_different_threads_use_their_own_connections(scripted: Script):
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
    scripted: Script,
):
    client = BomFtp()
    with client.session():
        run_in_threads(lambda: client.fetch("a"))
        assert len(scripted.instances) == 2
        assert scripted.instances[1].closed
        assert not scripted.instances[0].closed
        client.fetch("a")
    assert len(scripted.instances) == 2


def test_a_reused_thread_does_not_see_the_previous_session(scripted: Script):
    client = BomFtp()

    def in_session() -> None:
        with client.session():
            client.fetch("a")

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(in_session).result()
        pool.submit(client.fetch, "a").result()
    assert len(scripted.instances) == 2
    assert all(i.closed for i in scripted.instances)
