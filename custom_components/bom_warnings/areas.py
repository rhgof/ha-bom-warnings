"""Resolve coordinates to BoM AMOC area codes (AACs) using the static shapefiles.

No Home Assistant imports. The shapefiles (IDM00001, IDM00017, ...) are published at
ftp://ftp.bom.gov.au/anon/home/adfd/spatial/; the ``AAC`` field equals the CAP
``AMOC-AreaCode`` geocode. This does blocking file I/O: call it from an executor.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Iterable
from pathlib import Path

import shapefile

_DISTRICT_MARKER = "_PW"
MARINE_MARKER = "_MW"
# Mean Earth radius times pi / 180. The error against a true geodesic is well under 1% at the
# distances used here, which is far finer than the shapefile boundaries themselves.
_METRES_PER_DEGREE = 111_195.0


def is_marine(code: str) -> bool:
    """Coastal-water zone codes, e.g. `NSW_MW004`."""
    return MARINE_MARKER in code


def state_of(area_codes: set[str]) -> str:
    """The state prefix of the forecast district code, e.g. `QLD_PW011` gives `QLD`."""
    districts = sorted(code for code in area_codes if _DISTRICT_MARKER in code)
    return (districts or sorted(area_codes))[0].split("_")[0]


def _inside(lon: float, lat: float, points: list[tuple[float, float]], parts: list[int]) -> bool:
    """Even-odd rule over every ring of a shape, so holes and multipart areas work."""
    bounds = [*parts, len(points)]
    inside = False
    for start, end in zip(bounds, bounds[1:], strict=False):
        ring = points[start:end]
        for i in range(len(ring)):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % len(ring)]
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def _near(
    lon: float,
    lat: float,
    radius_m: float,
    points: list[tuple[float, float]],
    parts: list[int],
) -> bool:
    """True when any edge of the shape passes within `radius_m` of the point.

    Works on a flat plane centred on the point, scaling longitude by cos(latitude). That is
    accurate to well under 1% for a radius of tens of kilometres.
    """
    kx = _METRES_PER_DEGREE * math.cos(math.radians(lat))
    ky = _METRES_PER_DEGREE
    limit = radius_m * radius_m
    bounds = [*parts, len(points)]
    for start, end in zip(bounds, bounds[1:], strict=False):
        ring = [((x - lon) * kx, (y - lat) * ky) for x, y in points[start:end]]
        for i in range(len(ring)):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % len(ring)]
            # Most edges are nowhere near, and this is cheaper than the distance.
            if (
                (x1 > radius_m and x2 > radius_m)
                or (x1 < -radius_m and x2 < -radius_m)
                or (y1 > radius_m and y2 > radius_m)
                or (y1 < -radius_m and y2 < -radius_m)
            ):
                continue
            dx, dy = x2 - x1, y2 - y1
            length = dx * dx + dy * dy
            # Projection of the origin onto the edge, clamped to the segment.
            t = 0.0 if length == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / length))
            cx, cy = x1 + t * dx, y1 + t * dy
            if cx * cx + cy * cy <= limit:
                return True
    return False


def _layer_codes(path: Path, lon: float, lat: float, radius_m: float) -> set[str]:
    codes: set[str] = set()
    # Some layers ship a .cpg labelled "ansi 1252", which Python cannot decode. We only
    # read the ASCII AAC field, so force an encoding rather than trusting the label.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # "encoding differs from .cpg"
        reader = shapefile.Reader(str(path), encoding="cp1252", encodingErrors="replace")
    # The bounding box widened by the radius, so a shape that cannot reach the circle is skipped
    # without reading its points.
    pad_lat = radius_m / _METRES_PER_DEGREE
    pad_lon = pad_lat / max(math.cos(math.radians(lat)), 0.01)
    with reader:
        names = [f[0] for f in reader.fields[1:]]
        if "AAC" not in names:
            return codes
        aac_index = names.index("AAC")
        for item in reader.iterShapeRecords():
            west, south, east, north = item.shape.bbox
            if not (
                west - pad_lon <= lon <= east + pad_lon
                and south - pad_lat <= lat <= north + pad_lat
            ):
                continue
            points = item.shape.points
            parts = list(item.shape.parts)
            if _inside(lon, lat, points, parts) or (
                radius_m > 0 and _near(lon, lat, radius_m, points, parts)
            ):
                code = item.record[aac_index]
                if code:
                    codes.add(str(code))
    return codes


def resolve_area_codes(
    layers: Iterable[Path], *, lat: float, lon: float, radius_m: float = 0.0
) -> set[str]:
    """Return the AAC of every area, across all given shapefiles, within `radius_m` of the point.

    A radius of 0 is the plain point-in-polygon test. Otherwise an area counts when the point is
    inside it or the distance from the point to its boundary is at most the radius.
    """
    if radius_m < 0:
        raise ValueError(f"radius must not be negative: {radius_m}")
    codes: set[str] = set()
    for layer in layers:
        path = Path(layer)
        if not path.exists():
            raise FileNotFoundError(path)
        codes |= _layer_codes(path, lon, lat, radius_m)
    return codes
