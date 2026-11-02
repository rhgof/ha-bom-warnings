"""One shared nationwide refresh, and one coordinator per config entry that filters it."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .areas import state_of
from .cap import CapWarning, Info, Phase, Severity
from .const import (
    CONF_AREA_CODES,
    CONF_HIDE_FINAL,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_STATE,
    CONF_ZONE,
    DOMAIN,
    SPATIAL_CACHE_DIR,
    WARNING_TYPE_SENSORS,
)
from .feed import FireDangerReader, WarningReader
from .fire_danger import (
    FireDangerPeriod,
    FireDangerProduct,
    fire_product_ids,
    match_district,
)
from .ftp import BomFtp, BomFtpError, client_from_env
from .spatial import (
    LAYERS,
    RefreshResult,
    SpatialDataError,
    refresh_layers,
    resolve_coordinate,
)
from .strength import wind_strength
from .warning_types import enabled_keys, event_is_on
from .zone import ZoneFollower

if TYPE_CHECKING:
    from . import BomWarningsConfigEntry

_LOGGER = logging.getLogger(__name__)

# Not user-configurable, so users cannot hammer BoM's server.
UPDATE_INTERVAL = timedelta(minutes=10)
# A single failed poll is routine; three in a row (30 minutes) is worth telling the user about.
FAILURES_BEFORE_REPAIR = 3
# One issue for the whole integration: the refresh is shared, so its failure is too.
REFRESH_ISSUE_ID = "refresh_failing"
FIRE_STORE_VERSION = 1


def fire_store_key(entry: ConfigEntry) -> str:
    return f"{DOMAIN}.fire_danger.{entry.entry_id}"


def no_area_issue_id(entry: BomWarningsConfigEntry) -> str:
    return f"no_area_{entry.entry_id}"


# Shapefile layers change rarely, so they are checked weekly, in the background.
LAYER_CHECK_INTERVAL = timedelta(days=7)
# When the last check reached the server, so a restart does not start a fresh one.
LAYER_CHECK_RECORD = ".last_layer_check"


@dataclass(frozen=True, slots=True)
class ActiveWarning:
    """One current `<info>` block that covers the entry's location."""

    product_id: str
    event: str
    headline: str
    severity: Severity
    effective: datetime | None
    expires: datetime | None
    sent: datetime | None = None
    # Last, with a default, so existing constructors keep working.
    phase: Phase = Phase.UNKNOWN

    @property
    def is_current(self) -> bool:
        """False for a cancelled or final warning, which `hide_final=False` lists for reference."""
        return self.phase not in _ENDED

    @property
    def strength(self) -> str | None:
        """The class of a marine wind warning (strong, gale, storm), read from its headline."""
        return wind_strength(self.event, self.headline)


_ENDED = (Phase.CANCELLED, Phase.FINAL)


def warning_attributes(warning: ActiveWarning) -> dict[str, Any]:
    """One warning as the list attributes of the binary sensors and the type sensors show it."""
    attributes: dict[str, Any] = {
        "product_id": warning.product_id,
        "event": warning.event,
        "headline": warning.headline,
        "severity": str(warning.severity),
        "phase": str(warning.phase),
        "effective": warning.effective.isoformat() if warning.effective else None,
        "expires": warning.expires.isoformat() if warning.expires else None,
    }
    # Only marine wind has one, so no other event gains the field.
    if (strength := warning.strength) is not None:
        attributes["strength"] = strength
    return attributes


def _shown(info: Info, now: datetime, hide_final: bool) -> bool:
    if info.is_active(now):
        return True
    ended = info.phase in _ENDED
    return ended and not hide_final and (info.expires is None or info.expires > now)


def _active(
    warnings: list[CapWarning],
    now: datetime,
    matches: Callable[[Info], bool],
    *,
    hide_final: bool = True,
    type_on: Callable[[str], bool] = lambda event: True,
) -> tuple[ActiveWarning, ...]:
    # Match per info block: one file can mix areas, so a warning-level match could report an
    # inactive block that happens to share the file with a matching one.
    return tuple(
        ActiveWarning(
            product_id=warning.product_id,
            event=info.event,
            headline=info.headline,
            severity=info.severity,
            effective=info.effective,
            expires=info.expires,
            sent=warning.sent,
            phase=info.phase,
        )
        for warning in warnings
        for info in warning.infos
        if _shown(info, now, hide_final) and matches(info) and type_on(info.event)
    )


def _covering(
    warnings: list[CapWarning],
    area_codes: frozenset[str],
    now: datetime,
    **filters: Any,
) -> tuple[ActiveWarning, ...]:
    return _active(warnings, now, lambda info: bool(info.area_codes & area_codes), **filters)


@dataclass(frozen=True, slots=True)
class WarningState:
    """What the event entity compares between refreshes: one product, whatever its phase.

    `data` only holds active warnings, so a cancelled or final one vanishes from it. This keeps
    those too, so the transition can be seen.
    """

    product_id: str
    identifier: str
    phase: Phase
    event: str
    headline: str
    severity: Severity


def _states(
    warnings: list[CapWarning],
    area_codes: frozenset[str],
    now: datetime,
    type_on: Callable[[str], bool] = lambda event: True,
) -> dict[str, WarningState]:
    states: dict[str, WarningState] = {}
    for warning in warnings:
        # Finished blocks stay in; a block that merely expired without a cancel is not news.
        covering: list[Info] = [
            info
            for info in warning.infos
            if info.area_codes & area_codes
            and (info.phase in _ENDED or info.is_active(now))
            # A type that is off applies; hide_final deliberately does not, because a final
            # or cancelled transition is exactly what the event entity reports.
            and type_on(info.event)
        ]
        if not covering:
            continue
        # One file can hold several blocks (e.g. extreme and severe heatwave); the most severe
        # one stands for the product, so a product raises one event per transition.
        info = max(covering, key=lambda i: list(Severity).index(i.severity))
        states[warning.product_id] = WarningState(
            product_id=warning.product_id,
            identifier=warning.identifier,
            phase=info.phase,
            event=info.event,
            headline=info.headline,
            severity=info.severity,
        )
    return states


@dataclass(frozen=True, slots=True)
class FeedSnapshot:
    """The nationwide result of one refresh, before any entry filters it."""

    warnings: tuple[CapWarning, ...]
    # Bumped whenever a shapefile layer changed, so each entry re-resolves its own location once.
    layer_generation: int
    # Product id -> latest parse, for the products some entry needs. Empty when none could be read.
    fire_danger: Mapping[str, FireDangerProduct] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FireDangerView:
    """One entry's fire district: the latest issue, plus days remembered from earlier issues."""

    product_id: str
    issued: datetime | None
    district_code: str
    district_name: str
    # Every period of the latest issue, in date order.
    forecast: tuple[FireDangerPeriod, ...]
    by_date: Mapping[date, FireDangerPeriod]
    # The product's own local offset, which decides what "today" means for its district.
    tz: tzinfo

    def local_date(self, now: datetime) -> date:
        return now.astimezone(self.tz).date()


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
        self._next_layer_check = dt_util.utcnow()
        self._layer_task: asyncio.Task[None] | None = None
        self.layer_generation = 0
        # Entries using this feed, so the last one to leave can shut it down.
        self.entry_ids: set[str] = set()
        self.lock = asyncio.Lock()

    def _cache_dir(self) -> Path:
        return Path(self.hass.config.path(SPATIAL_CACHE_DIR))

    def _read_layer_record(self) -> datetime | None:
        """Blocking. When the last check reached the server; None if missing or unreadable."""
        try:
            last = datetime.fromisoformat((self._cache_dir() / LAYER_CHECK_RECORD).read_text())
        except OSError, ValueError:
            return None
        return last if last.tzinfo else None

    def _write_layer_record(self) -> None:
        """Blocking. Failing to write only means the next start checks again."""
        directory = self._cache_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / LAYER_CHECK_RECORD).write_text(dt_util.utcnow().isoformat())
        except OSError as err:
            _LOGGER.debug("Could not record the layer check time: %s", err)

    async def async_load_layer_record(self) -> None:
        """Schedule the first layer check from the persisted record; call before the first poll."""
        last = await self.hass.async_add_executor_job(self._read_layer_record)
        now = dt_util.utcnow()
        # A record from the future (clock change) would postpone the check for too long.
        if last is not None and last <= now:
            self._next_layer_check = last + LAYER_CHECK_INTERVAL

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
            self._write_layer_record()
        return bool(result.changed), reached

    async def _async_check_layers(self) -> None:
        try:
            changed, reached = await self.hass.async_add_executor_job(self._check_layers)
        except (BomFtpError, SpatialDataError, OSError) as err:
            _LOGGER.debug("Layer check failed: %s", err)
            changed = reached = False
        if not reached:
            # Never got through: due again on the next successful poll rather than in a week.
            self._next_layer_check = dt_util.utcnow()
        if changed and self.data is not None:
            self.layer_generation += 1
            self.async_set_updated_data(
                FeedSnapshot(self.data.warnings, self.layer_generation, self.data.fire_danger)
            )

    def _schedule_layer_check(self, now: datetime) -> None:
        if now < self._next_layer_check or (self._layer_task and not self._layer_task.done()):
            return
        # Set now, not when it finishes, so a slow check is not scheduled a second time.
        self._next_layer_check = now + LAYER_CHECK_INTERVAL
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
        ftp: BomFtp,
    ) -> None:
        super().__init__(hass, _LOGGER, config_entry=config_entry, name=DOMAIN)
        self._feed = feed
        # This entry's own client: a BomFtp session is not safe to share between threads.
        self._ftp = ftp
        self._unsubscribe: CALLBACK_TYPE | None = None
        # Start at the feed's generation: layer changes before this entry existed are already
        # reflected in the codes it was created with, so reloading must not re-resolve.
        self._seen_generation = feed.layer_generation
        # Every code the location resolved to, coastal-water codes included. Whether a marine
        # warning counts is the Marine wind and Hazardous surf toggles' business, so toggling them
        # never needs a re-resolve.
        self._area_codes = frozenset(config_entry.data[CONF_AREA_CODES])
        self._zone: ZoneFollower | None = None
        # Set when the location itself changed, so the next derivation re-resolves it.
        self._reresolve = False
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
        # Periods seen in earlier issues, so the afternoon issue (which starts tomorrow) does not
        # erase today's rating. Persisted, so a restart in the afternoon keeps it too. A period is
        # only ever shown on its own local date, so it expires at the end of that day.
        self._remembered: tuple[str, dict[date, FireDangerPeriod]] = ("", {})
        self._fire_store: Store[dict[str, Any]] = Store(
            hass, FIRE_STORE_VERSION, fire_store_key(config_entry)
        )

    async def async_load_remembered(self) -> None:
        """Restore the remembered fire danger periods; call before the first refresh."""
        stored = await self._fire_store.async_load()
        if not stored:
            return
        try:
            periods = {
                (d := date.fromisoformat(item["date"])): FireDangerPeriod(
                    d, item["level"], item["fire_behaviour_index"]
                )
                for item in stored["periods"]
            }
            self._remembered = (stored["district"], periods)
        except KeyError, TypeError, ValueError:
            # A damaged file is replaced by the next save; the next issue refills it.
            _LOGGER.debug("Ignoring unreadable remembered fire danger data")

    async def _async_save_remembered(self) -> None:
        code, periods = self._remembered
        await self._fire_store.async_save(
            {
                "district": code,
                "periods": [
                    {
                        "date": p.date.isoformat(),
                        "level": p.level,
                        "fire_behaviour_index": p.fire_behaviour_index,
                    }
                    for _, p in sorted(periods.items())
                ],
            }
        )

    @property
    def consecutive_failures(self) -> int:
        return self._feed.consecutive_failures

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

    def _re_resolve(self) -> set[str] | None:
        """Blocking. The area codes now covering this entry's location, or None if unknown."""
        data = self.config_entry.data
        cache_dir = Path(self.hass.config.path(SPATIAL_CACHE_DIR))
        try:
            with self._ftp.session():
                return resolve_coordinate(
                    self._ftp,
                    cache_dir,
                    lat=data[CONF_LATITUDE],
                    lon=data[CONF_LONGITUDE],
                    radius_m=data.get(CONF_RADIUS, 0.0),
                )
        except (BomFtpError, SpatialDataError, OSError) as err:
            _LOGGER.debug("Could not re-resolve the location after a layer change: %s", err)
            return None

    def _apply_resolved(self, codes: set[str]) -> None:
        if not codes:
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
        if codes == self._area_codes:
            return
        self._area_codes = frozenset(codes)
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_AREA_CODES: sorted(codes),
                CONF_STATE: state_of(codes),
            },
        )

    def _derive_fire_danger(self, snapshot: FeedSnapshot, now: datetime) -> FireDangerView | None:
        match = match_district(snapshot.fire_danger, self._area_codes)
        if match is None:
            return None
        product, district = match
        code, remembered = self._remembered
        if code != district.code:
            remembered = {}
        # The latest issue wins for any day both cover.
        remembered = {**remembered, **{p.date: p for p in district.periods}}
        tz = product.issued.tzinfo if product.issued and product.issued.tzinfo else None
        local_today = now.astimezone(tz or dt_util.get_default_time_zone()).date()
        remembered = {d: p for d, p in remembered.items() if d >= local_today - timedelta(days=1)}
        self._remembered = (district.code, remembered)
        return FireDangerView(
            product_id=product.product_id,
            issued=product.issued,
            district_code=district.code,
            district_name=district.name,
            forecast=district.periods,
            by_date=remembered,
            tz=tz or dt_util.get_default_time_zone(),
        )

    async def _async_update_data(self) -> tuple[ActiveWarning, ...]:
        feed = self._feed
        if not feed.last_update_success or feed.data is None:
            raise UpdateFailed("The shared BoM refresh is failing")
        snapshot = feed.data
        if snapshot.layer_generation != self._seen_generation or self._reresolve:
            new_codes = await self.hass.async_add_executor_job(self._re_resolve)
            # Only after success, so a failed attempt is retried on the next poll.
            if new_codes is not None:
                self._seen_generation = snapshot.layer_generation
                self._reresolve = False
                self._apply_resolved(new_codes)
        now = dt_util.utcnow()
        warnings = list(snapshot.warnings)
        covering = _covering(
            warnings, self._area_codes, now, hide_final=self._hide_final, type_on=self._type_on
        )
        self.by_event = {
            event: tuple(w for w in covering if w.event == event)
            for event, _ in WARNING_TYPE_SENSORS
        }
        self.states = _states(warnings, self._area_codes, now, self._type_on)
        before = self._remembered
        self.fire_danger = self._derive_fire_danger(snapshot, now)
        if self._remembered != before:
            await self._async_save_remembered()
        return covering
