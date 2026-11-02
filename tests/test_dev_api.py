"""Tests for the dev-instance REST helper against a local stub server, never a real HA."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from scripts.ha_api import HaApiError, get_state, read_token

SEEN: list[str | None] = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        SEEN.append(self.headers.get("Authorization"))
        if self.path == "/api/states/sensor.demo":
            body = json.dumps({"entity_id": "sensor.demo", "state": "42"}).encode()
            self.send_response(200)
        else:
            body = b'{"message": "Entity not found."}'
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


# The stub server is loopback-only, so the plugin's socket block must be lifted.
@pytest.fixture
def base_url(socket_enabled: None) -> Iterator[str]:
    SEEN.clear()
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_get_state_sends_bearer_token(base_url: str) -> None:
    state = get_state("sensor.demo", token="abc", base_url=base_url)
    assert state["state"] == "42"
    assert SEEN == ["Bearer abc"]


def test_get_state_missing_entity_raises(base_url: str) -> None:
    with pytest.raises(HaApiError, match="404"):
        get_state("sensor.nope", token="abc", base_url=base_url)


def test_read_token_strips_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "token"
    path.write_text("abc\n")
    assert read_token(path) == "abc"


def test_read_token_missing_file_explains_next_step(tmp_path: Path) -> None:
    with pytest.raises(HaApiError, match="long-lived"):
        read_token(tmp_path / "absent")
