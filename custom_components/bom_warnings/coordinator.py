"""One shared nationwide refresh, and one coordinator per config entry that filters it."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import location
from .active_warnings import ActiveWarning, WarningState, covering, product_states
from .const import (
    CONF_AREA_CODES,
    CONF_AREA_NAMES,
    CONF_HIDE_FINAL,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_STATE,
    CONF_ZONE,
    DOMAIN,
    SPATIAL_CACHE_DIR,
)
from .fire_danger import (
    FireDangerView,
    FireMemory,
    derive,
)
from .fire_store import FireStore
from .shared_feed import SharedFeed
from .warning_types import enabled_keys, event_is_on, sensor_types
from .zone import ZoneFollower

if TYPE_CHECKING:
    from . import BomWarningsConfigEntry

_LOGGER = logging.getLogger(__name__)


def no_area_issue_id(entry: BomWarningsConfigEntry) -> str:
    return f"no_area_{entry.entry_id}"


class BomWarningsCoordinator(DataUpdateCoordinator[tuple[ActiveWarning, ...]]):
    """Derives one config entry's data from the shared nationwide refresh.

    It never polls: it re-derives whenever the shared feed updates. Only the area codes, state,
    options and layer re-resolution are specific to this entry.
    """

    config_entry: BomWarningsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: BomWarningsConfigEntry,
        feed: SharedFeed,
    ) -> None:
        super().__init__(hass, _LOGGER, config_entry=config_entry, name=DOMAIN)
        self._feed = feed
        self._unsubscribe: CALLBACK_TYPE | None = None
        # Start at the feed's generation: layer changes before this entry existed are already
        # reflected in the codes it was created with, so reloading must not re-resolve.
        self._seen_generation = feed.layer_generation
        # Every code the location resolved to, coastal-water codes included. Whether a marine
        # warning counts is the Marine wind and Hazardous surf toggles' business, so toggling them
        # never needs a re-resolve.
        self._area_codes = frozenset(config_entry.data[CONF_AREA_CODES])
        self._area_names: dict[str, str] = dict(config_entry.data.get(CONF_AREA_NAMES, {}))
        self._zone: ZoneFollower | None = None
        # Set when the location itself changed, so the next derivation re-resolves it. An entry
        # made before names were stored has none to show, so it looks them up once.
        self._reresolve = CONF_AREA_NAMES not in config_entry.data
        self._hide_final: bool = config_entry.options.get(CONF_HIDE_FINAL, True)
        # The checklist: the warning types that are on.
        self.enabled_types = enabled_keys(config_entry.options)
        self._issue_id = no_area_issue_id(config_entry)
        # Latest state of every covering product in any phase, keyed by product id.
        self.states: dict[str, WarningState] = {}
        # Covering warnings by CAP event for the per-type sensors.
        self.by_event: dict[str, tuple[ActiveWarning, ...]] = {}
        # This entry's fire district, or None when no stored code is in a fetched product.
        self.fire_danger: FireDangerView | None = None
        # Persisted, so a restart in the afternoon keeps today's rating too.
        self._fire_memory = FireMemory()
        self._fire_store = FireStore(hass, config_entry)

    async def async_load_remembered(self) -> None:
        """Restore the remembered fire danger periods; call before the first refresh."""
        if (restored := await self._fire_store.async_load()) is not None:
            self._fire_memory = restored

    async def _async_save_remembered(self) -> None:
        await self._fire_store.async_save(self._fire_memory)

    @property
    def consecutive_failures(self) -> int:
        return self._feed.consecutive_failures

    @property
    def area_names(self) -> list[str]:
        """The names of the areas the entry covers, in code order, each once."""
        return list(dict.fromkeys(self._area_names[code] for code in sorted(self._area_names)))

    def _type_on(self, event: str) -> bool:
        return event_is_on(event, self.enabled_types)

    def attach(self) -> None:
        """Follow the shared feed (this is also what keeps the feed polling), and the zone."""
        self._unsubscribe = self._feed.async_add_listener(self._on_feed_update)
        if CONF_ZONE in self.config_entry.data:
            self._zone = ZoneFollower(self.hass, self.config_entry, self._on_location_changed)
            self._zone.start()

    @callback
    def _on_location_changed(self) -> None:
        self._reresolve = True
        self._on_feed_update()

    def detach(self) -> None:
        if self._zone:
            self._zone.stop()
            self._zone = None
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    @callback
    def _on_feed_update(self) -> None:
        self.config_entry.async_create_background_task(
            self.hass, self.async_refresh(), f"{DOMAIN} derive {self.config_entry.entry_id}"
        )

    def _re_resolve(self) -> location.ResolvedLocation | None:
        """Blocking. What now covers this entry's location, or None if that cannot be told."""
        data = self.config_entry.data
        cache_dir = Path(self.hass.config.path(SPATIAL_CACHE_DIR))
        try:
            return location.resolve_location(
                self._feed.client,
                cache_dir,
                lat=data[CONF_LATITUDE],
                lon=data[CONF_LONGITUDE],
                radius_m=data.get(CONF_RADIUS, 0.0),
            )
        except location.LocationUnavailable as err:
            _LOGGER.debug("Could not re-resolve the location after a layer change: %s", err)
            return None

    def _apply_resolved(self, found: location.ResolvedLocation) -> None:
        if not found.area_codes:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="no_area",
                translation_placeholders={"title": self.config_entry.title},
            )
            return
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
        names = dict(found.area_names)
        # The names are compared too: a district can be renamed without its code changing.
        if found.area_codes == self._area_codes and names == self._area_names:
            return
        self._area_codes = found.area_codes
        self._area_names = names
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_AREA_CODES: sorted(found.area_codes),
                CONF_AREA_NAMES: names,
                CONF_STATE: found.state,
            },
        )

    async def _async_update_data(self) -> tuple[ActiveWarning, ...]:
        feed = self._feed
        if not feed.last_update_success or feed.data is None:
            raise UpdateFailed("The shared BoM refresh is failing")
        snapshot = feed.data
        if snapshot.layer_generation != self._seen_generation or self._reresolve:
            found = await self.hass.async_add_executor_job(self._re_resolve)
            # Only after success, so a failed attempt is retried on the next poll.
            if found is not None:
                self._seen_generation = snapshot.layer_generation
                self._reresolve = False
                self._apply_resolved(found)
        now = dt_util.utcnow()
        warnings = list(snapshot.warnings)
        active = covering(
            warnings,
            self._area_codes,
            now,
            area_names=self._area_names,
            hide_final=self._hide_final,
            type_on=self._type_on,
        )
        self.by_event = {
            t.event: tuple(w for w in active if w.event == t.event) for t in sensor_types()
        }
        self.states = product_states(warnings, self._area_codes, now, self._type_on)
        before = self._fire_memory
        self._fire_memory, self.fire_danger = derive(
            before, snapshot.fire_danger, self._area_codes, now, dt_util.get_default_time_zone()
        )
        if self._fire_memory != before:
            await self._async_save_remembered()
        return active
