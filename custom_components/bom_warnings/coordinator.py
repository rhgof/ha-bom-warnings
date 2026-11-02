"""Polls the BoM warning feed for one config entry."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .cap import CapWarning, Info, Phase, Severity
from .config_flow import state_of
from .const import (
    CONF_AREA_CODES,
    CONF_EVENT_TYPES,
    CONF_HIDE_FINAL,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_STATE,
    DOMAIN,
    SPATIAL_CACHE_DIR,
)
from .feed import WarningReader
from .ftp import BomFtp, BomFtpError
from .spatial import RefreshResult, SpatialDataError, refresh_layers, resolve_coordinate

if TYPE_CHECKING:
    from . import BomWarningsConfigEntry

_LOGGER = logging.getLogger(__name__)

# Not user-configurable, so users cannot hammer BoM's server.
UPDATE_INTERVAL = timedelta(minutes=10)
# A single failed poll is routine; three in a row (30 minutes) is worth telling the user about.
FAILURES_BEFORE_REPAIR = 3


def refresh_issue_id(entry: BomWarningsConfigEntry) -> str:
    return f"refresh_failing_{entry.entry_id}"


# Shapefile layers change rarely, so checking their server times every poll would be wasted FTP
# commands.
LAYER_CHECK_INTERVAL = timedelta(hours=6)


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


def _shown(info: Info, now: datetime, hide_final: bool) -> bool:
    if info.is_active(now):
        return True
    ended = info.phase in (Phase.CANCELLED, Phase.FINAL)
    return ended and not hide_final and (info.expires is None or info.expires > now)


def _active(
    warnings: list[CapWarning],
    now: datetime,
    matches: Callable[[Info], bool],
    *,
    hide_final: bool = True,
    event_types: frozenset[str] = frozenset(),
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
        if _shown(info, now, hide_final)
        and matches(info)
        and (not event_types or info.event in event_types)
    )


def _covering(
    warnings: list[CapWarning],
    area_codes: frozenset[str],
    now: datetime,
    **filters: Any,
) -> tuple[ActiveWarning, ...]:
    return _active(warnings, now, lambda info: bool(info.area_codes & area_codes), **filters)


def _in_state(
    warnings: list[CapWarning],
    state: str,
    area_codes: frozenset[str],
    now: datetime,
    **filters: Any,
) -> tuple[ActiveWarning, ...]:
    # Area codes are prefixed with the state ("QLD_PW001"). Also keep warnings that cover the
    # entry, in case a location sits across a border.
    prefix = f"{state}_"
    return _active(
        warnings,
        now,
        lambda info: (
            bool(info.area_codes & area_codes)
            or any(code.startswith(prefix) for code in info.area_codes)
        ),
        **filters,
    )


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
    warnings: list[CapWarning], area_codes: frozenset[str], now: datetime
) -> dict[str, WarningState]:
    states: dict[str, WarningState] = {}
    for warning in warnings:
        # Finished blocks stay in; a block that merely expired without a cancel is not news.
        covering: list[Info] = [
            info
            for info in warning.infos
            if info.area_codes & area_codes
            and (info.phase in (Phase.CANCELLED, Phase.FINAL) or info.is_active(now))
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


class BomWarningsCoordinator(DataUpdateCoordinator[tuple[ActiveWarning, ...]]):
    """One coordinator, one FTP reader and one location per config entry.

    Ticket #21 shares a single nationwide refresh between locations. The seam for that is
    `_refresh`: it already returns every current warning, and only `_covering` is specific to
    this entry's area codes, so that is where the split goes.
    """

    config_entry: BomWarningsConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: BomWarningsConfigEntry, ftp: BomFtp
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._ftp = ftp
        self._reader = WarningReader(ftp)
        self._area_codes = frozenset(config_entry.data[CONF_AREA_CODES])
        self.consecutive_failures = 0
        self._state: str = config_entry.data[CONF_STATE]
        # Every current warning in the entry's state, for the count and most-severe sensors.
        # `data` stays limited to warnings covering the location.
        self.state_warnings: tuple[ActiveWarning, ...] = ()
        self._hide_final: bool = config_entry.options.get(CONF_HIDE_FINAL, True)
        self._event_types = frozenset(config_entry.options.get(CONF_EVENT_TYPES, []))
        self._issue_id = f"no_area_{config_entry.entry_id}"
        self._next_layer_check = dt_util.utcnow()
        # Latest state of every covering product in any phase, keyed by product id.
        self.states: dict[str, WarningState] = {}

    def _refresh(self, check_layers: bool) -> tuple[list[CapWarning], set[str] | None]:
        """Blocking. Returns the warnings, and new area codes when a layer change moved them."""
        cache_dir = Path(self.hass.config.path(SPATIAL_CACHE_DIR))
        data = self.config_entry.data
        new_codes: set[str] | None = None
        # One connection per refresh instead of one login per file.
        with self._ftp.session():
            if check_layers:
                new_codes = self._re_resolve(cache_dir, data[CONF_LATITUDE], data[CONF_LONGITUDE])
            return self._reader.refresh(), new_codes

    def _re_resolve(self, cache_dir: Path, lat: float, lon: float) -> set[str] | None:
        result: RefreshResult = refresh_layers(self._ftp, cache_dir)
        for layer, error in result.failed.items():
            # The cached copy stays in use, and the next check retries.
            _LOGGER.debug("Could not refresh shapefile layer %s: %s", layer, error)
        if not result.changed:
            return None
        try:
            return resolve_coordinate(self._ftp, cache_dir, lat=lat, lon=lon)
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
        self._state = state_of(codes)
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_AREA_CODES: sorted(codes),
                CONF_STATE: state_of(codes),
            },
        )

    async def _async_update_data(self) -> tuple[ActiveWarning, ...]:
        now = dt_util.utcnow()
        check_layers = now >= self._next_layer_check
        try:
            warnings, new_codes = await self.hass.async_add_executor_job(
                self._refresh, check_layers
            )
        except BomFtpError as err:
            self.consecutive_failures += 1
            if self.consecutive_failures >= FAILURES_BEFORE_REPAIR:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    refresh_issue_id(self.config_entry),
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="refresh_failing",
                )
            raise UpdateFailed(f"Cannot read BoM warnings: {err}") from err
        self.consecutive_failures = 0
        ir.async_delete_issue(self.hass, DOMAIN, refresh_issue_id(self.config_entry))
        if check_layers:
            self._next_layer_check = now + LAYER_CHECK_INTERVAL
        if new_codes is not None:
            self._apply_resolved(new_codes)
        filters: dict[str, Any] = {
            "hide_final": self._hide_final,
            "event_types": self._event_types,
        }
        self.states = _states(warnings, self._area_codes, now)
        self.state_warnings = _in_state(warnings, self._state, self._area_codes, now, **filters)
        return _covering(warnings, self._area_codes, now, **filters)
