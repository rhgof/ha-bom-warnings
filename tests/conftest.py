"""Shared fixtures for Home Assistant tests."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    CONF_AREA_CODES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_STATE,
    DOMAIN,
)
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

# The recorded warnings expire in early November 2026, so tests run at a fixed "now" in which the
# baseline QLD thunderstorm warnings (and the heatwave added by `warning_appears`) are current.
NOW = "2026-11-01 08:00:00+00:00"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components from this repo."""


@pytest.fixture(autouse=True)
def isolated_config_dir(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Give Home Assistant tests their own config dir.

    The default one is shared by every test and run, and the layer cache and check record live in
    it, so a check recorded by one test would silence the next.
    """
    if "hass" in request.fixturenames:
        hass = request.getfixturevalue("hass")
        hass.config.config_dir = str(tmp_path / "config")


@pytest.fixture
def fake_bom(tmp_path: Path, socket_enabled: None) -> Iterator[FakeBom]:
    """A local FTP server on the baseline scenario.

    The integration reaches it through the dev-only BOM_WARNINGS_FTP_HOST variable, exactly as
    the throwaway instance does.
    """
    with FakeBom(tmp_path / "bom") as server:
        scenarios.apply("baseline", server.root)
        with patch.dict("os.environ", {"BOM_WARNINGS_FTP_HOST": server.address}):
            yield server


@pytest.fixture
def area_codes() -> list[str]:
    """Area codes stored on the entry; parametrize this fixture to change them."""
    return ["QLD_PW001"]


@pytest.fixture
def entry_options() -> dict[str, Any]:
    """Options stored on the entry; parametrize this fixture to change them."""
    return {}


@pytest.fixture
def mock_config_entry(area_codes: list[str], entry_options: dict[str, Any]) -> MockConfigEntry:
    """A location in a QLD forecast district that no baseline warning covers."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=3,
        unique_id="-27.470,153.021",
        title="Home",
        options=entry_options,
        data={
            CONF_LATITUDE: -27.47,
            CONF_LONGITUDE: 153.021,
            CONF_STATE: "QLD",
            CONF_AREA_CODES: area_codes,
        },
    )
