"""Turn a coordinate into the BoM areas that cover it, and the state they belong to.

No Home Assistant imports. Blocking (FTP and file I/O): call from an executor. The shapefile layers
are downloaded on first use and read from the cache afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .areas import state_of
from .ftp import BomFtpClient, BomFtpError
from .spatial import SpatialDataError, resolve_coordinate


class LocationUnavailable(Exception):
    """The location could not be determined: BoM was unreachable or its layers are unusable."""


@dataclass(frozen=True, slots=True)
class ResolvedLocation:
    """The areas covering a point. An empty `area_codes` means no area, with an empty `state`."""

    area_codes: frozenset[str]
    state: str


def resolve_location(
    ftp: BomFtpClient, cache_dir: Path, *, lat: float, lon: float, radius_m: float = 0.0
) -> ResolvedLocation:
    """Resolve a point, or the area within `radius_m` of it, to its area codes and state.

    Raises LocationUnavailable when BoM cannot be reached or a layer is unusable. A point that no
    area covers is an empty result, not an error, because callers report that differently.
    """
    try:
        with ftp.session():
            codes = resolve_coordinate(ftp, cache_dir, lat=lat, lon=lon, radius_m=radius_m)
    except (BomFtpError, SpatialDataError, OSError) as err:
        raise LocationUnavailable(str(err)) from err
    if not codes:
        return ResolvedLocation(frozenset(), "")
    return ResolvedLocation(frozenset(codes), state_of(codes))
