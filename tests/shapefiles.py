"""Tiny generated shapefile layers, served from the fake FTP client in place of BoM's real ones."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import shapefile

from custom_components.bom_warnings.spatial import SPATIAL_DIR

SQUARE = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]


def zip_layer(tmp_path: Path, name: str, aac: str) -> bytes:
    """A one-polygon layer, the square from (0, 0) to (10, 10), whose only area is `aac`."""
    stem = tmp_path / "build" / name
    stem.parent.mkdir(exist_ok=True)
    with shapefile.Writer(str(stem)) as w:
        w.field("AAC", "C", size=20)
        w.poly([SQUARE])
        w.record(aac)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for suffix in (".shp", ".shx", ".dbf"):
            archive.write(stem.with_suffix(suffix), f"{name}{suffix}")
    return buffer.getvalue()


def remote(layer: str) -> str:
    return f"{SPATIAL_DIR}{layer}.zip"


def zip_real(base: Path, layer: str) -> bytes:
    """A real BoM layer, zipped from an unzipped folder (`BOM_SPATIAL_DIR`) as BoM serves it."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for part in (base / layer).iterdir():
            archive.write(part, part.name)
    return buffer.getvalue()
