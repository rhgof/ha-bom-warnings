"""One entry's remembered fire danger ratings, in Home Assistant's storage.

The key, version and shape are what earlier releases wrote, so ratings stored before a restart
still load. Nothing outside this module needs to know any of them.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .fire_danger import FireMemory

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1


class FireStore:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{DOMAIN}.fire_danger.{entry.entry_id}"
        )

    async def async_load(self) -> FireMemory | None:
        """What was saved, or None when nothing usable is stored."""
        stored = await self._store.async_load()
        if not stored:
            return None
        if (memory := FireMemory.from_dict(stored)) is None:
            # A damaged file is replaced by the next save; the next issue refills it.
            _LOGGER.debug("Ignoring unreadable remembered fire danger data")
        return memory

    async def async_save(self, memory: FireMemory) -> None:
        await self._store.async_save(memory.to_dict())

    async def async_remove(self) -> None:
        await self._store.async_remove()
