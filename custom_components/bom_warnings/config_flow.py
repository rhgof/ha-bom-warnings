"""Config flow for BoM Warnings: one location per entry, or one Home Assistant zone."""

from __future__ import annotations

import os
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
    SelectSelector,
    SelectSelectorConfig,
)

from .areas import state_of
from .const import (
    CONF_AREA_CODES,
    CONF_EVENT_TYPES,
    CONF_HIDE_FINAL,
    CONF_INCLUDE_MARINE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_STATE,
    CONF_ZONE,
    DOMAIN,
    KNOWN_EVENT_TYPES,
    MAX_RADIUS_M,
    SPATIAL_CACHE_DIR,
)
from .ftp import BomFtpError, client_from_env
from .spatial import SpatialDataError, resolve_coordinate


def _resolve(cache_dir: Path, lat: float, lon: float, radius_m: float) -> set[str]:
    """Blocking: runs in an executor."""
    ftp = client_from_env(os.environ)
    with ftp.session():
        return resolve_coordinate(ftp, cache_dir, lat=lat, lon=lon, radius_m=radius_m)


class _LocationError(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class BomWarningsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pick the Home Assistant home location, a zone, or type coordinates."""

    VERSION = 1

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
            codes = await self.hass.async_add_executor_job(_resolve, cache_dir, lat, lon, radius_m)
        except (BomFtpError, SpatialDataError, OSError) as err:
            raise _LocationError("cannot_connect") from err
        except Exception as err:
            raise _LocationError("unknown") from err
        if not codes:
            raise _LocationError("no_area")
        data: dict[str, Any] = {
            **(extra or {}),
            CONF_LATITUDE: lat,
            CONF_LONGITUDE: lon,
            CONF_STATE: state_of(codes),
            CONF_AREA_CODES: sorted(codes),
        }
        if CONF_ZONE in data:
            data[CONF_RADIUS] = radius_m
        return self.async_create_entry(title=title, data=data)


class BomWarningsOptionsFlow(OptionsFlowWithReload):
    """Which warnings to show. Saving reloads the entry, so no restart is needed."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Optional(CONF_HIDE_FINAL, default=True): BooleanSelector(),
                        probatio.Optional(CONF_EVENT_TYPES, default=[]): SelectSelector(
                            SelectSelectorConfig(
                                options=list(KNOWN_EVENT_TYPES),
                                multiple=True,
                                custom_value=True,
                            )
                        ),
                        # Offered to every entry: a typed location can be on the water too.
                        probatio.Optional(CONF_INCLUDE_MARINE, default=False): BooleanSelector(),
                    }
                ),
                self.config_entry.options,
            ),
        )
