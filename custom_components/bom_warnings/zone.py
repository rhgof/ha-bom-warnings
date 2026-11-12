"""Follow a Home Assistant zone: keep an entry's circle in step with the zone it was made from."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_ZONE,
    CONF_ZONE_NAME,
    DOMAIN,
    MAX_RADIUS_M,
)

if TYPE_CHECKING:
    from . import BomWarningsConfigEntry


def zone_removed_issue_id(entry: BomWarningsConfigEntry) -> str:
    return f"zone_removed_{entry.entry_id}"


def radius_clamped_issue_id(entry: BomWarningsConfigEntry) -> str:
    return f"radius_clamped_{entry.entry_id}"


def delete_zone_issues(hass: HomeAssistant, entry: BomWarningsConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, zone_removed_issue_id(entry))
    ir.async_delete_issue(hass, DOMAIN, radius_clamped_issue_id(entry))


class ZoneFollower:
    """Mirrors a zone's name, centre and radius into the entry, and says when the circle changed.

    A zone that is deleted leaves the entry on its last known circle and raises a repair issue; if
    a zone with the same entity id comes back, the entry follows it again.
    """

    def __init__(
        self, hass: HomeAssistant, entry: BomWarningsConfigEntry, on_change: Callable[[], None]
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._zone_id: str = entry.data[CONF_ZONE]
        self._on_change = on_change
        self._unsubscribe: CALLBACK_TYPE | None = None

    def start(self) -> None:
        self._unsubscribe = async_track_state_change_event(
            self._hass, [self._zone_id], self._handle_event
        )
        # The zone may have been edited, or deleted, while Home Assistant was not running.
        self.sync()

    def stop(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    @callback
    def _handle_event(self, event: Event[EventStateChangedData]) -> None:
        self.sync()

    @callback
    def sync(self) -> None:
        state = self._hass.states.get(self._zone_id)
        if state is None:
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                zone_removed_issue_id(self._entry),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="zone_removed",
                translation_placeholders={"title": self._entry.title, "zone": self._zone_id},
            )
            return
        ir.async_delete_issue(self._hass, DOMAIN, zone_removed_issue_id(self._entry))
        self._sync_name(state.name)

        try:
            latitude = float(state.attributes[CONF_LATITUDE])
            longitude = float(state.attributes[CONF_LONGITUDE])
            radius = float(state.attributes.get(CONF_RADIUS, 0))
        except KeyError, TypeError, ValueError:
            # Not a usable zone state; keep the last known circle.
            return
        self._sync_radius_notice(radius)

        circle = {
            CONF_LATITUDE: latitude,
            CONF_LONGITUDE: longitude,
            CONF_RADIUS: min(radius, MAX_RADIUS_M),
        }
        if all(self._entry.data.get(key) == value for key, value in circle.items()):
            return
        self._hass.config_entries.async_update_entry(
            self._entry, data={**self._entry.data, **circle}
        )
        self._on_change()

    def _sync_name(self, name: str) -> None:
        """Carry a zone rename into the entry title and its device, unless the user chose a title.

        The title was copied from the zone, so it still equals the zone's last known name unless
        the user renamed the entry since; then it is theirs and stays.
        """
        data = self._entry.data
        followed = data.get(CONF_ZONE_NAME, self._entry.title)
        if name == followed and CONF_ZONE_NAME in data:
            return
        title = name if self._entry.title == followed else self._entry.title
        self._hass.config_entries.async_update_entry(
            self._entry, title=title, data={**data, CONF_ZONE_NAME: name}
        )
        # Entities take their names from the device, so a new title alone would show only after a
        # restart. A name the user gave the device itself still wins over this one.
        registry = dr.async_get(self._hass)
        identifier = (DOMAIN, self._entry.unique_id or self._entry.entry_id)
        if device := registry.async_get_device_by_identifier(identifier, self._entry.entry_id):
            registry.async_update_device(device.id, name=title)

    def _sync_radius_notice(self, radius: float) -> None:
        issue_id = radius_clamped_issue_id(self._entry)
        if radius <= MAX_RADIUS_M:
            ir.async_delete_issue(self._hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="radius_clamped",
            translation_placeholders={
                "title": self._entry.title,
                "radius": f"{radius / 1000:g}",
                "max": f"{MAX_RADIUS_M / 1000:g}",
            },
        )
