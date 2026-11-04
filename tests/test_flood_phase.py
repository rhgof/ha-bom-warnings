"""A final flood warning, identified from the product XML's phase.

CAP gives a final flood warning severity `Unknown` and a headline with no "Final", so it looked like
any other current warning. The product XML says `phase="FIN"` for it (8 of the 16 captured flood
products), so a block whose hazard is final is marked final and hide-final applies to it. The CAP
headline rule stays as the fallback (`Phase.FINAL` from a "Final" headline is untouched).
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

from custom_components.bom_warnings.cap import CapWarning, Phase, parse_cap
from custom_components.bom_warnings.const import CONF_HIDE_FINAL
from custom_components.bom_warnings.ftp import BomFtpError
from custom_components.bom_warnings.product_xml import ProductSummaryReader
from scripts.fake_bom import layout
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .fake_ftp import FakeFtp
from .test_binary_sensor import ENTITY_ID as WARNING_BINARY_SENSOR
from .test_binary_sensor import setup_entry
from .test_warning_types import entry_at

pytestmark = pytest.mark.freeze_time(NOW)

FLOOD = "sensor.home_flood_warning"
COUNT = "sensor.home_warning_count"
CAPTURES = Path(__file__).parent / "fixtures" / "products" / "2026-11-03T2348Z"
READ_AT = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)

FINAL = [
    "IDQ20770",
    "IDQ20790",
    "IDQ20800",
    "IDQ20815",
    "IDQ20827",
    "IDQ20835",
    "IDQ20840",
    "IDQ20850",
]
UPDATING = [
    "IDQ20809",
    "IDQ20829",
    "IDQ20831",
    "IDQ20845",
    "IDQ20855",
    "IDQ20860",
    "IDN36631",
    "IDN36632",
]


def cap(product: str) -> CapWarning:
    warning = parse_cap((CAPTURES / f"{product}.cap.xml").read_bytes())
    assert warning is not None
    return warning


def xml(product: str) -> bytes:
    return (CAPTURES / f"{product}.xml").read_bytes()


def read(product: str, data: bytes | None = None) -> CapWarning:
    fake = FakeFtp({f"{product}.xml": data if data is not None else xml(product)})
    (warning,) = ProductSummaryReader(fake).enrich([cap(product)], READ_AT)
    return warning


@pytest.mark.parametrize("product", FINAL)
def test_a_flood_product_whose_xml_says_fin_is_final_in_every_block(product: str) -> None:
    assert all(info.phase is not Phase.FINAL for info in cap(product).infos)

    warning = read(product)

    assert all(info.phase is Phase.FINAL for info in warning.infos)


@pytest.mark.parametrize("product", UPDATING)
def test_a_flood_product_still_updating_is_left_as_it_was(product: str) -> None:
    assert read(product) == cap(product)


def test_each_block_takes_the_phase_of_its_own_hazard() -> None:
    mixed = xml("IDQ20770").replace(b'phase="FIN" type="FLW"', b'phase="UPD" type="FLW"', 1)

    warning = read("IDQ20770", mixed)

    assert sorted(info.phase is Phase.FINAL for info in warning.infos) == [False, True, True]


def test_the_xml_is_read_once_per_issue_even_for_a_block_that_has_a_description() -> None:
    fake = FakeFtp({"IDQ20835.xml": xml("IDQ20835")})
    reader = ProductSummaryReader(fake)

    reader.enrich([cap("IDQ20835")], READ_AT)
    reader.enrich([cap("IDQ20835")], READ_AT)

    assert (fake.listings, fake.fetches) == (["IDQ20835.xml"], ["IDQ20835.xml"])


def test_a_failed_read_leaves_the_flood_warning_as_the_cap_file_says() -> None:
    fake = FakeFtp({"IDQ20835.xml": xml("IDQ20835")})
    fake.fetch_error = BomFtpError("stalled")

    (warning,) = ProductSummaryReader(fake).enrich([cap("IDQ20835")], READ_AT)

    assert warning == cap("IDQ20835")


def test_a_flood_product_with_no_xml_stays_current_and_is_not_asked_for_again() -> None:
    fake = FakeFtp({})
    reader = ProductSummaryReader(fake)

    (first,) = reader.enrich([cap("IDQ20835")], READ_AT)
    reader.enrich([cap("IDQ20835")], READ_AT)

    assert first == cap("IDQ20835")
    assert fake.listings == ["IDQ20835.xml"]


async def test_a_final_flood_warning_is_hidden_by_default(
    hass: HomeAssistant, fake_bom: FakeBom
) -> None:
    layout.put_captured_product(fake_bom.root, "IDQ20835")

    await setup_entry(hass, entry_at("QLD_RC115"))

    assert hass.states.get(FLOOD).state == "none"  # type: ignore[union-attr]
    assert hass.states.get(WARNING_BINARY_SENSOR).state == "off"  # type: ignore[union-attr]
    assert hass.states.get(COUNT).state == "0"  # type: ignore[union-attr]


async def test_a_final_flood_warning_is_listed_as_final_when_ended_warnings_are_kept(
    hass: HomeAssistant, fake_bom: FakeBom
) -> None:
    layout.put_captured_product(fake_bom.root, "IDQ20835")
    entry = entry_at("QLD_RC115")
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_HIDE_FINAL: False})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(FLOOD)

    assert state is not None
    assert state.state == "none"
    assert [(w["product_id"], w["phase"]) for w in state.attributes["warnings"]] == [
        ("IDQ20835", "final")
    ]


async def test_without_the_xml_the_same_warning_still_looks_current(
    hass: HomeAssistant, fake_bom: FakeBom
) -> None:
    layout.put_captured_product(fake_bom.root, "IDQ20835", with_xml=False)

    await setup_entry(hass, entry_at("QLD_RC115"))

    assert hass.states.get(FLOOD).state != "none"  # type: ignore[union-attr]
    assert hass.states.get(WARNING_BINARY_SENSOR).state == "on"  # type: ignore[union-attr]


async def test_an_updating_flood_warning_is_unchanged(
    hass: HomeAssistant, fake_bom: FakeBom
) -> None:
    layout.put_captured_product(fake_bom.root, "IDQ20829")

    await setup_entry(hass, entry_at("QLD_RC170"))

    assert hass.states.get(FLOOD).state != "none"  # type: ignore[union-attr]
    assert hass.states.get(WARNING_BINARY_SENSOR).state == "on"  # type: ignore[union-attr]
