"""Resolve a coordinate to area codes from shapefile layers cached on disk.

No Home Assistant imports. Layers are downloaded once through the shared FTP interface and read
offline afterwards. Blocking (FTP and file I/O): call from an executor.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
import zlib
from pathlib import Path

from .areas import resolve_area_codes
from .ftp import BomFtpClient

SPATIAL_DIR = "/anon/home/adfd/spatial/"
# Forecast districts, metro areas, flood warning catchments, flood watch catchments, fire weather.
LAYERS = ("IDM00001", "IDM00014", "IDM00017", "IDM00020", "IDM00007")
_REQUIRED_SUFFIXES = (".shp", ".shx", ".dbf")


class SpatialDataError(Exception):
    """A downloaded shapefile archive is empty, corrupt or incomplete."""


def _extract(archive_path: Path, layer: str, target: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            bad = archive.testzip()
            if bad is not None:
                raise SpatialDataError(f"{layer}: corrupt member {bad}")
            # Flatten to base names so a hostile archive cannot write outside the target.
            members = {
                Path(name).name: name for name in archive.namelist() if not name.endswith("/")
            }
            for suffix in _REQUIRED_SUFFIXES:
                if f"{layer}{suffix}" not in members:
                    raise SpatialDataError(f"{layer}: archive has no {suffix} file")
            for base, name in members.items():
                (target / base).write_bytes(archive.read(name))
    except (zipfile.BadZipFile, EOFError, OSError, zlib.error) as err:
        raise SpatialDataError(f"{layer}: unreadable archive ({err})") from err


def _ensure_layer(ftp: BomFtpClient, cache_dir: Path, layer: str) -> Path:
    shp = cache_dir / layer / f"{layer}.shp"
    if shp.exists():
        return shp
    # Stage beside the final location so the rename is atomic and a failure leaves nothing behind.
    staging = Path(tempfile.mkdtemp(prefix=f".{layer}-", dir=cache_dir))
    try:
        archive_path = staging / f"{layer}.zip"
        ftp.download(f"{SPATIAL_DIR}{layer}.zip", str(archive_path))
        extracted = staging / "files"
        extracted.mkdir()
        _extract(archive_path, layer, extracted)
        extracted.rename(cache_dir / layer)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return shp


def resolve_coordinate(ftp: BomFtpClient, cache_dir: Path, *, lat: float, lon: float) -> set[str]:
    """Return the area codes covering the point, downloading any layer not yet cached."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    layers = [_ensure_layer(ftp, cache_dir, layer) for layer in LAYERS]
    return resolve_area_codes(layers, lat=lat, lon=lon)
