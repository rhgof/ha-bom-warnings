"""Config flow for BoM Warnings. Minimal placeholder until the location steps land."""

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class BomWarningsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, str] | None = None) -> ConfigFlowResult:
        """Show the (not yet implemented) user step."""
        return self.async_abort(reason="not_implemented")
