"""BoM Warnings: Bureau of Meteorology warnings as Home Assistant entities and events."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

type BomWarningsConfigEntry = ConfigEntry[None]


async def async_setup_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> bool:
    """Set up a config entry. Placeholder until the coordinator ticket lands."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> bool:
    """Unload a config entry."""
    return True
