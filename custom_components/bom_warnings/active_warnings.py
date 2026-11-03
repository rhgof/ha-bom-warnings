"""What one location sees of the parsed warnings: the active warnings that cover it, the
per-product states the event entity compares between refreshes, and a warning's list attributes.

No Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .cap import CapWarning, Info, Phase, Severity
from .strength import wind_strength


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


def covering(
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


def product_states(
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
