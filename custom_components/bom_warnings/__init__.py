"""BoM Warnings: Bureau of Meteorology warnings as Home Assistant entities and events."""

from __future__ import annotations

import os
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .coordinator import (
    BomWarningsCoordinator,
    async_acquire_feed,
    async_release_feed,
    no_area_issue_id,
)
from .ftp import BomFtpError, client_from_env

PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR]


@dataclass(slots=True)
class BomWarningsData:
    """Runtime data of one entry. The FTP refresh is shared and lives in `SharedFeed`."""

    coordinator: BomWarningsCoordinator


type BomWarningsConfigEntry = ConfigEntry[BomWarningsData]


async def async_setup_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> bool:
    """Set up one location on top of the refresh shared by every entry."""
    try:
        feed = await async_acquire_feed(hass, entry)
        # The feed's own client may be in use on another thread, so this entry gets its own.
        ftp = client_from_env(os.environ)
    except BomFtpError as err:
        raise ConfigEntryError(f"Invalid BOM_WARNINGS_FTP_HOST: {err}") from err

    coordinator = BomWarningsCoordinator(hass, entry, feed, ftp)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await async_release_feed(hass, entry)
        raise
    coordinator.attach()
    entry.runtime_data = BomWarningsData(coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> None:
    """Drop the entry's repair issue, which would otherwise outlive it."""
    ir.async_delete_issue(hass, DOMAIN, no_area_issue_id(entry))


async def async_unload_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> bool:
    """Unload a config entry; the shared refresh stops with the last one."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    entry.runtime_data.coordinator.detach()
    await async_release_feed(hass, entry)
    return True
