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
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from . import location
from .const import (
    CONF_AREA_CODES,
    CONF_HIDE_FINAL,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_STATE,
    CONF_WARNING_TYPES,
    CONF_ZONE,
    DOMAIN,
    MAX_RADIUS_M,
    SPATIAL_CACHE_DIR,
)
from .ftp import BomFtpError, client_from_env
from .warning_types import enabled_keys, label_of, type_keys


class _LocationError(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class BomWarningsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pick the Home Assistant home location, a zone, or type coordinates."""

    VERSION = 3

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
                        radius_m=min(float(state.attributes.get("radius", 0)), MAX_RADIUS_M),
                        extra={CONF_ZONE: zone_id},
                    )
                except _LocationError as err:
                    errors["base"] = err.key
        return self.async_show_form(
            step_id="zone",
            data_schema=probatio.Schema(
                {probatio.Required(CONF_ZONE): EntitySelector(EntitySelectorConfig(domain="zone"))}
            ),
            errors=errors,
        )

    async def _async_create(
        self,
        unique_id: str,
        title: str,
        lat: float,
        lon: float,
        *,
        radius_m: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Create the entry; raises _LocationError with the error key on failure."""
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
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
        data: dict[str, Any] = {
            **(extra or {}),
            CONF_LATITUDE: lat,
            CONF_LONGITUDE: lon,
            CONF_STATE: found.state,
            CONF_AREA_CODES: sorted(found.area_codes),
        }
        if CONF_ZONE in data:
            data[CONF_RADIUS] = radius_m
        return self.async_create_entry(title=title, data=data)


class BomWarningsOptionsFlow(OptionsFlowWithReload):
    """Which warning types matter here. Saving reloads the entry, so no restart is needed."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        enabled = enabled_keys(self.config_entry.options)
        if user_input is not None:
            chosen = set(user_input.get(CONF_WARNING_TYPES, enabled))
            return self.async_create_entry(
                data={
                    CONF_HIDE_FINAL: user_input.get(
                        CONF_HIDE_FINAL, self.config_entry.options.get(CONF_HIDE_FINAL, True)
                    ),
                    CONF_WARNING_TYPES: [key for key in type_keys() if key in chosen],
                }
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
