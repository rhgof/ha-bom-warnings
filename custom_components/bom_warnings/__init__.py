"""BoM Warnings: Bureau of Meteorology warnings as Home Assistant entities and events."""

from __future__ import annotations

import os
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import (
    CONF_EVENT_TYPES,
    CONF_INCLUDE_MARINE,
    CONF_WARNING_TYPES,
    DOMAIN,
    WARNING_TYPE_SENSORS,
)
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
from .warning_types import keys_from_legacy_options
from .zone import delete_zone_issues

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
    """Drop the entry's repair issues and remembered ratings, which would otherwise outlive it."""
    ir.async_delete_issue(hass, DOMAIN, no_area_issue_id(entry))
    delete_zone_issues(hass, entry)
    await Store(hass, FIRE_STORE_VERSION, fire_store_key(entry)).async_remove()
    await async_release_removed_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> bool:
    """Unload a config entry; the shared refresh stops with the last one."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    entry.runtime_data.coordinator.detach()
    await async_release_feed(hass, entry)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> bool:
    """Version 1 had an event-type filter and a coastal-waters switch; version 2 has a checklist."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        on = keys_from_legacy_options(entry.options)
        options = {
            key: value
            for key, value in entry.options.items()
            if key not in (CONF_EVENT_TYPES, CONF_INCLUDE_MARINE)
        }
        options[CONF_WARNING_TYPES] = on
        _enable_old_default_disabled_sensors(hass, entry, set(on))
        hass.config_entries.async_update_entry(entry, options=options, version=2)
    return True


def _enable_old_default_disabled_sensors(
    hass: HomeAssistant, entry: BomWarningsConfigEntry, on: set[str]
) -> None:
    """Per-type sensors used to be disabled by default; one the user never touched must not stay so.

    A sensor the user disabled themselves is left alone. Sensors of types that are off are removed
    when the entry loads.
    """
    registry = er.async_get(hass)
    unique_id = entry.unique_id or entry.entry_id
    for _, key in WARNING_TYPE_SENSORS:
        entity_id = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{unique_id}_{key}")
        if not entity_id or key not in on:
            continue
        registered = registry.async_get(entity_id)
        if registered and registered.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
            registry.async_update_entity(entity_id, disabled_by=None)
