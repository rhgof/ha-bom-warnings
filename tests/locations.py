"""Test data for what a point resolves to."""

from __future__ import annotations

from custom_components.bom_warnings.areas import state_of
from custom_components.bom_warnings.location import ResolvedLocation


def location_of(*codes: str) -> ResolvedLocation:
    """The location covering exactly these area codes; no codes means no area."""
    found = set(codes)
    return ResolvedLocation(frozenset(found), state_of(found) if found else "")
