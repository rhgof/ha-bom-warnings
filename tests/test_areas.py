"""Tests for coordinates -> BoM area codes (AAC) resolution."""

import os
from pathlib import Path

import pytest
import shapefile

from custom_components.bom_warnings.areas import resolve_area_codes, state_of


def _write(path: Path, shapes: list[tuple[str, list[list[tuple[float, float]]]]]) -> Path:
    with shapefile.Writer(str(path)) as w:
        w.field("AAC", "C", size=20)
        for aac, rings in shapes:
            w.poly(rings)
            w.record(aac)
    return path.with_suffix(".shp")


@pytest.fixture
def layer(tmp_path):
    outer = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]  # clockwise exterior
    hole = [(4, 4), (6, 4), (6, 6), (4, 6), (4, 4)]  # counter-clockwise hole
    other = [(20, 20), (20, 30), (30, 30), (30, 20), (20, 20)]
    return _write(tmp_path / "layer", [("T_A", [outer, hole]), ("T_B", [other])])


def test_point_inside_returns_code(layer):
    assert resolve_area_codes([layer], lat=2, lon=2) == {"T_A"}


def test_point_in_hole_is_outside(layer):
    assert resolve_area_codes([layer], lat=5, lon=5) == set()


def test_point_outside_everything(layer):
    assert resolve_area_codes([layer], lat=15, lon=15) == set()


def test_other_polygon(layer):
    assert resolve_area_codes([layer], lat=25, lon=25) == {"T_B"}


def test_multiple_layers_are_combined(tmp_path, layer):
    second = _write(tmp_path / "second", [("T_C", [[(0, 0), (0, 3), (3, 3), (3, 0), (0, 0)]])])
    assert resolve_area_codes([layer, second], lat=2, lon=2) == {"T_A", "T_C"}


def test_overlapping_areas_in_one_layer_both_returned(tmp_path):
    sq = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]
    path = _write(tmp_path / "ov", [("X1", [sq]), ("X2", [sq])])
    assert resolve_area_codes([path], lat=5, lon=5) == {"X1", "X2"}


def test_nonstandard_cpg_encoding_label_is_tolerated(tmp_path):
    """IDM00014 ships a .cpg saying 'ansi 1252', which Python cannot decode."""
    path = _write(tmp_path / "ansi", [("T_A", [[(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]])])
    path.with_suffix(".cpg").write_text("ansi 1252")
    assert resolve_area_codes([path], lat=5, lon=5) == {"T_A"}


def test_missing_layer_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_area_codes([tmp_path / "nope.shp"], lat=0, lon=0)


SPATIAL = os.environ.get("BOM_SPATIAL_DIR")


@pytest.mark.skipif(not SPATIAL, reason="set BOM_SPATIAL_DIR to the unzipped BoM shapefiles")
@pytest.mark.parametrize(
    ("name", "lat", "lon", "expected_flood", "expected_district"),
    [
        ("Quilpie", -26.6123, 144.2580, "QLD_RC126", "QLD_PW011"),
        ("Toowoomba", -27.5420, 151.9128, "QLD_RC167", "QLD_PW013"),
        ("Chinchilla", -26.7387, 150.6287, "QLD_RC168", "QLD_PW013"),
        ("Hobart", -42.8899, 147.3273, None, "TAS_PW006"),
    ],
)
def test_real_bom_shapefiles(name, lat, lon, expected_flood, expected_district):
    base = Path(SPATIAL)
    codes = resolve_area_codes(
        [base / "IDM00017" / "IDM00017.shp", base / "IDM00001" / "IDM00001.shp"], lat=lat, lon=lon
    )
    assert expected_district in codes
    if expected_flood:
        assert expected_flood in codes
    else:
        assert not any("_RC" in c for c in codes)


@pytest.mark.parametrize(
    ("codes", "state"),
    [
        ({"QLD_PW011", "QLD_ME008"}, "QLD"),
        ({"NSW_ME001", "NSW_PW002"}, "NSW"),
        # The forecast district decides when codes straddle a border.
        ({"QLD_ME008", "NSW_PW002"}, "NSW"),
        ({"VIC_FW001"}, "VIC"),
    ],
)
def test_state_comes_from_the_forecast_district(codes: set[str], state: str) -> None:
    assert state_of(codes) == state
