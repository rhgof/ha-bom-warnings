"""A local anonymous FTP server for a directory laid out like BoM's."""

from __future__ import annotations

import fnmatch
import glob
import os
import threading
from pathlib import Path
from types import TracebackType

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.handlers.ftp.producers import BufferedIteratorProducer
from pyftpdlib.servers import FTPServer


class BomHandler(FTPHandler):
    """Like BoM's server, accept a wildcard in LIST (`LIST *.cap.xml`), which pyftpdlib refuses."""

    # Every command received, for tests that count how often the integration talks to the server.
    commands: list[tuple[str, str]]

    def pre_process_command(self, line: str, cmd: str, arg: str | None) -> None:
        self.commands.append((cmd, arg or ""))
        super().pre_process_command(line, cmd, arg)

    def ftp_LIST(self, path: str) -> str | None:
        basedir, pattern = os.path.split(path)
        if not glob.has_magic(pattern):
            return super().ftp_LIST(path)
        try:
            names = sorted(fnmatch.filter(self.fs.listdir(basedir), pattern))
        except OSError as err:
            self.respond(f"550 {err.strerror}.")
            return None
        producer = BufferedIteratorProducer(self.fs.format_list(basedir, names))
        self.push_dtp_data(producer, isproducer=True, cmd="LIST")
        return path


class FakeBom:
    """Serve `root` read-only on 127.0.0.1 from a background thread. Port 0 picks a free one."""

    def __init__(self, root: Path, port: int = 0) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        authorizer = DummyAuthorizer()
        authorizer.add_anonymous(str(root), perm="elr")
        self.commands: list[tuple[str, str]] = []
        handler = type(
            "Handler", (BomHandler,), {"authorizer": authorizer, "commands": self.commands}
        )
        self._server = FTPServer(("127.0.0.1", port), handler)
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    @property
    def address(self) -> str:
        host, port = self._server.address[:2]
        return f"{host}:{port}"

    def _run(self) -> None:
        # One short non-blocking pass at a time, so stop() can end the loop before sockets close.
        while not self._stopping.is_set():
            self._server.serve_forever(timeout=0.05, blocking=False, handle_exit=False)
        self._server.close_all()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._thread.join(timeout=5)

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def __enter__(self) -> FakeBom:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
