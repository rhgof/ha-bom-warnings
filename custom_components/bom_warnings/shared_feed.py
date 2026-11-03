"""The one nationwide BoM refresh shared by every config entry, and the rules for creating,
joining, leaving and shutting it down."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .cap import CapWarning
from .const import (
    CONF_AREA_CODES,
    DOMAIN,
    SPATIAL_CACHE_DIR,
)
from .feed import WarningReader
from .fire_danger import (
    FireDangerProduct,
    FireDangerReader,
    fire_product_ids,
)
from .ftp import BomFtp, BomFtpError, client_from_env
from .layer_check import LayerSchedule, read_record, write_record
from .spatial import (
    LAYERS,
    RefreshResult,
    SpatialDataError,
    refresh_layers,
)

if TYPE_CHECKING:
    from . import BomWarningsConfigEntry

_LOGGER = logging.getLogger(__name__)

# Not user-configurable, so users cannot hammer BoM's server.
UPDATE_INTERVAL = timedelta(minutes=10)
# A single failed poll is routine; three in a row (30 minutes) is worth telling the user about.
FAILURES_BEFORE_REPAIR = 3
# One issue for the whole integration: the refresh is shared, so its failure is too.
REFRESH_ISSUE_ID = "refresh_failing"


@dataclass(frozen=True, slots=True)
class FeedSnapshot:
    """The nationwide result of one refresh, before any entry filters it."""

    warnings: tuple[CapWarning, ...]
    # Bumped whenever a shapefile layer changed, so each entry re-resolves its own location once.
    layer_generation: int
    # Product id -> latest parse, for the products some entry needs. Empty when none could be read.
    fire_danger: Mapping[str, FireDangerProduct] = field(default_factory=dict)


class SharedFeed(DataUpdateCoordinator[FeedSnapshot]):
    """The one FTP refresh of the whole integration, shared by every config entry.

    It polls only while an entry is listening, so it starts with the first loaded entry and stops
    when the last one detaches. The failure count lives here, so there is one repair issue.
    """

    def __init__(self, hass: HomeAssistant, ftp: BomFtp, layer_ftp: BomFtp) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=f"{DOMAIN} feed",
            update_interval=UPDATE_INTERVAL,
        )
        self._ftp = ftp
        # The layer check runs in an executor beside warnings refreshes, and a BomFtp session is
        # not thread-safe, so it gets its own client.
        self._layer_ftp = layer_ftp
        self._reader = WarningReader(ftp)
        self._fire_reader = FireDangerReader(ftp)
        self.consecutive_failures = 0
        # Due right after the first successful refresh, unless a recent record says otherwise.
        self._layer_schedule = LayerSchedule.loaded(None, dt_util.utcnow())
        self._layer_task: asyncio.Task[None] | None = None
        self.layer_generation = 0
        # Entries using this feed, so the last one to leave can shut it down.
        self.entry_ids: set[str] = set()
        self.lock = asyncio.Lock()

    def _cache_dir(self) -> Path:
        return Path(self.hass.config.path(SPATIAL_CACHE_DIR))

    async def async_load_layer_record(self) -> None:
        """Schedule the first layer check from the persisted record; call before the first poll."""
        last = await self.hass.async_add_executor_job(read_record, self._cache_dir())
        self._layer_schedule = LayerSchedule.loaded(last, dt_util.utcnow())

    def _refresh(
        self, fire_products: set[str]
    ) -> tuple[list[CapWarning], dict[str, FireDangerProduct]]:
        """Blocking. The warnings read decides success; the fire danger step runs after it."""
        # One connection per refresh instead of one login per file.
        with self._ftp.session():
            warnings = self._reader.refresh()
            # Never raises: a failure here keeps the previous fire danger data.
            return warnings, self._fire_reader.refresh(fire_products)

    def _wanted_fire_products(self) -> set[str]:
        return fire_product_ids(
            code
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            for code in entry.data.get(CONF_AREA_CODES, ())
        )

    def _check_layers(self) -> tuple[bool, bool]:
        """Blocking. Returns (a layer changed, the server was reached)."""
        with self._layer_ftp.session():
            result: RefreshResult = refresh_layers(self._layer_ftp, self._cache_dir())
        for layer, error in result.failed.items():
            # The cached copy stays in use, and the next check retries.
            _LOGGER.debug("Could not refresh shapefile layer %s: %s", layer, error)
        reached = len(result.failed) < len(LAYERS)
        if reached:
            write_record(self._cache_dir(), dt_util.utcnow())
        return bool(result.changed), reached

    async def _async_check_layers(self) -> None:
        try:
            changed, reached = await self.hass.async_add_executor_job(self._check_layers)
        except (BomFtpError, SpatialDataError, OSError) as err:
            _LOGGER.debug("Layer check failed: %s", err)
            changed = reached = False
        if not reached:
            self._layer_schedule = self._layer_schedule.unreached(dt_util.utcnow())
        if changed and self.data is not None:
            self.layer_generation += 1
            self.async_set_updated_data(
                FeedSnapshot(self.data.warnings, self.layer_generation, self.data.fire_danger)
            )

    def _schedule_layer_check(self, now: datetime) -> None:
        if not self._layer_schedule.due(now) or (self._layer_task and not self._layer_task.done()):
            return
        self._layer_schedule = self._layer_schedule.started(now)
        self._layer_task = self.hass.async_create_background_task(
            self._async_check_layers(), f"{DOMAIN} layer check"
        )

    async def async_shutdown(self) -> None:
        if self._layer_task:
            self._layer_task.cancel()
        await super().async_shutdown()

    async def _async_update_data(self) -> FeedSnapshot:
        try:
            warnings, fire_danger = await self.hass.async_add_executor_job(
                self._refresh, self._wanted_fire_products()
            )
        except BomFtpError as err:
            self.consecutive_failures += 1
            if self.consecutive_failures >= FAILURES_BEFORE_REPAIR:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    REFRESH_ISSUE_ID,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="refresh_failing",
                )
            raise UpdateFailed(f"Cannot read BoM warnings: {err}") from err
        self.consecutive_failures = 0
        ir.async_delete_issue(self.hass, DOMAIN, REFRESH_ISSUE_ID)
        self._schedule_layer_check(dt_util.utcnow())
        return FeedSnapshot(tuple(warnings), self.layer_generation, fire_danger)


FEED: HassKey[SharedFeed] = HassKey(DOMAIN)


async def async_acquire_feed(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> SharedFeed:
    """Join the shared feed, creating it and doing its first refresh if this is the first entry."""
    feed = hass.data.get(FEED)
    if feed is None:
        # The only place the feed's clients are built, so the dev-only host override applies once.
        feed = hass.data[FEED] = SharedFeed(
            hass, client_from_env(os.environ), client_from_env(os.environ)
        )
        await feed.async_load_layer_record()
    feed.entry_ids.add(entry.entry_id)
    async with feed.lock:
        if feed.data is None or not feed.last_update_success:
            await feed.async_refresh()
    if not feed.last_update_success:
        # The feed stays, so its failure count survives Home Assistant's setup retries and the
        # repair issue can appear when BoM is down at startup.
        feed.entry_ids.discard(entry.entry_id)
        raise ConfigEntryNotReady("Cannot read BoM warnings")
    return feed


async def async_abandon_setup(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> None:
    """Unregister an entry whose setup failed, keeping the feed and its failure count.

    Nothing listens to the feed, so it does not poll. It is torn down when the last entry is
    unloaded or removed.
    """
    if (feed := hass.data.get(FEED)) is not None:
        feed.entry_ids.discard(entry.entry_id)


async def async_release_feed(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> None:
    """Leave the shared feed; the last entry out shuts it down and clears its repair issue."""
    feed = hass.data.get(FEED)
    if feed is None:
        return
    feed.entry_ids.discard(entry.entry_id)
    if feed.entry_ids:
        return
    await _async_shutdown_feed(hass, feed)


async def async_release_removed_entry(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> None:
    """Tear the feed down if the last entry is removed without ever having been unloaded.

    An entry stuck in setup retry is never unloaded, yet it keeps the failing feed (and its
    repair issue) alive.
    """
    feed = hass.data.get(FEED)
    if feed is None:
        return
    feed.entry_ids.discard(entry.entry_id)
    others = [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id]
    if not feed.entry_ids and not others:
        await _async_shutdown_feed(hass, feed)


async def _async_shutdown_feed(hass: HomeAssistant, feed: SharedFeed) -> None:
    del hass.data[FEED]
    await feed.async_shutdown()
    ir.async_delete_issue(hass, DOMAIN, REFRESH_ISSUE_ID)
