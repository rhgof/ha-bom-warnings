"""Remembered fire danger ratings in Home Assistant's storage."""

from datetime import date
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bom_warnings.fire_danger import FireDangerPeriod, FireMemory
from custom_components.bom_warnings.fire_store import FireStore

MEMORY = FireMemory(
    "NSW_FW008",
    (
        FireDangerPeriod(date(2026, 11, 2), "moderate", 12),
        FireDangerPeriod(date(2026, 11, 3), "high", None),
    ),
)
# What earlier releases wrote, which must keep loading and keep being written.
STORED = {
    "district": "NSW_FW008",
    "periods": [
        {"date": "2026-11-02", "level": "moderate", "fire_behaviour_index": 12},
        {"date": "2026-11-03", "level": "high", "fire_behaviour_index": None},
    ],
}


def storage_key(entry: MockConfigEntry) -> str:
    return f"bom_warnings.fire_danger.{entry.entry_id}"


def seed(hass_storage: dict[str, Any], entry: MockConfigEntry, data: object) -> None:
    key = storage_key(entry)
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": data}


async def test_nothing_stored_loads_nothing(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    assert await FireStore(hass, mock_config_entry).async_load() is None


async def test_a_saved_memory_loads_back(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    await FireStore(hass, mock_config_entry).async_save(MEMORY)
    assert await FireStore(hass, mock_config_entry).async_load() == MEMORY


async def test_it_keeps_the_key_version_and_shape_earlier_releases_used(
    hass: HomeAssistant, hass_storage: dict[str, Any], mock_config_entry: MockConfigEntry
) -> None:
    await FireStore(hass, mock_config_entry).async_save(MEMORY)
    stored = hass_storage[storage_key(mock_config_entry)]
    assert stored["version"] == 1
    assert stored["data"] == STORED


async def test_data_written_by_an_earlier_release_loads(
    hass: HomeAssistant, hass_storage: dict[str, Any], mock_config_entry: MockConfigEntry
) -> None:
    seed(hass_storage, mock_config_entry, STORED)
    assert await FireStore(hass, mock_config_entry).async_load() == MEMORY


@pytest.mark.parametrize(
    "damaged",
    [
        pytest.param("not a dict", id="wrong-type"),
        pytest.param({"district": "NSW_FW008"}, id="no-periods"),
        pytest.param({"district": "NSW_FW008", "periods": 5}, id="periods-not-a-list"),
        pytest.param(
            {
                "district": "x",
                "periods": [{"date": "?", "level": "high", "fire_behaviour_index": 1}],
            },
            id="bad-date",
        ),
    ],
)
async def test_damaged_data_is_ignored_not_raised(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    damaged: object,
) -> None:
    seed(hass_storage, mock_config_entry, damaged)
    assert await FireStore(hass, mock_config_entry).async_load() is None


async def test_removing_deletes_what_was_stored(
    hass: HomeAssistant, hass_storage: dict[str, Any], mock_config_entry: MockConfigEntry
) -> None:
    store = FireStore(hass, mock_config_entry)
    await store.async_save(MEMORY)
    assert storage_key(mock_config_entry) in hass_storage

    await FireStore(hass, mock_config_entry).async_remove()

    assert storage_key(mock_config_entry) not in hass_storage
