"""The per-location checklist of warning types, driven through Home Assistant (#37).

One toggle per warning type decides whether a type counts anywhere (the any-warning sensor, the
count, the most-severe sensor, the list, the event entity) and whether its own sensor exists.
Marine wind and surf are ordinary toggles; the location's stored area codes are never touched.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings import warning_types
from custom_components.bom_warnings.const import (
    CONF_AREA_CODES,
    CONF_HIDE_FINAL,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_STATE,
    CONF_WARNING_TYPES,
    DOMAIN,
    OTHER_WARNINGS,
)
from custom_components.bom_warnings.warning_types import WARNING_TYPES, label_of, sensor_types
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom

from .conftest import NOW
from .test_binary_sensor import ENTITY_ID as ANY_WARNING
from .test_binary_sensor import poll, setup_entry
from .test_options import layers, resolve, set_options  # noqa: F401
from .test_sensor import COUNT, MOST_SEVERE
from .test_zones import set_zone, zone_codes, zone_entry, zone_options  # noqa: F401

pytestmark = pytest.mark.freeze_time(NOW)

TYPE_KEYS = [t.key for t in sensor_types()]
MARINE_KEYS = ["marine_wind_warning", "hazardous_surf_warning"]
LAND_KEYS = [key for key in TYPE_KEYS if key not in MARINE_KEYS]
THUNDERSTORM = "sensor.home_thunderstorm_warning"


def events_listed(hass: HomeAssistant, entity_id: str = ANY_WARNING) -> set[str]:
    state = hass.states.get(entity_id)
    assert state is not None
    return {w["event"] for w in state.attributes["warnings"]}


async def test_the_options_form_is_one_checklist_and_the_hide_final_switch(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
) -> None:
    await setup_entry(hass, mock_config_entry)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    fields = {str(key) for key in result["data_schema"].schema}
    assert fields == {CONF_HIDE_FINAL, CONF_WARNING_TYPES}
    selector = next(
        value
        for key, value in result["data_schema"].schema.items()
        if str(key) == CONF_WARNING_TYPES
    )
    # One compact checkbox list rather than a row per switch.
    assert selector.config["mode"] == "list"
    assert selector.config["multiple"] is True
    assert selector.config["options"] == [
        {"value": key, "label": label_of(key)} for key in [*TYPE_KEYS, OTHER_WARNINGS]
    ]


async def test_a_new_entry_has_every_type_on_and_every_sensor_enabled(
    hass: HomeAssistant, fake_bom: FakeBom, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    registry = er.async_get(hass)
    for key in TYPE_KEYS:
        entity_id = f"sensor.home_{key}"
        entry = registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert entry.disabled_by is None
        assert hass.states.get(entity_id) is not None


@pytest.mark.parametrize("area_codes", [["QLD_ME008", "QLD_PW001"]])
async def test_turning_a_type_off_removes_it_everywhere_and_back_on_restores_it(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
) -> None:
    scenarios.apply("warning_appears", fake_bom.root)
    await setup_entry(hass, mock_config_entry)
    assert events_listed(hass) == {"Extreme Heat", "Thunderstorm"}
    assert hass.states.get(COUNT).state == "2"  # type: ignore[union-attr]
    assert hass.states.get(THUNDERSTORM).state == "unrated"  # type: ignore[union-attr]

    await set_options(hass, mock_config_entry, thunderstorm_warning=False)

    assert events_listed(hass) == {"Extreme Heat"}
    assert events_listed(hass, MOST_SEVERE) == {"Extreme Heat"}
    assert hass.states.get(COUNT).state == "1"  # type: ignore[union-attr]
    assert hass.states.get(ANY_WARNING).state == STATE_ON  # type: ignore[union-attr]
    registry = er.async_get(hass)
    assert registry.async_get(THUNDERSTORM) is None
    assert hass.states.get(THUNDERSTORM) is None
    # The other types keep their sensors.
    assert registry.async_get("sensor.home_extreme_heat_warning") is not None

    await set_options(hass, mock_config_entry, thunderstorm_warning=True)

    assert events_listed(hass) == {"Extreme Heat", "Thunderstorm"}
    assert registry.async_get(THUNDERSTORM) is not None
    assert hass.states.get(THUNDERSTORM).state == "unrated"  # type: ignore[union-attr]


@pytest.mark.parametrize("area_codes", [["QLD_ME008", "QLD_PW001"]])
async def test_every_type_off_leaves_nothing_counted(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
) -> None:
    scenarios.apply("warning_appears", fake_bom.root)
    await setup_entry(hass, mock_config_entry)

    await set_options(
        hass, mock_config_entry, **{key: False for key in [*TYPE_KEYS, OTHER_WARNINGS]}
    )

    assert hass.states.get(ANY_WARNING).state == STATE_OFF  # type: ignore[union-attr]
    assert hass.states.get(COUNT).state == "0"  # type: ignore[union-attr]
    registry = er.async_get(hass)
    remaining = [
        entity.entity_id
        for entity in registry.entities.values()
        if any((entity.unique_id or "").endswith(f"_{key}") for key in TYPE_KEYS)
    ]
    assert remaining == []


@pytest.mark.parametrize("area_codes", [["QLD_ME008", "QLD_PW001"]])
async def test_a_type_that_is_off_raises_no_event(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    freezer: Any,
) -> None:
    await setup_entry(hass, mock_config_entry)
    await set_options(hass, mock_config_entry, thunderstorm_warning=False)

    scenarios.apply("warning_appears", fake_bom.root)
    await poll(hass, freezer)

    event = hass.states.get("event.home_warning_event")
    assert event is not None
    assert event.attributes.get("event") == "Extreme Heat"


@pytest.mark.parametrize("zone_codes", [["NT_PW999", "NT_MW004"]])
async def test_marine_wind_is_a_toggle_and_never_re_resolves(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    zone_entry: MockConfigEntry,  # noqa: F811
    layers: MagicMock,  # noqa: F811
    resolve: MagicMock,  # noqa: F811
) -> None:
    scenarios.apply("all_types", fake_bom.root)
    set_zone(hass)
    await setup_entry(hass, zone_entry)
    wind = "sensor.holiday_house_marine_wind_warning"
    assert hass.states.get(wind).state == "severe"  # type: ignore[union-attr]
    assert "Wind" in events_listed(hass, "binary_sensor.holiday_house_warning")

    await set_options(hass, zone_entry, marine_wind_warning=False)

    assert er.async_get(hass).async_get(wind) is None
    assert "Wind" not in events_listed(hass, "binary_sensor.holiday_house_warning")
    resolve.assert_not_called()
    # The stored area codes still include the water zone, so turning it back on needs no lookup.
    assert zone_entry.data[CONF_AREA_CODES] == ["NT_PW999", "NT_MW004"]

    await set_options(hass, zone_entry, marine_wind_warning=True)

    assert hass.states.get(wind).state == "severe"  # type: ignore[union-attr]
    resolve.assert_not_called()


@pytest.mark.parametrize("area_codes", [["NSW_PW999", "NSW_MW008"]])
async def test_other_warnings_covers_a_type_with_no_row(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    mock_config_entry: MockConfigEntry,
    layers: MagicMock,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Surf stands in for a type BoM adds later: it has no row, so the Other toggle governs it."""
    without_surf = tuple(t for t in WARNING_TYPES if t.event != "Large Coastal Surf")
    monkeypatch.setattr(warning_types, "WARNING_TYPES", without_surf)
    scenarios.apply("all_types", fake_bom.root)
    await setup_entry(hass, mock_config_entry)
    assert "Large Coastal Surf" in events_listed(hass)

    await set_options(hass, mock_config_entry, **{OTHER_WARNINGS: False})

    assert "Large Coastal Surf" not in events_listed(hass)
    assert hass.states.get(COUNT).state == "0"  # type: ignore[union-attr]

    await set_options(hass, mock_config_entry, **{OTHER_WARNINGS: True})

    assert "Large Coastal Surf" in events_listed(hass)


@pytest.mark.parametrize(
    ("old", "kept"),
    [
        pytest.param({}, LAND_KEYS + [OTHER_WARNINGS], id="no-options-marine-stays-off"),
        pytest.param({"include_marine": False}, LAND_KEYS + [OTHER_WARNINGS], id="marine-off"),
        pytest.param({"include_marine": True}, TYPE_KEYS + [OTHER_WARNINGS], id="marine-on"),
        pytest.param({"event_types": []}, LAND_KEYS + [OTHER_WARNINGS], id="empty-filter"),
        pytest.param(
            {"event_types": ["Frost", "Thunderstorm"]},
            ["frost_warning", "thunderstorm_warning"],
            id="named-types",
        ),
        pytest.param({"event_types": ["Wind"]}, [], id="marine-name-but-marine-off"),
        pytest.param(
            {"event_types": ["Wind"], "include_marine": True},
            ["marine_wind_warning"],
            id="marine-name-and-marine-on",
        ),
        pytest.param({"event_types": ["Tsunami"]}, [OTHER_WARNINGS], id="type-with-no-row"),
        pytest.param(
            {"event_types": ["Frost", "Tsunami", "Wind"], "include_marine": True},
            ["frost_warning", "marine_wind_warning", OTHER_WARNINGS],
            id="mixed",
        ),
    ],
)
async def test_an_entry_from_before_the_checklist_is_migrated(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    layers: MagicMock,  # noqa: F811
    old: dict[str, Any],
    kept: list[str],
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="-27.470,153.021",
        title="Home",
        options={CONF_HIDE_FINAL: False, **old},
        data={
            CONF_LATITUDE: -27.47,
            CONF_LONGITUDE: 153.021,
            CONF_STATE: "QLD",
            CONF_AREA_CODES: ["QLD_PW001"],
        },
    )

    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 3
    assert set(entry.options[CONF_WARNING_TYPES]) == set(kept)
    assert entry.options[CONF_HIDE_FINAL] is False
    assert "event_types" not in entry.options
    assert "include_marine" not in entry.options


async def test_an_entry_with_no_options_at_all_is_migrated(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    layers: MagicMock,  # noqa: F811
) -> None:
    """Entries created before coastal waters existed stored no options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="-27.470,153.021",
        title="Home",
        data={
            CONF_LATITUDE: -27.47,
            CONF_LONGITUDE: 153.021,
            CONF_STATE: "QLD",
            CONF_AREA_CODES: ["QLD_PW001"],
        },
    )

    await setup_entry(hass, entry)

    assert set(entry.options[CONF_WARNING_TYPES]) == set(LAND_KEYS + [OTHER_WARNINGS])


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize(
    ("old", "thunderstorm_after", "frost_after"),
    [
        pytest.param({}, True, True, id="every-type-on"),
        pytest.param({"event_types": ["Frost"]}, False, True, id="only-frost"),
    ],
)
async def test_the_old_binary_type_sensors_are_removed_and_replaced_by_level_sensors(
    hass: HomeAssistant,
    fake_bom: FakeBom,
    layers: MagicMock,  # noqa: F811
    version: int,
    old: dict[str, Any],
    thunderstorm_after: bool,
    frost_after: bool,
) -> None:
    """The type sensors used to be binary sensors, so nothing may be left orphaned."""
    options: dict[str, Any] = old
    if version == 2:
        options = {CONF_WARNING_TYPES: ["frost_warning"] if "event_types" in old else TYPE_KEYS}
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=version,
        unique_id="-27.470,153.021",
        title="Home",
        options=options,
        data={
            CONF_LATITUDE: -27.47,
            CONF_LONGITUDE: 153.021,
            CONF_STATE: "QLD",
            CONF_AREA_CODES: ["QLD_PW001"],
        },
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for key, disabled_by in (
        ("thunderstorm_warning", er.RegistryEntryDisabler.INTEGRATION),
        ("frost_warning", None),
        ("marine_wind_warning", er.RegistryEntryDisabler.USER),
    ):
        registry.async_get_or_create(
            "binary_sensor",
            DOMAIN,
            f"-27.470,153.021_{key}",
            config_entry=entry,
            disabled_by=disabled_by,
            suggested_object_id=f"home_{key}",
        )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 3
    old_binaries = [
        e.entity_id
        for e in registry.entities.values()
        if e.domain == "binary_sensor" and e.entity_id != ANY_WARNING
    ]
    assert old_binaries == []
    assert (registry.async_get(THUNDERSTORM) is not None) is thunderstorm_after
    assert (registry.async_get("sensor.home_frost_warning") is not None) is frost_after
    if thunderstorm_after:
        thunderstorm = registry.async_get(THUNDERSTORM)
        assert thunderstorm is not None and thunderstorm.disabled_by is None
        assert hass.states.get(THUNDERSTORM) is not None


async def test_the_zone_step_no_longer_asks_about_coastal_waters(
    hass: HomeAssistant,
    resolve: MagicMock,  # noqa: F811
) -> None:
    from homeassistant.config_entries import SOURCE_USER

    set_zone(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "zone"}
    )

    assert {str(key) for key in result["data_schema"].schema} == {"zone"}


def test_every_choice_on_the_checklist_has_a_plain_english_label() -> None:
    """The list shows these words, so none may be a computer identifier."""
    keys = [*TYPE_KEYS, OTHER_WARNINGS]
    labels = [label_of(key) for key in keys]
    assert len(set(labels)) == len(labels)
    for key, label in zip(keys, labels, strict=True):
        assert label != key
        assert "_" not in label
        assert label[0].isupper()
