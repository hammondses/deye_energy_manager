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
    DEFAULT_FLEXIBLE_LOAD_PRIORITY,
    DEFAULT_HEAT_LOADS,
    DEFAULT_HEAT_MODE,
    DEFAULT_STRATEGY,
    DEFAULT_THERMAL_ACTUATION_MODE,
    DEFAULT_THERMAL_MODE,
    DOMAIN,
    FEATURE_DEFAULTS,
    FLEXIBLE_LOAD_PRIORITY_OPTIONS,
    HEAT_MODE_OPTIONS,
    NUMBER_DEFAULTS,
    STRATEGY_OPTIONS,
    THERMAL_ACTUATION_MODE_OPTIONS,
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
                "ev_grid_bypass_enabled",
                default=defaults.get("ev_grid_bypass_enabled", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "ev_solar_charging_enabled",
                default=defaults.get("ev_solar_charging_enabled", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "ev_cheap_grid_charging_enabled",
                default=defaults.get("ev_cheap_grid_charging_enabled", True),
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
            vol.Required(
                "thermal_actuation_mode",
                default=defaults.get("thermal_actuation_mode", DEFAULT_THERMAL_ACTUATION_MODE),
            ): selector.SelectSelector(selector.SelectSelectorConfig(options=THERMAL_ACTUATION_MODE_OPTIONS)),
            vol.Required(
                "flexible_load_priority",
                default=defaults.get("flexible_load_priority", DEFAULT_FLEXIBLE_LOAD_PRIORITY),
            ): selector.SelectSelector(selector.SelectSelectorConfig(options=FLEXIBLE_LOAD_PRIORITY_OPTIONS)),
            **{
                vol.Required(key, default=defaults.get(key, value)): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=1)
                )
                for key, value in NUMBER_DEFAULTS.items()
            },
        }
    )


def _controls_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("enabled", default=defaults.get("enabled", FEATURE_DEFAULTS["enabled"])): selector.BooleanSelector(),
            vol.Required("advisory_enabled", default=defaults.get("advisory_enabled", True)): selector.BooleanSelector(),
            vol.Required("deye_control_enabled", default=defaults.get("deye_control_enabled", False)): selector.BooleanSelector(),
            vol.Required("grid_charge_control_enabled", default=defaults.get("grid_charge_control_enabled", False)): selector.BooleanSelector(),
            vol.Required("ev_control_enabled", default=defaults.get("ev_control_enabled", False)): selector.BooleanSelector(),
            vol.Required("thermal_control_enabled", default=defaults.get("thermal_control_enabled", False)): selector.BooleanSelector(),
            vol.Required("direct_climate_control_enabled", default=defaults.get("direct_climate_control_enabled", False)): selector.BooleanSelector(),
            vol.Required("strategy", default=defaults.get("strategy", DEFAULT_STRATEGY)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=STRATEGY_OPTIONS)
            ),
            vol.Required("flexible_load_priority", default=defaults.get("flexible_load_priority", DEFAULT_FLEXIBLE_LOAD_PRIORITY)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=FLEXIBLE_LOAD_PRIORITY_OPTIONS)
            ),
        }
    )


def _thermal_schema(defaults: dict[str, Any]) -> vol.Schema:
    thermal_keys = [
        "heat_soak_target_temp",
        "heat_normal_target_temp",
        "cool_soak_target_temp",
        "cool_normal_target_temp",
        "thermal_start_min_soc",
        "thermal_start_min_charge_w",
        "thermal_keep_running_min_charge_w",
        "thermal_shed_discharge_w",
        "thermal_emergency_shed_w",
        "room_satisfied_delta_c",
        "room_resume_delta_c",
        "forecast_full_confidence_buffer_kwh",
        "manual_override_cooldown_min",
        "battery_capacity_kwh",
        "overnight_bedroom_taper_target_temp",
    ]
    return vol.Schema(
        {
            vol.Required("thermal_mode", default=defaults.get("thermal_mode", DEFAULT_THERMAL_MODE)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=THERMAL_MODE_OPTIONS)
            ),
            vol.Required("thermal_actuation_mode", default=defaults.get("thermal_actuation_mode", DEFAULT_THERMAL_ACTUATION_MODE)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=THERMAL_ACTUATION_MODE_OPTIONS)
            ),
            vol.Required("return_to_normal_on_shed_enabled", default=defaults.get("return_to_normal_on_shed_enabled", True)): selector.BooleanSelector(),
            vol.Required("forecast_full_override_enabled", default=defaults.get("forecast_full_override_enabled", True)): selector.BooleanSelector(),
            vol.Required("thermal_rotation_enabled", default=defaults.get("thermal_rotation_enabled", True)): selector.BooleanSelector(),
            vol.Required("pv_load_test_control_enabled", default=defaults.get("pv_load_test_control_enabled", False)): selector.BooleanSelector(),
            vol.Required("export_limited_mode_enabled", default=defaults.get("export_limited_mode_enabled", False)): selector.BooleanSelector(),
            **{
                vol.Required(key, default=defaults.get(key, NUMBER_DEFAULTS[key])): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=0.5)
                )
                for key in thermal_keys
            },
        }
    )


def _ev_schema(defaults: dict[str, Any]) -> vol.Schema:
    ev_keys = [
        "ev_start_load_jump_w",
        "ev_stop_load_drop_w",
        "ev_active_load_threshold_w",
        "ev_stopped_load_threshold_w",
        "ev_hold_extra_minutes",
        "ev_fallback_hold_minutes",
        "ev_restore_program_power_w",
    ]
    return vol.Schema(
        {
            vol.Required("ev_control_enabled", default=defaults.get("ev_control_enabled", False)): selector.BooleanSelector(),
            vol.Required("ev_grid_bypass_enabled", default=defaults.get("ev_grid_bypass_enabled", False)): selector.BooleanSelector(),
            vol.Required("ev_solar_charging_enabled", default=defaults.get("ev_solar_charging_enabled", False)): selector.BooleanSelector(),
            vol.Required("ev_cheap_grid_charging_enabled", default=defaults.get("ev_cheap_grid_charging_enabled", True)): selector.BooleanSelector(),
            **{
                vol.Required(key, default=defaults.get(key, NUMBER_DEFAULTS[key])): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=100)
                )
                for key in ev_keys
            },
        }
    )


def _battery_schema(defaults: dict[str, Any]) -> vol.Schema:
    keys = ["forecast_safety_buffer_kwh", "min_soc_floor", "max_grid_charge_target_soc"]
    return vol.Schema(
        {
            vol.Required("deye_control_enabled", default=defaults.get("deye_control_enabled", False)): selector.BooleanSelector(),
            vol.Required("grid_charge_control_enabled", default=defaults.get("grid_charge_control_enabled", False)): selector.BooleanSelector(),
            **{
                vol.Required(key, default=defaults.get(key, NUMBER_DEFAULTS[key])): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=1)
                )
                for key in keys
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
                    "thermal_actuation_mode": DEFAULT_THERMAL_ACTUATION_MODE,
                    "flexible_load_priority": DEFAULT_FLEXIBLE_LOAD_PRIORITY,
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
        return self.async_show_menu(
            step_id="init",
            menu_options=["controls", "thermal", "ev", "battery", "entities", "legacy"],
        )

    async def async_step_controls(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)
        return self.async_show_form(step_id="controls", data_schema=_controls_schema(self._options))

    async def async_step_thermal(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)
        return self.async_show_form(step_id="thermal", data_schema=_thermal_schema(self._options))

    async def async_step_ev(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)
        return self.async_show_form(step_id="ev", data_schema=_ev_schema(self._options))

    async def async_step_battery(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)
        return self.async_show_form(step_id="battery", data_schema=_battery_schema(self._options))

    async def async_step_legacy(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)
        return self.async_show_form(step_id="legacy", data_schema=_options_schema(self._options))

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
