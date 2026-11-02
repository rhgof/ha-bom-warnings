# Confirmed Home Assistant APIs

Checked 2026-11-02 against the installed `homeassistant` 2026.10.4 source (the version pinned by
`pytest-homeassistant-custom-component` 0.13.375). Not checked against the web docs. Re-check when
the HA pin moves.

- **Config flow**: subclass `config_entries.ConfigFlow, domain=DOMAIN`; steps return
  `ConfigFlowResult`. Use `await self.async_set_unique_id(...)` then
  `self._abort_if_unique_id_configured()`. Needs `"config_flow": true` in the manifest.
- **Options flow**: `ConfigFlow.async_get_options_flow(config_entry)` (static, callback) returns an
  `OptionsFlow`. `OptionsFlowWithReload` reloads the entry automatically when options change; it
  cannot be combined with update listeners.
- **DataUpdateCoordinator**: `DataUpdateCoordinator(hass, logger, *, config_entry=..., name=...,
  update_interval=..., update_method=..., setup_method=..., always_update=True)`. Pass
  `config_entry` explicitly. `async_config_entry_first_refresh()` raises `ConfigEntryNotReady`
  on failure; `_async_update_data` raises `UpdateFailed`.
- **Runtime data**: `type MyEntry = ConfigEntry[MyData]`; set `entry.runtime_data = ...` in
  `async_setup_entry`. No `hass.data[DOMAIN]`.
- **Event entity**: `homeassistant.components.event.EventEntity` with `_attr_event_types: list[str]`
  (or `entity_description.event_types`); fire with `self._trigger_event(event_type, attrs)`, then
  `self.async_write_ha_state()`. An event type not in `event_types` raises `ValueError`.
- **Diagnostics**: a `diagnostics.py` module with
  `async_get_config_entry_diagnostics(hass, config_entry) -> Mapping[str, Any]`; use
  `homeassistant.components.diagnostics.async_redact_data` for redaction.
- **Repairs**: `homeassistant.helpers.issue_registry.async_create_issue(hass, domain, issue_id, *,
  is_fixable, severity, translation_key, translation_placeholders=..., data=..., ...)` and
  `async_delete_issue(hass, domain, issue_id)`. Fixable issues need a `repairs.py` with
  `async_create_fix_flow` returning a `RepairsFlow` (e.g. `ConfirmRepairFlow`).

## Test harness

`pytest-homeassistant-custom-component` provides `hass` and `enable_custom_integrations`;
`tests/conftest.py` enables the latter for every test. It is in the `dev` dependency group.
