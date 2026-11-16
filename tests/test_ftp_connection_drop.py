"""A server closing the control connection, against the real client over a real socket."""

from collections.abc import Callable
from pathlib import Path

import pytest

from custom_components.bom_warnings import ftp as ftp_module
from custom_components.bom_warnings.ftp import (
    ATTEMPTS,
    HOST_ENV_VAR,
    BomFtp,
    BomFtpError,
    BomFtpRejectedError,
    client_from_env,
)

from .drop_server import DropAt, DroppingServer


def _session(client: BomFtp, _: Path) -> None:
    with client.session():
        pass


OPERATIONS: dict[str, Callable[[BomFtp, Path], object]] = {
    "list_files": lambda client, _: client.list_files("*.cap.xml"),
    "fetch": lambda client, _: client.fetch("IDQ1.cap.xml"),
    "modified": lambda client, _: client.modified("IDQ1.cap.xml"),
    "download": lambda client, tmp: client.download("IDQ1.zip", str(tmp / "IDQ1.zip")),
    "session": _session,
}

# A session only connects, so it never reaches a data command.
CASES: list[tuple[DropAt, str]] = [
    (at, operation)
    for at in ("connect", "cwd", "command")
    for operation in OPERATIONS
    if not (at == "command" and operation == "session")
]


@pytest.mark.parametrize(("at", "operation"), CASES)
def test_a_dropped_connection_is_a_connection_failure_and_is_retried(
    socket_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    at: DropAt,
    operation: str,
) -> None:
    monkeypatch.setattr(ftp_module, "RETRY_DELAY", 0)
    with DroppingServer(at) as server:
        client = client_from_env({HOST_ENV_VAR: server.address})
        with pytest.raises(BomFtpError) as raised:
            OPERATIONS[operation](client, tmp_path)
    assert not isinstance(raised.value, BomFtpRejectedError)
    # A bare EOFError has no text, and the repair issue and logs show this.
    assert str(raised.value)
    # A session opens its connection once; every other call reconnects for each attempt.
    assert server.accepted == (1 if operation == "session" else ATTEMPTS)
