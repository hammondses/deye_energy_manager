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
    FAN_MODE_DEFAULTS,
    FAN_MODE_OPTIONS,
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
                "cheap_grid_preserve_enabled",
                default=defaults.get("cheap_grid_preserve_enabled", FEATURE_DEFAULTS["cheap_grid_preserve_enabled"]),
            ): selector.BooleanSelector(),
            vol.Required(
                "cheap_grid_charge_enabled",
                default=defaults.get("cheap_grid_charge_enabled", FEATURE_DEFAULTS["cheap_grid_charge_enabled"]),
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
            vol.Required(
                "morning_preheat_enabled",
                default=defaults.get("morning_preheat_enabled", True),
            ): selector.BooleanSelector(),
            vol.Required(
                "passive_warming_guard_enabled",
                default=defaults.get("passive_warming_guard_enabled", True),
            ): selector.BooleanSelector(),
            vol.Required(
                "paid_time_grid_avoidance_enabled",
                default=defaults.get("paid_time_grid_avoidance_enabled", True),
            ): selector.BooleanSelector(),
            vol.Required(
                "underfloor_schedule_enabled",
                default=defaults.get("underfloor_schedule_enabled", True),
            ): selector.BooleanSelector(),
            vol.Required(
                "underfloor_require_home",
                default=defaults.get("underfloor_require_home", True),
            ): selector.BooleanSelector(),
            vol.Required(
                "underfloor_allow_paid_grid",
                default=defaults.get("underfloor_allow_paid_grid", False),
            ): selector.BooleanSelector(),
            vol.Required(
                "dynamic_base_load_estimate_enabled",
                default=defaults.get("dynamic_base_load_estimate_enabled", True),
            ): selector.BooleanSelector(),
            vol.Required("strategy", default=defaults.get("strategy", DEFAULT_STRATEGY)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=STRATEGY_OPTIONS)
            ),
            vol.Required(
                "heat_mode",
                default=defaults.get("heat_mode") if defaults.get("heat_mode") in HEAT_MODE_OPTIONS else DEFAULT_HEAT_MODE,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=HEAT_MODE_OPTIONS)
            ),
            vol.Required("thermal_mode", default=defaults.get("thermal_mode", DEFAULT_THERMAL_MODE)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=THERMAL_MODE_OPTIONS)
            ),
            vol.Required(
                "thermal_actuation_mode",
                default=(
                    defaults.get("thermal_actuation_mode")
                    if defaults.get("thermal_actuation_mode") in THERMAL_ACTUATION_MODE_OPTIONS
                    else DEFAULT_THERMAL_ACTUATION_MODE
                ),
            ): selector.SelectSelector(selector.SelectSelectorConfig(options=THERMAL_ACTUATION_MODE_OPTIONS)),
            vol.Required(
                "flexible_load_priority",
                default=defaults.get("flexible_load_priority", DEFAULT_FLEXIBLE_LOAD_PRIORITY),
            ): selector.SelectSelector(selector.SelectSelectorConfig(options=FLEXIBLE_LOAD_PRIORITY_OPTIONS)),
            vol.Required("heat_soak_fan_mode", default=defaults.get("heat_soak_fan_mode", FAN_MODE_DEFAULTS["heat_soak_fan_mode"])): selector.SelectSelector(
                selector.SelectSelectorConfig(options=FAN_MODE_OPTIONS)
            ),
            vol.Required("heat_normal_fan_mode", default=defaults.get("heat_normal_fan_mode", FAN_MODE_DEFAULTS["heat_normal_fan_mode"])): selector.SelectSelector(
                selector.SelectSelectorConfig(options=FAN_MODE_OPTIONS)
            ),
            vol.Required("cool_soak_fan_mode", default=defaults.get("cool_soak_fan_mode", FAN_MODE_DEFAULTS["cool_soak_fan_mode"])): selector.SelectSelector(
                selector.SelectSelectorConfig(options=FAN_MODE_OPTIONS)
            ),
            vol.Required("cool_normal_fan_mode", default=defaults.get("cool_normal_fan_mode", FAN_MODE_DEFAULTS["cool_normal_fan_mode"])): selector.SelectSelector(
                selector.SelectSelectorConfig(options=FAN_MODE_OPTIONS)
            ),
            vol.Required("morning_preheat_fan_mode", default=defaults.get("morning_preheat_fan_mode", FAN_MODE_DEFAULTS["morning_preheat_fan_mode"])): selector.SelectSelector(
                selector.SelectSelectorConfig(options=FAN_MODE_OPTIONS)
            ),
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
        "min_thermal_run_minutes",
        "min_thermal_rest_minutes",
        "thermal_rotation_cooldown_minutes",
        "battery_capacity_kwh",
        "overnight_bedroom_taper_target_temp",
        "auto_heating_below_temp",
        "auto_cooling_above_temp",
        "heat_comfort_target_temp",
        "cool_comfort_target_temp",
        "comfort_min_room_temp",
        "full_soak_min_soc",
        "forecast_soak_min_soc",
        "morning_battery_priority_soc",
        "morning_preheat_start_hour",
        "morning_preheat_end_hour",
        "morning_preheat_min_room_temp",
        "morning_preheat_target_temp",
        "morning_preheat_min_soc",
        "morning_preheat_max_grid_import_w",
        "morning_preheat_forecast_buffer_kwh",
        "solar_soak_required_battery_margin_kwh",
        "underfloor_morning_start_hour",
        "underfloor_morning_end_hour",
        "underfloor_evening_start_hour",
        "underfloor_evening_end_hour",
        "underfloor_preheat_minutes",
        "underfloor_comfort_min_temp",
        "underfloor_comfort_target_temp",
        "underfloor_max_target_temp",
        "underfloor_min_soc",
        "underfloor_max_grid_import_w",
    ]
    return vol.Schema(
        {
            vol.Required("thermal_mode", default=defaults.get("thermal_mode", DEFAULT_THERMAL_MODE)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=THERMAL_MODE_OPTIONS)
            ),
            vol.Required(
                "thermal_actuation_mode",
                default=(
                    defaults.get("thermal_actuation_mode")
                    if defaults.get("thermal_actuation_mode") in THERMAL_ACTUATION_MODE_OPTIONS
                    else DEFAULT_THERMAL_ACTUATION_MODE
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=THERMAL_ACTUATION_MODE_OPTIONS)
            ),
            vol.Required("return_to_normal_on_shed_enabled", default=defaults.get("return_to_normal_on_shed_enabled", True)): selector.BooleanSelector(),
            vol.Required("forecast_full_override_enabled", default=defaults.get("forecast_full_override_enabled", True)): selector.BooleanSelector(),
            vol.Required("thermal_rotation_enabled", default=defaults.get("thermal_rotation_enabled", True)): selector.BooleanSelector(),
            vol.Required("shed_unowned_managed_loads_on_battery_discharge", default=defaults.get("shed_unowned_managed_loads_on_battery_discharge", False)): selector.BooleanSelector(),
            vol.Required("morning_preheat_enabled", default=defaults.get("morning_preheat_enabled", True)): selector.BooleanSelector(),
            vol.Required("passive_warming_guard_enabled", default=defaults.get("passive_warming_guard_enabled", True)): selector.BooleanSelector(),
            vol.Required("underfloor_schedule_enabled", default=defaults.get("underfloor_schedule_enabled", True)): selector.BooleanSelector(),
            vol.Required("underfloor_require_home", default=defaults.get("underfloor_require_home", True)): selector.BooleanSelector(),
            vol.Required("underfloor_allow_paid_grid", default=defaults.get("underfloor_allow_paid_grid", False)): selector.BooleanSelector(),
            vol.Required("auto_mode_month_fallback_enabled", default=defaults.get("auto_mode_month_fallback_enabled", True)): selector.BooleanSelector(),
            vol.Required("heat_soak_fan_mode", default=defaults.get("heat_soak_fan_mode", FAN_MODE_DEFAULTS["heat_soak_fan_mode"])): selector.SelectSelector(selector.SelectSelectorConfig(options=FAN_MODE_OPTIONS)),
            vol.Required("heat_normal_fan_mode", default=defaults.get("heat_normal_fan_mode", FAN_MODE_DEFAULTS["heat_normal_fan_mode"])): selector.SelectSelector(selector.SelectSelectorConfig(options=FAN_MODE_OPTIONS)),
            vol.Required("cool_soak_fan_mode", default=defaults.get("cool_soak_fan_mode", FAN_MODE_DEFAULTS["cool_soak_fan_mode"])): selector.SelectSelector(selector.SelectSelectorConfig(options=FAN_MODE_OPTIONS)),
            vol.Required("cool_normal_fan_mode", default=defaults.get("cool_normal_fan_mode", FAN_MODE_DEFAULTS["cool_normal_fan_mode"])): selector.SelectSelector(selector.SelectSelectorConfig(options=FAN_MODE_OPTIONS)),
            vol.Required("morning_preheat_fan_mode", default=defaults.get("morning_preheat_fan_mode", FAN_MODE_DEFAULTS["morning_preheat_fan_mode"])): selector.SelectSelector(selector.SelectSelectorConfig(options=FAN_MODE_OPTIONS)),
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
    keys = [
        "forecast_safety_buffer_kwh",
        "min_soc_floor",
        "max_grid_charge_target_soc",
        "evening_peak_soc_target",
        "evening_peak_heating_allowance_kwh",
        "evening_peak_ev_allowance_kwh",
        "cheap_grid_preserve_soc",
        "cheap_grid_charge_target_soc",
        "max_fallback_soc_age_minutes",
        "paid_time_min_reserve_soc",
        "morning_paid_time_min_reserve_soc",
        "evening_paid_time_min_reserve_soc",
        "pre_peak_preserve_min_reserve_soc",
        "paid_grid_import_threshold_w",
        "paid_grid_import_grace_minutes",
        "solar_arrived_charge_threshold_w",
        "solar_arrived_pv_surplus_threshold_w",
        "daily_battery_target_soc",
        "battery_charge_efficiency",
        "base_load_estimate_w",
        "base_load_window_minutes",
        "house_load_forecast_buffer_kwh",
        "paid_grid_avoidance_buffer_kwh",
    ]
    return vol.Schema(
        {
            vol.Required("deye_control_enabled", default=defaults.get("deye_control_enabled", False)): selector.BooleanSelector(),
            vol.Required("grid_charge_control_enabled", default=defaults.get("grid_charge_control_enabled", False)): selector.BooleanSelector(),
            vol.Required("cheap_grid_preserve_enabled", default=defaults.get("cheap_grid_preserve_enabled", FEATURE_DEFAULTS["cheap_grid_preserve_enabled"])): selector.BooleanSelector(),
            vol.Required("cheap_grid_charge_enabled", default=defaults.get("cheap_grid_charge_enabled", FEATURE_DEFAULTS["cheap_grid_charge_enabled"])): selector.BooleanSelector(),
            vol.Required("paid_time_grid_avoidance_enabled", default=defaults.get("paid_time_grid_avoidance_enabled", True)): selector.BooleanSelector(),
            vol.Required("dynamic_base_load_estimate_enabled", default=defaults.get("dynamic_base_load_estimate_enabled", True)): selector.BooleanSelector(),
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
                    **FAN_MODE_DEFAULTS,
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
            menu_options=["controls", "thermal", "ev", "battery", "loads", "entities", "legacy"],
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

    async def async_step_loads(self, user_input: dict[str, Any] | None = None):
        loads = list(self.config_entry.options.get(CONF_HEAT_LOADS, self.config_entry.data.get(CONF_HEAT_LOADS, DEFAULT_HEAT_LOADS))) or list(DEFAULT_HEAT_LOADS)
        if user_input is not None:
            self._selected_load_index = int(user_input["load_index"])
            return await self.async_step_load_detail()
        return self.async_show_form(
            step_id="loads",
            data_schema=vol.Schema(
                {
                    vol.Required("load_index", default=0): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": str(index), "label": str(load.get("name", f"Load {index + 1}"))}
                                for index, load in enumerate(loads)
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_load_detail(self, user_input: dict[str, Any] | None = None):
        loads = list(self.config_entry.options.get(CONF_HEAT_LOADS, self.config_entry.data.get(CONF_HEAT_LOADS, DEFAULT_HEAT_LOADS))) or list(DEFAULT_HEAT_LOADS)
        index = getattr(self, "_selected_load_index", 0)
        load = dict(loads[index])
        if user_input is not None:
            load.update(user_input)
            loads[index] = load
            self._options[CONF_HEAT_LOADS] = loads
            return self.async_create_entry(title="", data=self._options)
        return self.async_show_form(
            step_id="load_detail",
            data_schema=vol.Schema(
                {
                    vol.Required("enabled", default=bool(load.get("enabled", True))): selector.BooleanSelector(),
                    vol.Required("slug", default=str(load.get("slug", ""))): str,
                    vol.Required("name", default=str(load.get("name", ""))): str,
                    vol.Required("climate_entity", default=str(load.get("climate_entity", ""))): selector.EntitySelector(),
                    vol.Required("ownership_entity", default=str(load.get("ownership_entity", ""))): selector.EntitySelector(),
                    vol.Required("priority", default=int(load.get("priority", 99))): selector.NumberSelector(selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=1, step=1)),
                    vol.Required("estimated_load_w", default=float(load.get("estimated_load_w", 0))): selector.NumberSelector(selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=100)),
                    vol.Required("supports_heating", default=bool(load.get("supports_heating", True))): selector.BooleanSelector(),
                    vol.Required("supports_cooling", default=bool(load.get("supports_cooling", False))): selector.BooleanSelector(),
                    vol.Optional("optional_power_sensor", default=str(load.get("optional_power_sensor", ""))): selector.EntitySelector(),
                    vol.Required("active_power_threshold_w", default=float(load.get("active_power_threshold_w", 800))): selector.NumberSelector(selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=50)),
                    vol.Required("idle_power_threshold_w", default=float(load.get("idle_power_threshold_w", 150))): selector.NumberSelector(selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=50)),
                    vol.Required("taper_power_threshold_w", default=float(load.get("taper_power_threshold_w", 400))): selector.NumberSelector(selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=50)),
                    vol.Required("allow_unowned_battery_shed", default=bool(load.get("allow_unowned_battery_shed", str(load.get("type", "heatpump")).lower() != "underfloor"))): selector.BooleanSelector(),
                    vol.Required("never_emergency_shed", default=bool(load.get("never_emergency_shed", False))): selector.BooleanSelector(),
                    vol.Required("comfort_sensor_type", default=str(load.get("comfort_sensor_type", "floor_slab" if str(load.get("type", "heatpump")) in {"underfloor", "floor_underfloor"} else "air"))): selector.SelectSelector(selector.SelectSelectorConfig(options=["air", "floor_slab"])),
                    vol.Optional("comfort_min_temp", default=load.get("comfort_min_temp")): selector.NumberSelector(selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=0.5)),
                    vol.Optional("comfort_target_temp", default=load.get("comfort_target_temp")): selector.NumberSelector(selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=0.5)),
                    vol.Optional("normal_target_temp", default=load.get("normal_target_temp")): selector.NumberSelector(selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, min=0, step=0.5)),
                    vol.Required("allow_solar_soak", default=bool(load.get("allow_solar_soak", str(load.get("type", "heatpump")).lower() not in {"underfloor", "floor_underfloor"}))): selector.BooleanSelector(),
                    vol.Required("type", default=str(load.get("type", "room_heat_pump" if str(load.get("type", "heatpump")) == "heatpump" else load.get("type", "room_heat_pump")))): selector.SelectSelector(selector.SelectSelectorConfig(options=["room_heat_pump", "floor_underfloor", "other", "heatpump", "underfloor"])),
                }
            ),
        )

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
