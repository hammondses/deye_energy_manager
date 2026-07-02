"""Config flow for Deye Energy Manager."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import (
    CONF_ENTITY_MAP,
    CONF_HEAT_LOADS,
    DEFAULT_ENTITY_MAP,
    DEFAULT_HEAT_LOADS,
    DEFAULT_HEAT_MODE,
    DEFAULT_STRATEGY,
    DEFAULT_THERMAL_MODE,
    DOMAIN,
    FEATURE_DEFAULTS,
    HEAT_MODE_OPTIONS,
    NUMBER_DEFAULTS,
    STRATEGY_OPTIONS,
    THERMAL_MODE_OPTIONS,
)


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("enabled", default=defaults.get("enabled", FEATURE_DEFAULTS["enabled"])): selector.BooleanSelector(),
            vol.Required(
                "advisory_enabled",
                default=defaults.get("advisory_enabled", FEATURE_DEFAULTS["advisory_enabled"]),
            ): selector.BooleanSelector(),
            vol.Required(
                "deye_control_enabled",
                default=defaults.get("deye_control_enabled", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "grid_charge_control_enabled",
                default=defaults.get("grid_charge_control_enabled", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "ev_control_enabled",
                default=defaults.get("ev_control_enabled", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "heat_control_enabled",
                default=defaults.get("heat_control_enabled", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "thermal_control_enabled",
                default=defaults.get("thermal_control_enabled", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "direct_climate_control_enabled",
                default=defaults.get("direct_climate_control_enabled", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "pv_load_test_control_enabled",
                default=defaults.get("pv_load_test_control_enabled", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "export_limited_mode_enabled",
                default=defaults.get("export_limited_mode_enabled", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "return_to_normal_on_shed_enabled",
                default=defaults.get("return_to_normal_on_shed_enabled", True),
            ): selector.BooleanSelector(),
            vol.Required(
                "forecast_full_override_enabled",
                default=defaults.get("forecast_full_override_enabled", True),
            ): selector.BooleanSelector(),
            vol.Required(
                "thermal_rotation_enabled",
                default=defaults.get("thermal_rotation_enabled", True),
            ): selector.BooleanSelector(),
            vol.Required("strategy", default=defaults.get("strategy", DEFAULT_STRATEGY)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=STRATEGY_OPTIONS)
            ),
            vol.Required("heat_mode", default=defaults.get("heat_mode", DEFAULT_HEAT_MODE)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=HEAT_MODE_OPTIONS)
            ),
            vol.Required("thermal_mode", default=defaults.get("thermal_mode", DEFAULT_THERMAL_MODE)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=THERMAL_MODE_OPTIONS)
            ),
            **{
                vol.Required(key, default=defaults.get(key, value)): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=1)
                )
                for key, value in NUMBER_DEFAULTS.items()
            },
        }
    )


def _entity_schema(defaults: dict[str, str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(key, default=defaults.get(key, entity_id)): selector.EntitySelector()
            for key, entity_id in DEFAULT_ENTITY_MAP.items()
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Deye Energy Manager."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Create the integration entry."""

        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_ENTITY_MAP: DEFAULT_ENTITY_MAP,
                    CONF_HEAT_LOADS: DEFAULT_HEAT_LOADS,
                },
                options={
                    **FEATURE_DEFAULTS,
                    **NUMBER_DEFAULTS,
                    "strategy": DEFAULT_STRATEGY,
                    "heat_mode": DEFAULT_HEAT_MODE,
                    "thermal_mode": DEFAULT_THERMAL_MODE,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default="Deye Energy Manager"): str}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Deye Energy Manager."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
        self._options: dict[str, Any] = dict(config_entry.options)

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_entities()
        return self.async_show_form(step_id="init", data_schema=_options_schema(self._options))

    async def async_step_entities(self, user_input: dict[str, Any] | None = None):
        defaults = {
            **DEFAULT_ENTITY_MAP,
            **self.config_entry.data.get(CONF_ENTITY_MAP, {}),
            **self.config_entry.options.get(CONF_ENTITY_MAP, {}),
        }
        if user_input is not None:
            self._options[CONF_ENTITY_MAP] = {key: value for key, value in user_input.items() if value}
            return self.async_create_entry(title="", data=self._options)
        return self.async_show_form(step_id="entities", data_schema=_entity_schema(defaults))
