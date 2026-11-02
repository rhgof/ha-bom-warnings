"""Polls the BoM warning feed for one config entry."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .cap import CapWarning, Info, Phase, Severity
from .const import CONF_AREA_CODES, CONF_STATE, DOMAIN
from .feed import WarningReader
from .ftp import BomFtp, BomFtpError

if TYPE_CHECKING:
    from . import BomWarningsConfigEntry

_LOGGER = logging.getLogger(__name__)

# Not user-configurable, so users cannot hammer BoM's server.
UPDATE_INTERVAL = timedelta(minutes=10)
# A single failed poll is routine; three in a row (30 minutes) is worth telling the user about.
FAILURES_BEFORE_REPAIR = 3


def refresh_issue_id(entry: BomWarningsConfigEntry) -> str:
    return f"refresh_failing_{entry.entry_id}"


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


def _active(
    warnings: list[CapWarning], now: datetime, matches: Callable[[Info], bool]
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
        )
        for warning in warnings
        for info in warning.infos
        if info.is_active(now) and matches(info)
    )


def _covering(
    warnings: list[CapWarning], area_codes: frozenset[str], now: datetime
) -> tuple[ActiveWarning, ...]:
    return _active(warnings, now, lambda info: bool(info.area_codes & area_codes))


def _in_state(
    warnings: list[CapWarning], state: str, area_codes: frozenset[str], now: datetime
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
        # Latest state of every covering product in any phase, keyed by product id.
        self.states: dict[str, WarningState] = {}

    def _refresh(self) -> list[CapWarning]:
        # One connection per refresh instead of one login per file.
        with self._ftp.session():
            return self._reader.refresh()

    async def _async_update_data(self) -> tuple[ActiveWarning, ...]:
        try:
            warnings = await self.hass.async_add_executor_job(self._refresh)
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
        now = dt_util.utcnow()
        self.states = _states(warnings, self._area_codes, now)
        self.state_warnings = _in_state(warnings, self._state, self._area_codes, now)
        return _covering(warnings, self._area_codes, now)
