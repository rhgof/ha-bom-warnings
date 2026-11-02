"""BoM Warnings: Bureau of Meteorology warnings as Home Assistant entities and events."""

from __future__ import annotations

import os
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .coordinator import (
    FIRE_STORE_VERSION,
    BomWarningsCoordinator,
    async_abandon_setup,
    async_acquire_feed,
    async_release_feed,
    async_release_removed_entry,
    fire_store_key,
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
    except BomFtpError as err:
        raise ConfigEntryError(f"Invalid BOM_WARNINGS_FTP_HOST: {err}") from err

    try:
        # The feed's own client may be in use on another thread, so this entry gets its own.
        ftp = client_from_env(os.environ)
        coordinator = BomWarningsCoordinator(hass, entry, feed, ftp)
        await coordinator.async_load_remembered()
        await coordinator.async_config_entry_first_refresh()
    except BomFtpError as err:
        await async_abandon_setup(hass, entry)
        raise ConfigEntryError(f"Invalid BOM_WARNINGS_FTP_HOST: {err}") from err
    except BaseException:
        # Whatever went wrong, the entry must not stay registered on the shared feed.
        await async_abandon_setup(hass, entry)
        raise
    coordinator.attach()
    entry.runtime_data = BomWarningsData(coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> None:
    """Drop the entry's repair issue and remembered ratings, which would otherwise outlive it."""
    ir.async_delete_issue(hass, DOMAIN, no_area_issue_id(entry))
    await Store(hass, FIRE_STORE_VERSION, fire_store_key(entry)).async_remove()
    await async_release_removed_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> bool:
    """Unload a config entry; the shared refresh stops with the last one."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    entry.runtime_data.coordinator.detach()
    await async_release_feed(hass, entry)
    return True
