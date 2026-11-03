"""What one location sees of the parsed warnings: the active warnings that cover it, the
per-product states the event entity compares between refreshes, and a warning's list attributes.

No Home Assistant imports.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .cap import CapWarning, Info, Phase, Severity
from .const import DEFAULT_EVENT_ICON, EVENT_ICONS, LEVEL_COLORS, WARNING_TYPE_NOTES


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

# The one severity order, lowest first. It is our ranking policy, not CAP's: `unknown` sits between
# moderate and severe because BoM sends it for Severe Weather and Severe Thunderstorm warnings,
# which must not rank below a minor flood. The ranked list, the level sensors and the block that
# stands for a product in the event data all derive from it.
SEVERITY_ORDER = (
    Severity.MINOR,
    Severity.MODERATE,
    Severity.UNKNOWN,
    Severity.SEVERE,
    Severity.EXTREME,
)


def warning_attributes(warning: ActiveWarning, *, ranked: bool = False) -> dict[str, Any]:
    """One warning as the list attributes entities show it.

    The ranked list adds the level, icon, colour and sent time to the fields every list has.
    """
    attributes: dict[str, Any] = {
        "product_id": warning.product_id,
        "event": warning.event,
        "headline": warning.headline,
        "severity": str(warning.severity),
        "phase": str(warning.phase),
        "effective": warning.effective.isoformat() if warning.effective else None,
        "expires": warning.expires.isoformat() if warning.expires else None,
    }
    if ranked:
        level = level_of(warning)
        attributes |= {
            "level": level,
            "icon": event_icon(warning.event),
            "color": LEVEL_COLORS[level],
            "sent": warning.sent.isoformat() if warning.sent else None,
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
        info = max(covering, key=lambda i: SEVERITY_ORDER.index(i.severity))
        states[warning.product_id] = WarningState(
            product_id=warning.product_id,
            identifier=warning.identifier,
            phase=info.phase,
            event=info.event,
            headline=info.headline,
            severity=info.severity,
        )
    return states


_LEVEL_RANK = {severity.value: rank for rank, severity in enumerate(SEVERITY_ORDER)}
_EPOCH = datetime.min.replace(tzinfo=UTC)

STATE_NONE = "none"
# The states of a type sensor, lowest first: the severity order, with BoM's CAP severity `unknown`
# (sent for Severe Thunderstorm and Severe Weather warnings) called `unrated`, because `unknown` is
# Home Assistant's own no-value state and must not be a state of ours.
LEVEL_OPTIONS = [
    STATE_NONE,
    *("unrated" if severity is Severity.UNKNOWN else severity.value for severity in SEVERITY_ORDER),
]


def level_of(warning: ActiveWarning) -> str:
    return warning.severity.value


def rank_warnings(warnings: Iterable[ActiveWarning]) -> list[ActiveWarning]:
    """Most severe first; ties go to the most recently issued, undated last, then product id."""
    return sorted(
        warnings,
        key=lambda w: (
            -_LEVEL_RANK[level_of(w)],
            w.sent is None,
            -(w.sent or _EPOCH).timestamp(),
            w.product_id,
        ),
    )


def highest_level(warnings: Iterable[ActiveWarning]) -> str:
    """The top level among the warnings still in force, or `none`."""
    current = rank_warnings(w for w in warnings if w.is_current)
    if not current:
        return STATE_NONE
    level = level_of(current[0])
    return "unrated" if level == "unknown" else level


def current_then_ended(warnings: Iterable[ActiveWarning]) -> list[ActiveWarning]:
    ranked = rank_warnings(warnings)
    return [w for w in ranked if w.is_current] + [w for w in ranked if not w.is_current]


def event_icon(event: str) -> str:
    return EVENT_ICONS.get(event, DEFAULT_EVENT_ICON)


def type_attributes(event: str, warnings: Sequence[ActiveWarning]) -> dict[str, Any]:
    """The attributes of one type's level sensor: its top warning's fields, then every warning.

    The top warning is the highest-ranked one still in force. Only marine wind carries a strength,
    and only some types a note.
    """
    current = rank_warnings(w for w in warnings if w.is_current)
    top = current[0] if current else None
    attributes: dict[str, Any] = {
        "headline": top.headline if top else None,
        "expires": top.expires.isoformat() if top and top.expires else None,
        "product_id": top.product_id if top else None,
        "event": top.event if top else None,
        "warnings": [warning_attributes(w) for w in warnings],
    }
    if event == WIND_EVENT:
        attributes["strength"] = top.strength if top else None
    if note := WARNING_TYPE_NOTES.get(event):
        attributes["note"] = note
    return attributes


# The marine wind strength class, read from the headline.
WIND_EVENT = "Wind"

_CLASSES = {
    "strong": "strong",
    "gale force": "gale",
    "gale": "gale",
    "storm force": "storm",
    "storm": "storm",
    "hurricane force": "hurricane",
    "hurricane": "hurricane",
}
_HEADLINE = re.compile(r"^(?P<class>.+?)\s+wind\s+warning\b", re.IGNORECASE)


def wind_strength(event: str, headline: str) -> str | None:
    """The strength class of a Wind warning, or None.

    Known classes are lowercase and stable (`strong`, `gale`, `storm`, `hurricane`). Wording this
    code does not know keeps its class text as written, so a new class is shown and not lost. A
    cancellation, a headline with no class, and any event other than Wind have no strength.
    """
    if event != WIND_EVENT:
        return None
    match = _HEADLINE.match(headline.strip())
    if match is None:
        return None
    text = match.group("class").strip()
    if text.lower().startswith("cancellation"):
        return None
    return _CLASSES.get(text.lower(), text)
