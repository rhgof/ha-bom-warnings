"""The marine wind summary, end to end: the real NSW product `IDN20400` through the fake BoM server.

Its CAP file has no description, so the summary of each block comes from the product XML beside it.
The reader's own rules are in `test_product_xml.py`; this checks the whole path to the entities.
"""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.bom_warnings.ftp import BomFtp, BomFtpError
from custom_components.bom_warnings.shared_feed import FEED
from scripts.fake_bom import layout
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import setup_entry
from .test_reliability import repair_issues
from .test_warning_types import entry_at

pytestmark = pytest.mark.freeze_time(NOW)

MARINE_WIND = "sensor.home_marine_wind_warning"
COUNT = "sensor.home_warning_count"
MOST_SEVERE = "sensor.home_most_severe_warning"
STRONG = (
    "Strong Wind Warning for Coffs Coast, Macquarie Coast, Hunter Coast, Sydney Coast, "
    "Illawarra Coast and Batemans Coast"
)
GALE = "Gale Warning for Eden Coast"


@pytest.mark.parametrize(
    ("code", "summary"),
    [("NSW_MW004", STRONG), ("NSW_MW001", GALE)],
    ids=["sydney-coast", "eden-coast"],
)
async def test_a_coast_gets_the_summary_of_the_hazard_that_covers_it(
    hass: HomeAssistant, fake_bom: FakeBom, code: str, summary: str
) -> None:
    layout.put_captured_product(fake_bom.root, "IDN20400")

    await setup_entry(hass, entry_at(code))

    for entity_id in (MARINE_WIND, MOST_SEVERE):
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.attributes["summary"] == summary, entity_id
    for entity_id in (MARINE_WIND, COUNT, MOST_SEVERE):
        state = hass.states.get(entity_id)
        assert state is not None
        assert [w["summary"] for w in state.attributes["warnings"]] == [summary], entity_id


async def test_without_the_xml_the_warning_is_still_there_with_no_summary(
    hass: HomeAssistant, fake_bom: FakeBom
) -> None:
    layout.put_captured_product(fake_bom.root, "IDN20400", with_xml=False)

    await setup_entry(hass, entry_at("NSW_MW004"))

    state = hass.states.get(MARINE_WIND)
    assert state is not None
    assert state.state == "moderate"
    assert len(state.attributes["warnings"]) == 1
    assert "summary" not in state.attributes
    assert "summary" not in state.attributes["warnings"][0]
    assert hass.data[FEED].consecutive_failures == 0
    assert repair_issues(hass) == []


async def test_a_failing_xml_fetch_leaves_the_summary_out_and_the_refresh_healthy(
    hass: HomeAssistant, fake_bom: FakeBom, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout.put_captured_product(fake_bom.root, "IDN20400")
    fetch = BomFtp.fetch

    def failing_fetch(self: BomFtp, name: str) -> bytes | None:
        if name == "IDN20400.xml":
            raise BomFtpError("transfer stalled")
        return fetch(self, name)

    monkeypatch.setattr(BomFtp, "fetch", failing_fetch)

    await setup_entry(hass, entry_at("NSW_MW004"))

    state = hass.states.get(MARINE_WIND)
    assert state is not None
    assert state.state == "moderate"
    assert "summary" not in state.attributes
    assert hass.data[FEED].consecutive_failures == 0
    assert repair_issues(hass) == []
