"""Diagnostics download for BoM Warnings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

from . import BomWarningsConfigEntry
from .const import CONF_LATITUDE, CONF_LONGITUDE

# The unique id is the rounded coordinates and the title is the zone name or the coordinates.
TO_REDACT = {CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME, "title", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BomWarningsConfigEntry
) -> Mapping[str, Any]:
    """Return the entry and the coordinator state with the location redacted."""
    coordinator = entry.runtime_data.coordinator
    return {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT,
        ),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "consecutive_failures": coordinator.consecutive_failures,
            "warnings": [
                {
                    "product_id": warning.product_id,
                    "event": warning.event,
                    "severity": warning.severity.value,
                    "effective": warning.effective.isoformat() if warning.effective else None,
                    "expires": warning.expires.isoformat() if warning.expires else None,
                }
                for warning in coordinator.data or ()
            ],
        },
    }
