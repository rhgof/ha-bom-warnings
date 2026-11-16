"""A local FTP server that closes the control connection, as BoM can mid-session.

Not a scripted `ftplib.FTP`: the point is that real `ftplib` raises `EOFError` on an orderly
close, which is not an `OSError` or an `ftplib.Error`.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from types import TracebackType
from typing import Literal

type DropAt = Literal["connect", "cwd", "command"]

# What a client sends to log in and enter the directory; anything else is a data command.
_SETUP_REPLIES = {b"USER": b"331 ok", b"PASS": b"230 ok", b"CWD": b"250 ok"}


class DroppingServer:
    """Accepts connections and drops each one at the chosen step.

    `connect` closes before the banner, `cwd` after login when the directory is entered, and
    `command` at the first data command (LIST, RETR or MDTM) once the client is in the directory.
    """

    def __init__(self, at: DropAt) -> None:
        self._at = at
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        # Closing a listening socket does not wake a blocked accept on Linux, so the loop polls a
        # stop flag instead, and the thread is gone when the block ends on every platform.
        self._listener.settimeout(0.05)
        self._stopping = threading.Event()
        self.accepted = 0
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def address(self) -> str:
        host, port = self._listener.getsockname()
        return f"{host}:{port}"

    def __enter__(self) -> DroppingServer:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stopping.set()
        self._thread.join(timeout=5)
        self._listener.close()

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                connection, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self.accepted += 1
            self._handle(connection)

    def _handle(self, connection: socket.socket) -> None:
        stream = connection.makefile("rwb")
        try:
            if self._at != "connect":
                stream.write(b"220 ready\r\n")
                stream.flush()
                for line in stream:
                    if not (words := line.split()):
                        continue
                    command = words[0].upper()
                    if self._at == "cwd":
                        drops = command == b"CWD"
                    else:
                        drops = command not in _SETUP_REPLIES
                    if drops:
                        break
                    stream.write(_SETUP_REPLIES.get(command, b"200 ok") + b"\r\n")
                    stream.flush()
        finally:
            # An orderly close, so the client reads end-of-file, not a timeout.
            # The client may have closed first, which must not end the server thread.
            with contextlib.suppress(OSError):
                stream.close()
                connection.shutdown(socket.SHUT_RDWR)
            connection.close()
