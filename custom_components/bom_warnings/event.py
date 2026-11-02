"""Event entity: fires when a warning appears, is updated, becomes final or is cancelled.

Decision: an Event entity rather than bus events. Home Assistant's guidance is to model
momentary occurrences as `event` entities: they show up in the UI and logbook, have a stable
entity id, can be used in the automation editor (state and device triggers) and are covered by
the entity registry, whereas a custom bus event needs hand-written YAML and is invisible to
users. Bus events remain right for integration-wide signals with no natural entity, which this
is not: every transition belongs to one location.

Transitions are found by diffing the coordinator's per-product states against the previous
refresh, so a warning that is unchanged fires nothing. The baseline is taken when the entity is
added, so warnings already present at startup or reload fire no "new" event.
"""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BomWarningsConfigEntry
from .cap import Phase
from .const import DOMAIN
from .coordinator import BomWarningsCoordinator, WarningState

PARALLEL_UPDATES = 0

EVENT_NEW = "new"
EVENT_UPDATE = "update"
EVENT_FINAL = "final"
EVENT_CANCELLED = "cancelled"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BomWarningsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([WarningEvent(entry.runtime_data.coordinator, entry)])


def _transition(previous: WarningState | None, current: WarningState) -> str | None:
    """The event type for one product between two refreshes, or None if nothing happened."""
    if previous == current:
        return None
    if current.phase is Phase.CANCELLED:
        return EVENT_CANCELLED
    if current.phase is Phase.FINAL:
        return EVENT_FINAL
    return EVENT_NEW if previous is None else EVENT_UPDATE


class WarningEvent(CoordinatorEntity[BomWarningsCoordinator], EventEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "warning_event"
    _attr_event_types = [EVENT_NEW, EVENT_UPDATE, EVENT_FINAL, EVENT_CANCELLED]

    def __init__(self, coordinator: BomWarningsCoordinator, entry: BomWarningsConfigEntry) -> None:
        super().__init__(coordinator)
        unique_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{unique_id}_warning_event"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )
        # Set in async_added_to_hass: nothing present at that point counts as a transition.
        self._previous: dict[str, WarningState] = {}

    async def async_added_to_hass(self) -> None:
        self._previous = dict(self.coordinator.states)
        await super().async_added_to_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.last_update_success:
            current = self.coordinator.states
            for product_id, state in current.items():
                if (event_type := _transition(self._previous.get(product_id), state)) is None:
                    continue
                self._trigger_event(
                    event_type,
                    {
                        "product_id": state.product_id,
                        "event": state.event,
                        "severity": str(state.severity),
                        "headline": state.headline,
                    },
                )
            self._previous = dict(current)
        self.async_write_ha_state()
