"""The one table of warning types, and the views derived from it, without Home Assistant."""

import pytest

from custom_components.bom_warnings import warning_types
from custom_components.bom_warnings.const import OTHER_WARNINGS
from custom_components.bom_warnings.warning_types import (
    WARNING_TYPES,
    event_is_on,
    key_of,
    label_of,
    sensor_types,
    type_keys,
)

# Today's rows, in the order the options checklist lists them and the sensors are created.
ROWS = [
    ("Thunderstorm", "thunderstorm_warning", "Thunderstorm"),
    ("Fire Weather", "fire_weather_warning", "Fire weather"),
    ("Extreme Heat", "extreme_heat_warning", "Extreme heat"),
    ("Frost", "frost_warning", "Frost"),
    ("Hazardous Road Conditions", "hazardous_road_conditions_warning", "Hazardous road conditions"),
    ("Riverine Flood", "flood_warning", "Flood"),
    ("Sheep Grazier Warning", "sheep_grazier_warning", "Sheep grazier"),
    ("Exposure", "exposure_warning", "Exposure"),
    ("Tropical Cyclone", "tropical_cyclone_warning", "Tropical cyclone"),
    ("Weather", "severe_weather_warning", "Severe weather"),
    ("Wind", "marine_wind_warning", "Marine wind"),
    ("Large Coastal Surf", "hazardous_surf_warning", "Hazardous surf"),
]


def test_the_sensor_types_are_these_rows_in_this_order() -> None:
    assert [(t.event, t.key, t.label) for t in sensor_types()] == ROWS


def test_every_event_and_key_is_unique() -> None:
    events = [t.event for t in WARNING_TYPES]
    keys = [t.key for t in WARNING_TYPES]
    assert len(set(events)) == len(events)
    assert len(set(keys)) == len(keys)


def test_the_checklist_is_the_sensor_keys_then_other_warnings() -> None:
    assert type_keys() == (*(key for _, key, _ in ROWS), OTHER_WARNINGS)
    assert type_keys()[-1] == OTHER_WARNINGS


@pytest.mark.parametrize(("event", "key", "label"), ROWS)
def test_every_key_has_its_label(event: str, key: str, label: str) -> None:
    assert label_of(key) == label


def test_other_warnings_has_a_label_too() -> None:
    assert label_of(OTHER_WARNINGS) == "Other warnings"


def test_a_key_with_no_row_has_no_label() -> None:
    with pytest.raises(KeyError):
        label_of("no_such_type")


def test_only_wind_and_large_coastal_surf_are_marine() -> None:
    assert {t.event for t in WARNING_TYPES if t.marine} == {"Wind", "Large Coastal Surf"}


@pytest.mark.parametrize(
    ("event", "key"),
    [
        pytest.param("Thunderstorm", "thunderstorm_warning", id="a-row"),
        pytest.param("Weather", "severe_weather_warning", id="named-differently-from-its-event"),
        pytest.param("Tsunami", OTHER_WARNINGS, id="no-row-yet"),
        pytest.param("A Type BoM Adds Later", OTHER_WARNINGS, id="never-seen"),
    ],
)
def test_an_event_belongs_to_its_row_or_to_other_warnings(event: str, key: str) -> None:
    assert key_of(event) == key


@pytest.mark.parametrize(
    ("event", "enabled", "on"),
    [
        pytest.param("Thunderstorm", frozenset({"thunderstorm_warning"}), True, id="row-on"),
        pytest.param("Thunderstorm", frozenset(), False, id="row-off"),
        pytest.param(
            "Thunderstorm", frozenset({OTHER_WARNINGS}), False, id="other-does-not-cover-a-row"
        ),
        pytest.param("Tsunami", frozenset({OTHER_WARNINGS}), True, id="other-on"),
        pytest.param("Tsunami", frozenset({"thunderstorm_warning"}), False, id="other-off"),
    ],
)
def test_an_event_is_on_when_its_toggle_is(event: str, enabled: frozenset[str], on: bool) -> None:
    assert event_is_on(event, enabled) is on


def test_patching_the_one_table_changes_every_derived_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This is how a test makes a type disappear, as if BoM had added it after this code shipped.
    without_surf = tuple(t for t in WARNING_TYPES if t.event != "Large Coastal Surf")
    monkeypatch.setattr(warning_types, "WARNING_TYPES", without_surf)

    assert len(sensor_types()) == 11
    assert "hazardous_surf_warning" not in type_keys()
    assert key_of("Large Coastal Surf") == OTHER_WARNINGS
    assert event_is_on("Large Coastal Surf", frozenset({OTHER_WARNINGS}))
    with pytest.raises(KeyError):
        label_of("hazardous_surf_warning")
