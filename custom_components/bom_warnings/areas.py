"""Resolve coordinates to BoM AMOC area codes (AACs) using the static shapefiles.

No Home Assistant imports. The shapefiles (IDM00001, IDM00017, ...) are published at
ftp://ftp.bom.gov.au/anon/home/adfd/spatial/; the ``AAC`` field equals the CAP
``AMOC-AreaCode`` geocode. This does blocking file I/O: call it from an executor.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from pathlib import Path

import shapefile


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


def _layer_codes(path: Path, lon: float, lat: float) -> set[str]:
    codes: set[str] = set()
    # Some layers ship a .cpg labelled "ansi 1252", which Python cannot decode. We only
    # read the ASCII AAC field, so force an encoding rather than trusting the label.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # "encoding differs from .cpg"
        reader = shapefile.Reader(str(path), encoding="cp1252", encodingErrors="replace")
    with reader:
        names = [f[0] for f in reader.fields[1:]]
        if "AAC" not in names:
            return codes
        aac_index = names.index("AAC")
        for item in reader.iterShapeRecords():
            west, south, east, north = item.shape.bbox
            if not (west <= lon <= east and south <= lat <= north):
                continue
            if _inside(lon, lat, item.shape.points, list(item.shape.parts)):
                code = item.record[aac_index]
                if code:
                    codes.add(str(code))
    return codes


def resolve_area_codes(layers: Iterable[Path], *, lat: float, lon: float) -> set[str]:
    """Return the AAC of every area, across all given shapefiles, containing the point."""
    codes: set[str] = set()
    for layer in layers:
        path = Path(layer)
        if not path.exists():
            raise FileNotFoundError(path)
        codes |= _layer_codes(path, lon, lat)
    return codes
