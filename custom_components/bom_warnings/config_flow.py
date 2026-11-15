"""Config flow for BoM Warnings: one location per entry, or one Home Assistant zone."""

from __future__ import annotations

import os
from functools import partial
from pathlib import Path
from typing import Any

import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from . import location
from .const import (
    CONF_AREA_CODES,
    CONF_AREA_NAMES,
    CONF_HIDE_FINAL,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_STATE,
    CONF_WARNING_RADIUS,
    CONF_WARNING_TYPES,
    CONF_ZONE,
    CONF_ZONE_NAME,
    DOMAIN,
    MAX_RADIUS_M,
    SPATIAL_CACHE_DIR,
)
from .ftp import BomFtpError, client_from_env
from .warning_types import enabled_keys, label_of, type_keys

_WARNING_RADIUS_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=0,
        max=MAX_RADIUS_M / 1000,
        step=0.1,
        unit_of_measurement="km",
        mode=NumberSelectorMode.BOX,
    )
)


class _LocationError(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class BomWarningsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pick the Home Assistant home location, a zone, or type coordinates."""

    VERSION = 4

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BomWarningsOptionsFlow:
        return BomWarningsOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = ["home", "manual"]
        if self.hass.states.async_entity_ids("zone"):
            options.insert(1, "zone")
        return self.async_show_menu(step_id="user", menu_options=options)

    async def async_step_home(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        config = self.hass.config
        try:
            return await self._async_create(
                f"{config.latitude:.3f},{config.longitude:.3f}",
                config.location_name,
                config.latitude,
                config.longitude,
            )
        except _LocationError as err:
            # There is no form to show again, so a failure ends the flow.
            return self.async_abort(reason=err.key)

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            lat, lon = user_input[CONF_LATITUDE], user_input[CONF_LONGITUDE]
            try:
                return await self._async_create(
                    f"{lat:.3f},{lon:.3f}", f"{lat:.3f}, {lon:.3f}", lat, lon
                )
            except _LocationError as err:
                errors["base"] = err.key
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_LATITUDE): cv.latitude,
                        probatio.Required(CONF_LONGITUDE): cv.longitude,
                    }
                ),
                user_input
                or {
                    CONF_LATITUDE: self.hass.config.latitude,
                    CONF_LONGITUDE: self.hass.config.longitude,
                },
            ),
            errors=errors,
        )

    async def async_step_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            zone_id = user_input[CONF_ZONE]
            radius_km = float(user_input[CONF_WARNING_RADIUS])
            state = self.hass.states.get(zone_id)
            if state is None:
                errors["base"] = "zone_not_found"
            else:
                try:
                    return await self._async_create(
                        zone_id,
                        state.name,
                        state.attributes["latitude"],
                        state.attributes["longitude"],
                        radius_m=radius_km * 1000,
                        extra={CONF_ZONE: zone_id, CONF_ZONE_NAME: state.name},
                        options={CONF_WARNING_RADIUS: radius_km},
                    )
                except _LocationError as err:
                    errors["base"] = err.key
        return self.async_show_form(
            step_id="zone",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_ZONE): EntitySelector(
                        EntitySelectorConfig(domain="zone")
                    ),
                    probatio.Optional(CONF_WARNING_RADIUS, default=0): _WARNING_RADIUS_SELECTOR,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Follow another zone, keeping the entry and so its entities.

        The unique id stays the zone the entry was made from: the device and every entity id are
        built from it, so changing it would recreate them all under new ids.
        """
        entry = self._get_reconfigure_entry()
        if CONF_ZONE not in entry.data:
            return self.async_abort(reason="not_a_zone_entry")
        errors: dict[str, str] = {}
        if user_input is not None:
            zone_id = user_input[CONF_ZONE]
            state = self.hass.states.get(zone_id)
            if any(
                other.data.get(CONF_ZONE) == zone_id
                for other in self._async_current_entries()
                if other.entry_id != entry.entry_id
            ):
                errors["base"] = "zone_already_followed"
            elif state is None:
                errors["base"] = "zone_not_found"
            else:
                lat, lon = state.attributes["latitude"], state.attributes["longitude"]
                radius_m = float(entry.options.get(CONF_WARNING_RADIUS, 0)) * 1000
                try:
                    found = await self._async_resolve(lat, lon, radius_m)
                except _LocationError as err:
                    errors["base"] = err.key
                else:
                    # The zone name is left for the zone follower, which renames the entry and its
                    # device only when the user has not chosen their own title.
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_ZONE: zone_id,
                            CONF_LATITUDE: lat,
                            CONF_LONGITUDE: lon,
                            CONF_RADIUS: radius_m,
                            CONF_STATE: found.state,
                            CONF_AREA_CODES: sorted(found.area_codes),
                            CONF_AREA_NAMES: dict(found.area_names),
                        },
                    )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_ZONE): EntitySelector(
                            EntitySelectorConfig(domain="zone")
                        )
                    }
                ),
                {CONF_ZONE: entry.data[CONF_ZONE]},
            ),
            errors=errors,
        )

    async def _async_resolve(
        self, lat: float, lon: float, radius_m: float
    ) -> location.ResolvedLocation:
        """The areas covering a circle; raises _LocationError with the error key on failure."""
        cache_dir = Path(self.hass.config.path(SPATIAL_CACHE_DIR))
        try:
            # Built here so an invalid dev host override (a BomFtpError) is a connection problem.
            ftp = client_from_env(os.environ)
            found = await self.hass.async_add_executor_job(
                partial(
                    location.resolve_location, ftp, cache_dir, lat=lat, lon=lon, radius_m=radius_m
                )
            )
        except (location.LocationUnavailable, BomFtpError) as err:
            raise _LocationError("cannot_connect") from err
        except Exception as err:
            raise _LocationError("unknown") from err
        if not found.area_codes:
            raise _LocationError("no_area")
        return found

    async def _async_create(
        self,
        unique_id: str,
        title: str,
        lat: float,
        lon: float,
        *,
        radius_m: float = 0.0,
        extra: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Create the entry; raises _LocationError with the error key on failure."""
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        found = await self._async_resolve(lat, lon, radius_m)
        data: dict[str, Any] = {
            **(extra or {}),
            CONF_LATITUDE: lat,
            CONF_LONGITUDE: lon,
            CONF_STATE: found.state,
            CONF_AREA_CODES: sorted(found.area_codes),
            CONF_AREA_NAMES: dict(found.area_names),
        }
        if CONF_ZONE in data:
            data[CONF_RADIUS] = radius_m
        return self.async_create_entry(title=title, data=data, options=options or {})


class BomWarningsOptionsFlow(OptionsFlowWithReload):
    """Which warning types matter here. Saving reloads the entry, so no restart is needed."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        enabled = enabled_keys(self.config_entry.options)
        # Only a zone entry has a radius to set.
        is_zone = CONF_ZONE in self.config_entry.data
        radius_km = self.config_entry.options.get(CONF_WARNING_RADIUS, 0)
        if user_input is not None:
            chosen = set(user_input.get(CONF_WARNING_TYPES, enabled))
            options: dict[str, Any] = {
                CONF_HIDE_FINAL: user_input.get(
                    CONF_HIDE_FINAL, self.config_entry.options.get(CONF_HIDE_FINAL, True)
                ),
                CONF_WARNING_TYPES: [key for key in type_keys() if key in chosen],
            }
            if is_zone:
                options[CONF_WARNING_RADIUS] = float(user_input.get(CONF_WARNING_RADIUS, radius_km))
            return self.async_create_entry(data=options)
        radius_field = (
            {probatio.Optional(CONF_WARNING_RADIUS, default=radius_km): _WARNING_RADIUS_SELECTOR}
            if is_zone
            else {}
        )
        # One checkbox list is much shorter on screen than a switch per type.
        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_HIDE_FINAL,
                        default=self.config_entry.options.get(CONF_HIDE_FINAL, True),
                    ): BooleanSelector(),
                    **radius_field,
                    probatio.Optional(
                        CONF_WARNING_TYPES, default=[k for k in type_keys() if k in enabled]
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=key, label=label_of(key))
                                for key in type_keys()
                            ],
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )
