"""The one entry point from a coordinate to a resolved location, through the fake FTP client."""

import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from custom_components.bom_warnings.areas import state_of
from custom_components.bom_warnings.ftp import BomFtpError, BomFtpRejectedError
from custom_components.bom_warnings.location import (
    LocationUnavailable,
    ResolvedLocation,
    resolve_location,
)
from custom_components.bom_warnings.spatial import LAYERS, resolve_coordinate
from tests.fake_ftp import FakeFtp
from tests.shapefiles import remote, zip_layer, zip_real

# Every generated layer is the same square, so a point inside it is in one area per layer.
AREAS = {
    "IDM00001": "QLD_PW011",
    "IDM00014": "QLD_ME001",
    "IDM00017": "QLD_FW001",
    "IDM00020": "QLD_FA001",
    "IDM00007": "QLD_FWD01",
    "IDM00003": "QLD_MW004",
}


@pytest.fixture
def ftp(tmp_path: Path) -> FakeFtp:
    return FakeFtp({remote(layer): zip_layer(tmp_path, layer, AREAS[layer]) for layer in LAYERS})


def test_layers_cover_the_generated_areas() -> None:
    assert set(AREAS) == set(LAYERS)


def test_point_inside_gives_its_areas_and_state(ftp: FakeFtp, tmp_path: Path) -> None:
    location = resolve_location(ftp, tmp_path / "cache", lat=5, lon=5)
    assert location == ResolvedLocation(frozenset(AREAS.values()), "QLD")


def test_point_outside_every_area_is_empty_not_an_error(ftp: FakeFtp, tmp_path: Path) -> None:
    location = resolve_location(ftp, tmp_path / "cache", lat=50, lon=50)
    assert location == ResolvedLocation(frozenset(), "")


def test_radius_reaches_areas_beside_the_point(ftp: FakeFtp, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    assert not resolve_location(ftp, cache, lat=5, lon=11).area_codes
    # One degree east of the square is about 111 km.
    reached = resolve_location(ftp, cache, lat=5, lon=11, radius_m=120_000)
    assert reached.area_codes == frozenset(AREAS.values())


def test_result_is_frozen(ftp: FakeFtp, tmp_path: Path) -> None:
    location = resolve_location(ftp, tmp_path / "cache", lat=5, lon=5)
    with pytest.raises(FrozenInstanceError):
        location.state = "NSW"  # type: ignore[misc]


def test_session_is_opened_once_and_closed(ftp: FakeFtp, tmp_path: Path) -> None:
    resolve_location(ftp, tmp_path / "cache", lat=5, lon=5)
    assert (ftp.sessions_started, ftp.sessions_open) == (1, 0)


def _break_download(ftp: FakeFtp, error: BaseException) -> None:
    def fail(remote_path: str, local_path: str) -> None:
        raise error

    ftp.download = fail  # type: ignore[method-assign]


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param(lambda ftp: setattr(ftp, "error", BomFtpError("offline")), id="ftp-failure"),
        pytest.param(
            lambda ftp: setattr(ftp, "error", BomFtpRejectedError("550")), id="ftp-rejected"
        ),
        pytest.param(lambda ftp: ftp.files.update({remote(LAYERS[0]): b"junk"}), id="bad-archive"),
        pytest.param(lambda ftp: _break_download(ftp, OSError("disk full")), id="os-error"),
    ],
)
def test_failure_to_determine_raises_one_error(ftp: FakeFtp, tmp_path: Path, setup: object) -> None:
    setup(ftp)  # type: ignore[operator]
    with pytest.raises(LocationUnavailable) as raised:
        resolve_location(ftp, tmp_path / "cache", lat=5, lon=5)
    assert raised.value.__cause__ is not None
    # The session is closed even though the work failed.
    assert ftp.sessions_open == 0


def test_unexpected_exception_propagates_unchanged(ftp: FakeFtp, tmp_path: Path) -> None:
    _break_download(ftp, RuntimeError("a bug"))
    with pytest.raises(RuntimeError, match="a bug"):
        resolve_location(ftp, tmp_path / "cache", lat=5, lon=5)
    assert ftp.sessions_open == 0


def test_negative_radius_propagates_unchanged(ftp: FakeFtp, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="radius"):
        resolve_location(ftp, tmp_path / "cache", lat=5, lon=5, radius_m=-1)


SPATIAL = os.environ.get("BOM_SPATIAL_DIR")


@pytest.mark.skipif(not SPATIAL, reason="set BOM_SPATIAL_DIR to the unzipped BoM shapefiles")
@pytest.mark.parametrize(
    ("lat", "lon", "expected", "state"),
    [
        (-26.6123, 144.2580, {"QLD_RC126", "QLD_PW011"}, "QLD"),  # Quilpie
        (-27.5420, 151.9128, {"QLD_RC167", "QLD_PW013", "QLD_ME010"}, "QLD"),  # Toowoomba
        (-42.8899, 147.3273, {"TAS_PW006"}, "TAS"),  # Hobart
    ],
    ids=["quilpie", "toowoomba", "hobart"],
)
def test_real_shapefiles_resolve_to_the_same_areas_and_state(
    tmp_path: Path, lat: float, lon: float, expected: set[str], state: str
) -> None:
    base = Path(SPATIAL or "")
    fake = FakeFtp({remote(layer): zip_real(base, layer) for layer in LAYERS})
    cache = tmp_path / "cache"

    found = resolve_location(fake, cache, lat=lat, lon=lon)

    assert expected <= found.area_codes
    assert found.state == state
    # The same answer the callers used to assemble for themselves.
    codes = resolve_coordinate(fake, cache, lat=lat, lon=lon)
    assert found == ResolvedLocation(frozenset(codes), state_of(codes))
    # A radius only ever adds areas.
    wider = resolve_location(fake, cache, lat=lat, lon=lon, radius_m=50_000)
    assert found.area_codes <= wider.area_codes


@pytest.mark.skipif(not SPATIAL, reason="set BOM_SPATIAL_DIR to the unzipped BoM shapefiles")
def test_real_shapefiles_find_no_area_at_sea(tmp_path: Path) -> None:
    base = Path(SPATIAL or "")
    fake = FakeFtp({remote(layer): zip_real(base, layer) for layer in LAYERS})

    assert resolve_location(fake, tmp_path / "cache", lat=0.0, lon=0.0) == ResolvedLocation(
        frozenset(), ""
    )
