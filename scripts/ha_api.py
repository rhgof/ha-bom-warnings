"""Call the throwaway dev Home Assistant's REST API with the stored long-lived token.

Usage: python -m scripts.ha_api sensor.some_entity
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
# Inside the gitignored config/ folder so the token can never be committed.
TOKEN_FILE = ROOT / "config" / ".ha-token"
# Not 8123, so it cannot be mistaken for another instance on the same machine.
BASE_URL = "http://127.0.0.1:8124"


class HaApiError(Exception):
    """Raised for a missing token or a failed request."""


def read_token(path: Path = TOKEN_FILE) -> str:
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        raise HaApiError(
            f"No token at {path}. Create a long-lived access token in the HA profile page "
            "and save it to that file (see README, 'Dev instance')."
        ) from None


def get_state(
    entity_id: str, *, token: str | None = None, base_url: str = BASE_URL
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}/api/states/{entity_id}",
        headers={"Authorization": f"Bearer {token or read_token()}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result: dict[str, Any] = json.load(response)
    except urllib.error.HTTPError as err:
        raise HaApiError(f"HTTP {err.code} for {entity_id}") from err
    except urllib.error.URLError as err:
        raise HaApiError(f"Cannot reach {base_url}: {err.reason}. Is it running?") from err
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(get_state(sys.argv[1]), indent=2))
    except (HaApiError, IndexError) as err:
        sys.exit(str(err) or "usage: python -m scripts.ha_api <entity_id>")
