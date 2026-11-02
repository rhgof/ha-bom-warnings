"""Matching an entry's stored area codes to a fire district, by exact code."""

import os
import warnings
from pathlib import Path

import pytest
import shapefile

from custom_components.bom_warnings.areas import resolve_area_codes
from custom_components.bom_warnings.fire_danger import (
    PRODUCTS,
    FireDangerProduct,
    match_district,
    parse_fire_danger,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fire_danger"
SPATIAL = os.environ.get("BOM_SPATIAL_DIR")
needs_shapefiles = pytest.mark.skipif(
    not SPATIAL, reason="set BOM_SPATIAL_DIR to the unzipped BoM shapefiles"
)


def load(product_id: str) -> FireDangerProduct:
    product = parse_fire_danger((FIXTURES / f"{product_id}.xml").read_bytes())
    assert product is not None
    return product


@pytest.mark.parametrize(
    ("codes", "district"),
    [
        (["NSW_FW004"], "Greater Sydney Region"),
        (["NSW_PW005", "NSW_ME001", "NSW_FW004", "NSW_FL068"], "Greater Sydney Region"),
        (["NSW_FW008"], "The Australian Capital Territory"),
    ],
)
def test_a_stored_fire_weather_code_selects_its_district(codes: list[str], district: str) -> None:
    match = match_district({"IDN10016": load("IDN10016")}, codes)

    assert match is not None
    assert match[1].name == district


@pytest.mark.parametrize(
    "codes",
    [[], ["NSW_PW005", "NSW_ME001"], ["NSW_FW099"], ["QLD_FW002"], ["Greater Sydney Region"]],
)
def test_no_matching_code_gives_nothing(codes: list[str]) -> None:
    assert match_district({"IDN10016": load("IDN10016")}, codes) is None


def test_the_code_is_found_in_whichever_product_holds_it() -> None:
    products = {"IDN10016": load("IDN10016"), "IDQ13016": load("IDQ13016")}

    match = match_district(products, ["QLD_FW002"])

    assert match is not None
    assert (match[0].product_id, match[1].name) == ("IDQ13016", "Gulf Country")


@needs_shapefiles
def test_central_sydney_resolves_to_the_greater_sydney_district_in_the_product() -> None:
    layer = Path(str(SPATIAL)) / "IDM00007" / "IDM00007.shp"
    codes = resolve_area_codes([layer], lat=-33.8688, lon=151.2093)

    assert codes == {"NSW_FW004"}
    match = match_district({"IDN10016": load("IDN10016")}, codes)
    assert match is not None
    assert match[1].name == "Greater Sydney Region"


@needs_shapefiles
@pytest.mark.parametrize("product_id", sorted(PRODUCTS.values()))
def test_every_district_in_a_product_is_a_code_of_the_fire_weather_layer(product_id: str) -> None:
    layer = Path(str(SPATIAL)) / "IDM00007" / "IDM00007.shp"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        reader = shapefile.Reader(str(layer), encoding="cp1252", encodingErrors="replace")
    with reader:
        index = [f[0] for f in reader.fields[1:]].index("AAC")
        layer_codes = {str(record[index]) for record in reader.iterRecords()}

    assert set(load(product_id).districts) <= layer_codes
