"""Tests for resolving a coordinate from shapefile layers cached offline."""

import io
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
import shapefile

from custom_components.bom_warnings.areas import resolve_area_codes
from custom_components.bom_warnings.ftp import BomFtpError
from custom_components.bom_warnings.spatial import (
    LAYERS,
    SPATIAL_DIR,
    SpatialDataError,
    refresh_layers,
    resolve_coordinate,
)
from tests.fake_ftp import FakeFtp

SQUARE = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]


def _zip_layer(tmp_path: Path, name: str, aac: str) -> bytes:
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


def _remote(layer: str) -> str:
    return f"{SPATIAL_DIR}{layer}.zip"


@pytest.fixture
def ftp(tmp_path: Path) -> FakeFtp:
    return FakeFtp({_remote(layer): _zip_layer(tmp_path, layer, f"T_{layer}") for layer in LAYERS})


def test_first_use_downloads_every_layer(ftp: FakeFtp, tmp_path: Path) -> None:
    codes = resolve_coordinate(ftp, tmp_path / "cache", lat=5, lon=5)
    assert codes == {f"T_{layer}" for layer in LAYERS}
    assert sorted(remote for remote, _ in ftp.downloads) == sorted(_remote(x) for x in LAYERS)


def test_later_use_makes_no_network_calls(ftp: FakeFtp, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    resolve_coordinate(ftp, cache, lat=5, lon=5)
    ftp.downloads.clear()
    ftp.error = BomFtpError("offline")
    assert resolve_coordinate(ftp, cache, lat=5, lon=5)
    assert ftp.downloads == []


def test_point_outside_returns_nothing(ftp: FakeFtp, tmp_path: Path) -> None:
    assert resolve_coordinate(ftp, tmp_path / "cache", lat=50, lon=50) == set()


@pytest.mark.parametrize(
    "bad",
    [b"", b"not a zip at all", b"PK\x03\x04truncated"],
    ids=["empty", "garbage", "truncated"],
)
def test_corrupt_download_is_rejected_and_not_cached(
    ftp: FakeFtp, tmp_path: Path, bad: bytes
) -> None:
    ftp.files[_remote(LAYERS[2])] = bad
    cache = tmp_path / "cache"
    with pytest.raises(SpatialDataError):
        resolve_coordinate(ftp, cache, lat=5, lon=5)
    assert not (cache / LAYERS[2]).exists()
    assert {p.name for p in cache.iterdir()} <= set(LAYERS)


def test_zip_missing_a_shapefile_part_is_rejected(ftp: FakeFtp, tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{LAYERS[0]}.shp", b"x")
    ftp.files[_remote(LAYERS[0])] = buffer.getvalue()
    cache = tmp_path / "cache"
    with pytest.raises(SpatialDataError):
        resolve_coordinate(ftp, cache, lat=5, lon=5)
    assert not (cache / LAYERS[0]).exists()


def test_retry_after_corrupt_download_succeeds(ftp: FakeFtp, tmp_path: Path) -> None:
    good = ftp.files[_remote(LAYERS[0])]
    ftp.files[_remote(LAYERS[0])] = b"junk"
    cache = tmp_path / "cache"
    with pytest.raises(SpatialDataError):
        resolve_coordinate(ftp, cache, lat=5, lon=5)
    ftp.files[_remote(LAYERS[0])] = good
    assert f"T_{LAYERS[0]}" in resolve_coordinate(ftp, cache, lat=5, lon=5)


T0 = datetime(2026, 10, 1, tzinfo=UTC)
T1 = datetime(2026, 11, 1, tzinfo=UTC)


@pytest.fixture
def cached(ftp: FakeFtp, tmp_path: Path) -> Path:
    ftp.mtimes = {_remote(layer): T0 for layer in LAYERS}
    cache = tmp_path / "cache"
    resolve_coordinate(ftp, cache, lat=5, lon=5)
    ftp.downloads.clear()
    return cache


def test_unchanged_layers_are_not_downloaded(ftp: FakeFtp, cached: Path) -> None:
    result = refresh_layers(ftp, cached)
    assert result.changed == [] and result.failed == {}
    assert ftp.downloads == []


def test_changed_layer_is_redownloaded_and_reported(
    ftp: FakeFtp, cached: Path, tmp_path: Path
) -> None:
    layer = LAYERS[1]
    ftp.files[_remote(layer)] = _zip_layer(tmp_path, layer, "NEW_CODE")
    ftp.mtimes[_remote(layer)] = T1
    result = refresh_layers(ftp, cached)
    assert result.changed == [layer] and result.failed == {}
    assert [remote for remote, _ in ftp.downloads] == [_remote(layer)]
    assert "NEW_CODE" in resolve_coordinate(ftp, cached, lat=5, lon=5)
    assert refresh_layers(ftp, cached).changed == []
    assert sorted(p.name for p in cached.iterdir()) == sorted(LAYERS)


def test_layer_cached_without_known_mtime_is_refreshed(ftp: FakeFtp, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    resolve_coordinate(ftp, cache, lat=5, lon=5)
    ftp.mtimes = {_remote(layer): T0 for layer in LAYERS}
    assert refresh_layers(ftp, cache).changed == list(LAYERS)


def test_failed_check_keeps_cache_and_reports(ftp: FakeFtp, cached: Path) -> None:
    ftp.modified_error = BomFtpError("offline")
    result = refresh_layers(ftp, cached)
    assert result.changed == [] and set(result.failed) == set(LAYERS)
    assert resolve_coordinate(ftp, cached, lat=5, lon=5)


@pytest.mark.parametrize("bad", [b"", b"junk"], ids=["empty", "garbage"])
def test_failed_download_keeps_old_copy_and_other_layers_proceed(
    ftp: FakeFtp, cached: Path, tmp_path: Path, bad: bytes
) -> None:
    broken, fine = LAYERS[0], LAYERS[1]
    ftp.files[_remote(broken)] = bad
    ftp.files[_remote(fine)] = _zip_layer(tmp_path, fine, "NEW_CODE")
    ftp.mtimes[_remote(broken)] = ftp.mtimes[_remote(fine)] = T1
    result = refresh_layers(ftp, cached)
    assert result.changed == [fine] and set(result.failed) == {broken}
    codes = resolve_coordinate(ftp, cached, lat=5, lon=5)
    assert f"T_{broken}" in codes and "NEW_CODE" in codes
    # The failed layer is retried next time.
    assert set(refresh_layers(ftp, cached).failed) == {broken}


def test_download_error_keeps_old_copy(ftp: FakeFtp, cached: Path) -> None:
    ftp.mtimes[_remote(LAYERS[0])] = T1
    ftp.error = BomFtpError("dropped")
    result = refresh_layers(ftp, cached)
    assert set(result.failed) == {LAYERS[0]}
    ftp.error = None
    assert f"T_{LAYERS[0]}" in resolve_coordinate(ftp, cached, lat=5, lon=5)


def test_missing_remote_layer_is_a_failure(ftp: FakeFtp, cached: Path) -> None:
    del ftp.mtimes[_remote(LAYERS[0])]
    assert set(refresh_layers(ftp, cached).failed) == {LAYERS[0]}


SPATIAL = os.environ.get("BOM_SPATIAL_DIR")


def _zip_real(base: Path, layer: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for part in (base / layer).iterdir():
            archive.write(part, part.name)
    return buffer.getvalue()


@pytest.mark.skipif(not SPATIAL, reason="set BOM_SPATIAL_DIR to the unzipped BoM shapefiles")
@pytest.mark.parametrize(
    ("lat", "lon", "expected"),
    [
        (-26.6123, 144.2580, {"QLD_RC126", "QLD_PW011"}),  # Quilpie
        (-27.5420, 151.9128, {"QLD_RC167", "QLD_PW013", "QLD_ME010"}),  # Toowoomba
        (-26.7387, 150.6287, {"QLD_RC168", "QLD_PW013"}),  # Chinchilla
        (-42.8899, 147.3273, {"TAS_PW006"}),  # Hobart
    ],
    ids=["quilpie", "toowoomba", "chinchilla", "hobart"],
)
def test_real_shapefiles_through_cache(
    tmp_path: Path, lat: float, lon: float, expected: set[str]
) -> None:
    base = Path(SPATIAL)
    fake = FakeFtp({_remote(layer): _zip_real(base, layer) for layer in LAYERS})
    cache = tmp_path / "cache"
    codes = resolve_coordinate(fake, cache, lat=lat, lon=lon)
    assert expected <= codes
    fake.downloads.clear()
    assert resolve_coordinate(fake, cache, lat=lat, lon=lon) == codes
    assert fake.downloads == []
    assert codes == resolve_area_codes(
        [base / layer / f"{layer}.shp" for layer in LAYERS], lat=lat, lon=lon
    )
