"""A zone's radius and the areas it shows, with nothing patched.

The fake BoM server serves generated shapefile layers, so the real resolver runs over a real socket
and the names come from the layers' `DIST_NAME` field. The `resolve` fixture used elsewhere is the
seam for tests that only care what a point resolves to; this one checks the seam is honest.
"""

import io
import zipfile
from pathlib import Path

import pytest
import shapefile
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    CONF_AREA_CODES,
    CONF_AREA_NAMES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_STATE,
    CONF_ZONE,
    DOMAIN,
)
from custom_components.bom_warnings.spatial import LAYERS
from scripts.fake_bom.layout import SPATIAL
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import setup_entry
from .test_sensor import state_of
from .test_zones import SENSOR, ZONE, change_zone, set_zone

pytestmark = pytest.mark.freeze_time(NOW)

HOME_SQUARE = [
    (152.90, -27.60),
    (152.90, -27.30),
    (153.10, -27.30),
    (153.10, -27.60),
    (152.90, -27.60),
]
NEIGHBOUR = [
    (153.15, -27.60),
    (153.15, -27.30),
    (153.30, -27.30),
    (153.30, -27.60),
    (153.15, -27.60),
]
FAR = [(100.0, -10.0), (100.0, -9.0), (101.0, -9.0), (101.0, -10.0), (100.0, -10.0)]


def layer_zip(tmp: Path, layer: str, areas: list[tuple[str, str, list]]) -> bytes:
    stem = tmp / layer
    with shapefile.Writer(str(stem)) as w:
        w.field("AAC", "C", size=20)
        w.field("DIST_NAME", "C", size=60)
        for code, name, ring in areas:
            w.poly([ring])
            w.record(code, name)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for suffix in (".shp", ".shx", ".dbf"):
            archive.write(stem.with_suffix(suffix), f"{layer}{suffix}")
    return buffer.getvalue()


async def test_growing_a_zone_over_a_second_district_shows_it_and_shrinking_drops_it(
    hass: HomeAssistant, fake_bom: FakeBom, tmp_path: Path
) -> None:
    served = fake_bom.root / SPATIAL
    served.mkdir(parents=True, exist_ok=True)
    build = tmp_path / "layers"
    build.mkdir()
    for layer in LAYERS:
        areas = [("XXX_FAR", f"{layer} far", FAR)]
        if layer == "IDM00001":
            areas = [
                ("QLD_PW001", "Moreton Bay", HOME_SQUARE),
                ("QLD_ME008", "Brisbane", NEIGHBOUR),
            ]
        (served / f"{layer}.zip").write_bytes(layer_zip(build, layer, areas))

    # Stored without names, as an older version did, so setup also looks the first name up.
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        unique_id=ZONE,
        title="Holiday house",
        data={
            CONF_ZONE: ZONE,
            CONF_LATITUDE: -27.47,
            CONF_LONGITUDE: 153.021,
            CONF_RADIUS: 2000.0,
            CONF_STATE: "QLD",
            CONF_AREA_CODES: ["QLD_PW001"],
        },
    )
    count = "sensor.holiday_house_warning_count"
    set_zone(hass, radius=2000.0)
    await setup_entry(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[CONF_AREA_NAMES] == {"QLD_PW001": "Moreton Bay"}
    assert state_of(hass, count).attributes["areas"] == ["Moreton Bay"]
    assert hass.states.get(SENSOR).state == STATE_OFF

    await change_zone(hass, radius=15_000.0)
    attrs = state_of(hass, count).attributes
    assert attrs["areas"] == ["Brisbane", "Moreton Bay"]
    assert [w["area"] for w in attrs["warnings"]] == ["Brisbane"]
    assert hass.states.get(SENSOR).state == STATE_ON

    await change_zone(hass, radius=2_000.0)
    attrs = state_of(hass, count).attributes
    assert attrs["areas"] == ["Moreton Bay"]
    assert attrs["warnings"] == []
    assert hass.states.get(SENSOR).state == STATE_OFF
