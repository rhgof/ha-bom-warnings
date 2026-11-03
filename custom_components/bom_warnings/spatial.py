"""Resolve a coordinate to area codes from shapefile layers cached on disk.

No Home Assistant imports. Layers are downloaded once through the shared FTP interface and read
offline afterwards. Blocking (FTP and file I/O): call from an executor.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .areas import resolve_areas
from .ftp import BomFtpClient, BomFtpError

SPATIAL_DIR = "/anon/home/adfd/spatial/"
# Forecast districts, metro areas, flood warning catchments, flood watch catchments, fire weather,
# and coastal waters (a land point is never inside one, so only a radius reaches them).
LAYERS = ("IDM00001", "IDM00014", "IDM00017", "IDM00020", "IDM00007", "IDM00003")
_MTIME_FILE = ".server_mtime"
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


def _remote(layer: str) -> str:
    return f"{SPATIAL_DIR}{layer}.zip"


def _cached_mtime(cache_dir: Path, layer: str) -> datetime | None:
    try:
        return datetime.fromisoformat((cache_dir / layer / _MTIME_FILE).read_text())
    except OSError, ValueError:
        return None


def _install_layer(ftp: BomFtpClient, cache_dir: Path, layer: str, mtime: datetime | None) -> None:
    """Download, validate and swap in a layer; on any failure the existing copy is untouched."""
    # Stage beside the final location so the rename is atomic and a failure leaves nothing behind.
    staging = Path(tempfile.mkdtemp(prefix=f".{layer}-", dir=cache_dir))
    final = cache_dir / layer
    try:
        archive_path = staging / f"{layer}.zip"
        ftp.download(_remote(layer), str(archive_path))
        extracted = staging / "files"
        extracted.mkdir()
        _extract(archive_path, layer, extracted)
        # Stored inside the layer so it is swapped in together with the data it describes.
        if mtime is not None:
            (extracted / _MTIME_FILE).write_text(mtime.isoformat())
        old = staging / "old"
        if final.exists():
            final.rename(old)
        try:
            extracted.rename(final)
        except OSError:
            if old.exists():
                old.rename(final)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _ensure_layer(ftp: BomFtpClient, cache_dir: Path, layer: str) -> Path:
    shp = cache_dir / layer / f"{layer}.shp"
    if not shp.exists():
        try:
            mtime = ftp.modified(_remote(layer))
        except BomFtpError:
            # The download below reports a real outage; a refresh will pick up the time later.
            mtime = None
        _install_layer(ftp, cache_dir, layer, mtime)
    return shp


@dataclass(frozen=True, slots=True)
class RefreshResult:
    changed: list[str] = field(default_factory=list)
    # Layer to error text; those layers keep their previous cached copy.
    failed: dict[str, str] = field(default_factory=dict)


def refresh_layers(ftp: BomFtpClient, cache_dir: Path) -> RefreshResult:
    """Re-download layers whose server modification time differs from the cached copy.

    A failure for one layer is recorded and leaves its cached copy usable; others still proceed.
    Callers re-resolve stored area codes when `changed` is not empty.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    result = RefreshResult()
    for layer in LAYERS:
        try:
            remote = ftp.modified(_remote(layer))
            if remote is None:
                raise SpatialDataError(f"{layer}: not found on server")
            usable = (cache_dir / layer / f"{layer}.shp").exists()
            if usable and _cached_mtime(cache_dir, layer) == remote:
                continue
            _install_layer(ftp, cache_dir, layer, remote)
        except (BomFtpError, SpatialDataError, OSError) as err:
            result.failed[layer] = str(err)
        else:
            result.changed.append(layer)
    return result


def resolve_coordinate(
    ftp: BomFtpClient, cache_dir: Path, *, lat: float, lon: float, radius_m: float = 0.0
) -> dict[str, str]:
    """Return the areas within `radius_m` of the point by area code, each with its name (or an
    empty string), downloading any layer not cached."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    layers = [_ensure_layer(ftp, cache_dir, layer) for layer in LAYERS]
    return resolve_areas(layers, lat=lat, lon=lon, radius_m=radius_m)
