"""A thunderstorm warning end to end: real captured files, the fake BoM server, the entity.

The pieces are tested alone in `test_product_text.py`, `test_product_text_reader.py` and
`test_thunderstorm_attributes.py`; this checks they are joined up.
"""

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.const import (
    CONF_AREA_CODES,
    CONF_AREA_NAMES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_STATE,
    DOMAIN,
)
from scripts.fake_bom import layout
from scripts.fake_bom.server import FakeBom

from .test_binary_sensor import setup_entry

SNAPSHOT = Path(__file__).parent / "fixtures" / "products" / "2026-11-15T0343Z-thunderstorm"
THUNDERSTORM = "sensor.home_thunderstorm_warning"

pytestmark = pytest.mark.freeze_time("2026-11-15 03:50:00+00:00")


def entry_named(code: str, name: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=4,
        unique_id="-32.9,151.7",
        title="Home",
        data={
            CONF_LATITUDE: -32.9,
            CONF_LONGITUDE: 151.7,
            CONF_STATE: "NSW",
            CONF_AREA_CODES: [code],
            CONF_AREA_NAMES: {code: name},
        },
    )


@pytest.mark.parametrize(
    ("code", "name", "very_dangerous"),
    [("NSW_PW003", "Hunter", None), ("NSW_PW002", "Mid North Coast", True)],
    ids=["hunter", "mid-north-coast"],
)
async def test_a_broad_warning_reaches_the_sensor_with_its_text_facts(
    hass: HomeAssistant, fake_bom: FakeBom, code: str, name: str, very_dangerous: bool | None
) -> None:
    layout.put_captured_product(
        fake_bom.root, "IDN21033", with_text=True, with_xml=False, source=SNAPSHOT
    )

    await setup_entry(hass, entry_named(code, name))

    state = hass.states.get(THUNDERSTORM)
    assert state is not None
    assert state.state == "severe"
    assert state.attributes["hazards"] == ["wind", "hail"]
    assert state.attributes["hazard"] == "Large, possibly giant hailstones and damaging winds"
    assert state.attributes["next_issue"] == "2026-11-15T06:40:00+00:00"
    assert state.attributes["current"] == 1
    assert "detailed" not in state.attributes
    assert state.attributes.get("very_dangerous") is very_dangerous


async def test_a_detailed_warning_is_marked_and_keeps_its_whole_forecast_sentence(
    hass: HomeAssistant, fake_bom: FakeBom
) -> None:
    layout.put_captured_product(
        fake_bom.root, "IDN21035", with_text=True, with_xml=True, source=SNAPSHOT
    )

    await setup_entry(hass, entry_named("NSW_ME015", "Greater Newcastle"))

    state = hass.states.get(THUNDERSTORM)
    assert state is not None
    assert state.attributes["detailed"] is True
    assert state.attributes["next_issue"] == "2026-11-15T04:10:00+00:00"
    assert state.attributes["summary"].endswith("Hexham by 3:10 pm.")
