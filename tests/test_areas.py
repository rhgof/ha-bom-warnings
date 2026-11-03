"""Tests for coordinates -> BoM area codes (AAC) resolution."""

import os
import time
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
        # And when the district code sorts after the other state's code.
        ({"NSW_ME001", "QLD_PW011"}, "QLD"),
        ({"VIC_FW001"}, "VIC"),
    ],
)
def test_state_comes_from_the_forecast_district(codes: set[str], state: str) -> None:
    assert state_of(codes) == state


# One degree of latitude is about 111.2 km everywhere; of longitude it shrinks with cos(latitude).
@pytest.mark.parametrize(
    ("lat", "lon", "radius_m", "expected"),
    [
        # Inside the polygon: any radius, including none, gives the point-in-polygon result.
        (2, 2, 0, {"T_A"}),
        (2, 2, 100, {"T_A"}),
        # Outside: the nearest edge is 1 degree (111 km) east of the square.
        (5, 11, 100_000, set()),
        (5, 11, 112_000, {"T_A"}),
        # In the hole, 1 degree from the ring around it.
        (5, 5, 100_000, set()),
        (5, 5, 112_000, {"T_A"}),
        # A circle that swallows a whole polygon still touches it.
        (25, 25, 3_000_000, {"T_A", "T_B"}),
        (25, 25, 0, {"T_B"}),
    ],
)
def test_radius_reaches_polygons_by_distance(
    layer: Path, lat: float, lon: float, radius_m: float, expected: set[str]
) -> None:
    assert resolve_area_codes([layer], lat=lat, lon=lon, radius_m=radius_m) == expected


def test_longitude_distance_shrinks_with_latitude(tmp_path: Path) -> None:
    square = [(0, 59), (0, 61), (1, 61), (1, 59), (0, 59)]
    path = _write(tmp_path / "high", [("T_H", [square])])
    # One degree of longitude at 60 degrees south is 55.6 km, not 111 km.
    assert resolve_area_codes([path], lat=60, lon=2, radius_m=50_000) == set()
    assert resolve_area_codes([path], lat=60, lon=2, radius_m=60_000) == {"T_H"}


def test_edge_crossing_the_circle_without_a_vertex_inside_counts(tmp_path: Path) -> None:
    long_thin = [(-50, 1), (-50, 1.1), (50, 1.1), (50, 1), (-50, 1)]
    path = _write(tmp_path / "thin", [("T_L", [long_thin])])
    assert resolve_area_codes([path], lat=0, lon=0, radius_m=100_000) == set()
    assert resolve_area_codes([path], lat=0, lon=0, radius_m=120_000) == {"T_L"}


def test_radius_is_added_to_every_layer(tmp_path: Path, layer: Path) -> None:
    second = _write(tmp_path / "second", [("T_C", [[(12, 0), (12, 3), (13, 3), (13, 0), (12, 0)]])])
    codes = resolve_area_codes([layer, second], lat=5, lon=11, radius_m=260_000)
    assert codes == {"T_A", "T_C"}


def test_negative_radius_is_rejected(layer: Path) -> None:
    with pytest.raises(ValueError, match="radius"):
        resolve_area_codes([layer], lat=2, lon=2, radius_m=-1)


ALL_LAYERS = ("IDM00001", "IDM00014", "IDM00017", "IDM00020", "IDM00007", "IDM00003")
SYDNEY_CBD = (-33.8688, 151.2093)


def _real_layers() -> list[Path]:
    base = Path(SPATIAL)  # type: ignore[arg-type]
    return [base / name / f"{name}.shp" for name in ALL_LAYERS]


@pytest.mark.skipif(not SPATIAL, reason="set BOM_SPATIAL_DIR to the unzipped BoM shapefiles")
def test_real_sydney_small_radius_equals_the_point_result() -> None:
    lat, lon = SYDNEY_CBD
    point = resolve_area_codes(_real_layers(), lat=lat, lon=lon)
    assert resolve_area_codes(_real_layers(), lat=lat, lon=lon, radius_m=100) == point
    assert "NSW_PW005" in point
    assert not any("_MW" in code for code in point)


@pytest.mark.skipif(not SPATIAL, reason="set BOM_SPATIAL_DIR to the unzipped BoM shapefiles")
@pytest.mark.parametrize(
    ("radius_m", "reaches", "misses"),
    [
        # The harbour is within 2 km of the CBD; the open coast is further out.
        (2_000, {"NSW_MW009"}, {"NSW_MW004"}),
        (12_000, {"NSW_MW009", "NSW_MW004"}, {"NSW_MW005"}),
        (50_000, {"NSW_MW009", "NSW_MW004", "NSW_MW003"}, {"NSW_MW008"}),
    ],
)
def test_real_sydney_radius_reaches_coastal_waters(
    radius_m: float, reaches: set[str], misses: set[str]
) -> None:
    lat, lon = SYDNEY_CBD
    codes = resolve_area_codes(_real_layers(), lat=lat, lon=lon, radius_m=radius_m)
    assert reaches <= codes
    assert not misses & codes


@pytest.mark.skipif(not SPATIAL, reason="set BOM_SPATIAL_DIR to the unzipped BoM shapefiles")
def test_real_worst_case_radius_stays_fast() -> None:
    """The cap radius in the least favourable place: huge polygons, so most edges are tested."""
    started = time.perf_counter()
    resolve_area_codes(_real_layers(), lat=-25.0, lon=135.0, radius_m=50_000)
    # Measured at about 0.6 s on a laptop; the bound only catches an accidental quadratic.
    assert time.perf_counter() - started < 5
