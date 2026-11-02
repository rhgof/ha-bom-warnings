"""BoM Warnings: Bureau of Meteorology warnings as Home Assistant entities and events."""

from __future__ import annotations

import os
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .coordinator import BomWarningsCoordinator, refresh_issue_id
from .ftp import BomFtpError, client_from_env

PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR]


@dataclass(slots=True)
class BomWarningsData:
    """Runtime data of one entry. Ticket #21 moves the shared refresh out of this."""

    coordinator: BomWarningsCoordinator


type BomWarningsConfigEntry = ConfigEntry[BomWarningsData]


async def async_setup_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> bool:
    """Set up one location: one FTP client and one coordinator for this entry."""
    try:
        # The only place the client is built, so the dev-only host override applies once.
        ftp = client_from_env(os.environ)
    except BomFtpError as err:
        raise ConfigEntryError(f"Invalid BOM_WARNINGS_FTP_HOST: {err}") from err

    coordinator = BomWarningsCoordinator(hass, entry, ftp)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = BomWarningsData(coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> None:
    """Drop the repair issue, which would otherwise outlive the entry that raised it."""
    ir.async_delete_issue(hass, DOMAIN, refresh_issue_id(entry))


async def async_unload_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
