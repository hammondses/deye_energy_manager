"""Number platform for Deye Energy Manager thresholds."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUMBER_DEFAULTS
from .entity import DeyeEnergyManagerEntity


@dataclass(frozen=True, kw_only=True)
class DeyeNumberDescription(NumberEntityDescription):
    default: float


NUMBERS = (
    DeyeNumberDescription(key="heat_add_min_charge_w", name="Heat add min charge", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["heat_add_min_charge_w"]),
    DeyeNumberDescription(key="heat_add_min_soc", name="Heat add min SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["heat_add_min_soc"]),
    DeyeNumberDescription(key="heat_shed_discharge_w", name="Heat shed discharge", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["heat_shed_discharge_w"]),
    DeyeNumberDescription(key="heat_soak_target_temp", name="Heat soak target temp", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=20, native_max_value=30, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["heat_soak_target_temp"]),
    DeyeNumberDescription(key="heat_normal_target_temp", name="Heat normal target temp", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=16, native_max_value=25, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["heat_normal_target_temp"]),
    DeyeNumberDescription(key="cool_soak_target_temp", name="Cool soak target temp", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=16, native_max_value=24, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["cool_soak_target_temp"]),
    DeyeNumberDescription(key="cool_normal_target_temp", name="Cool normal target temp", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=20, native_max_value=30, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["cool_normal_target_temp"]),
    DeyeNumberDescription(key="heat_comfort_target_temp", name="Heat comfort target temp", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=16, native_max_value=25, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["heat_comfort_target_temp"]),
    DeyeNumberDescription(key="cool_comfort_target_temp", name="Cool comfort target temp", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=20, native_max_value=30, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["cool_comfort_target_temp"]),
    DeyeNumberDescription(key="comfort_min_room_temp", name="Comfort min room temp", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=5, native_max_value=25, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["comfort_min_room_temp"]),
    DeyeNumberDescription(key="full_soak_min_soc", name="Full soak min SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["full_soak_min_soc"]),
    DeyeNumberDescription(key="forecast_soak_min_soc", name="Forecast soak min SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["forecast_soak_min_soc"]),
    DeyeNumberDescription(key="morning_battery_priority_soc", name="Morning battery priority SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["morning_battery_priority_soc"]),
    DeyeNumberDescription(key="morning_preheat_start_hour", name="Morning preheat start hour", native_min_value=0, native_max_value=23, native_step=0.25, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["morning_preheat_start_hour"]),
    DeyeNumberDescription(key="morning_preheat_end_hour", name="Morning preheat end hour", native_min_value=0, native_max_value=23, native_step=0.25, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["morning_preheat_end_hour"]),
    DeyeNumberDescription(key="morning_preheat_min_room_temp", name="Morning preheat min room temp", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=5, native_max_value=25, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["morning_preheat_min_room_temp"]),
    DeyeNumberDescription(key="morning_preheat_target_temp", name="Morning preheat target temp", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=10, native_max_value=25, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["morning_preheat_target_temp"]),
    DeyeNumberDescription(key="morning_preheat_min_soc", name="Morning preheat min SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["morning_preheat_min_soc"]),
    DeyeNumberDescription(key="morning_preheat_max_grid_import_w", name="Morning preheat max grid import", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["morning_preheat_max_grid_import_w"]),
    DeyeNumberDescription(key="morning_preheat_forecast_buffer_kwh", name="Morning preheat forecast buffer", native_min_value=0, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["morning_preheat_forecast_buffer_kwh"]),
    DeyeNumberDescription(key="paid_time_min_reserve_soc", name="Paid time min reserve SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["paid_time_min_reserve_soc"]),
    DeyeNumberDescription(key="morning_paid_time_min_reserve_soc", name="Morning paid time min reserve SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["morning_paid_time_min_reserve_soc"]),
    DeyeNumberDescription(key="evening_paid_time_min_reserve_soc", name="Evening paid time min reserve SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["evening_paid_time_min_reserve_soc"]),
    DeyeNumberDescription(key="pre_peak_preserve_min_reserve_soc", name="Pre peak preserve min reserve SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["pre_peak_preserve_min_reserve_soc"]),
    DeyeNumberDescription(key="paid_grid_import_threshold_w", name="Paid grid import threshold", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["paid_grid_import_threshold_w"]),
    DeyeNumberDescription(key="paid_grid_import_grace_minutes", name="Paid grid import grace minutes", native_min_value=0, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["paid_grid_import_grace_minutes"]),
    DeyeNumberDescription(key="solar_arrived_charge_threshold_w", name="Solar arrived charge threshold", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["solar_arrived_charge_threshold_w"]),
    DeyeNumberDescription(key="solar_arrived_pv_surplus_threshold_w", name="Solar arrived PV surplus threshold", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["solar_arrived_pv_surplus_threshold_w"]),
    DeyeNumberDescription(key="thermal_start_min_soc", name="Thermal start min SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["thermal_start_min_soc"]),
    DeyeNumberDescription(key="thermal_start_min_charge_w", name="Thermal start min charge", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["thermal_start_min_charge_w"]),
    DeyeNumberDescription(key="thermal_keep_running_min_charge_w", name="Thermal keep running min charge", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["thermal_keep_running_min_charge_w"]),
    DeyeNumberDescription(key="thermal_shed_discharge_w", name="Thermal shed discharge", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["thermal_shed_discharge_w"]),
    DeyeNumberDescription(key="thermal_emergency_shed_w", name="Thermal emergency shed", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["thermal_emergency_shed_w"]),
    DeyeNumberDescription(key="room_satisfied_delta_c", name="Room satisfied delta", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=0, native_step=0.1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["room_satisfied_delta_c"]),
    DeyeNumberDescription(key="room_resume_delta_c", name="Room resume delta", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=0, native_step=0.1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["room_resume_delta_c"]),
    DeyeNumberDescription(key="forecast_full_confidence_buffer_kwh", name="Forecast full confidence buffer", native_min_value=0, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["forecast_full_confidence_buffer_kwh"]),
    DeyeNumberDescription(key="ev_start_load_jump_w", name="EV start load jump", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["ev_start_load_jump_w"]),
    DeyeNumberDescription(key="ev_stop_load_drop_w", name="EV stop load drop", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["ev_stop_load_drop_w"]),
    DeyeNumberDescription(key="ev_active_load_threshold_w", name="EV active load threshold", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["ev_active_load_threshold_w"]),
    DeyeNumberDescription(key="ev_stopped_load_threshold_w", name="EV stopped load threshold", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=50, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["ev_stopped_load_threshold_w"]),
    DeyeNumberDescription(key="ev_hold_extra_minutes", name="EV hold extra minutes", native_min_value=0, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["ev_hold_extra_minutes"]),
    DeyeNumberDescription(key="ev_fallback_hold_minutes", name="EV fallback hold minutes", native_min_value=0, native_step=5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["ev_fallback_hold_minutes"]),
    DeyeNumberDescription(key="ev_restore_program_power_w", name="EV restore program power", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["ev_restore_program_power_w"]),
    DeyeNumberDescription(key="min_thermal_run_minutes", name="Minimum thermal run minutes", native_min_value=0, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["min_thermal_run_minutes"]),
    DeyeNumberDescription(key="min_thermal_rest_minutes", name="Minimum thermal rest minutes", native_min_value=0, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["min_thermal_rest_minutes"]),
    DeyeNumberDescription(key="thermal_rotation_cooldown_minutes", name="Thermal rotation cooldown minutes", native_min_value=0, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["thermal_rotation_cooldown_minutes"]),
    DeyeNumberDescription(key="auto_heating_below_temp", name="Auto heating below temp", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=-10, native_max_value=30, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["auto_heating_below_temp"]),
    DeyeNumberDescription(key="auto_cooling_above_temp", name="Auto cooling above temp", native_unit_of_measurement=UnitOfTemperature.CELSIUS, native_min_value=10, native_max_value=40, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["auto_cooling_above_temp"]),
    DeyeNumberDescription(key="forecast_safety_buffer_kwh", name="Forecast safety buffer", native_min_value=0, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["forecast_safety_buffer_kwh"]),
    DeyeNumberDescription(key="min_soc_floor", name="Minimum SOC floor", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["min_soc_floor"]),
    DeyeNumberDescription(key="max_grid_charge_target_soc", name="Maximum grid charge target SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["max_grid_charge_target_soc"]),
    DeyeNumberDescription(key="pv_load_test_min_soc", name="PV load test min SOC", native_unit_of_measurement=PERCENTAGE, native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["pv_load_test_min_soc"]),
    DeyeNumberDescription(key="pv_load_test_min_expected_power_w", name="PV load test min expected power", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["pv_load_test_min_expected_power_w"]),
    DeyeNumberDescription(key="pv_load_test_max_battery_charge_w", name="PV load test max battery charge", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["pv_load_test_max_battery_charge_w"]),
    DeyeNumberDescription(key="pv_load_test_min_remaining_forecast_kwh", name="PV load test min remaining forecast", native_min_value=0, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["pv_load_test_min_remaining_forecast_kwh"]),
    DeyeNumberDescription(key="heat_satisfied_margin_c", name="Heat satisfied margin", native_min_value=0, native_step=0.1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["heat_satisfied_margin_c"]),
    DeyeNumberDescription(key="heat_need_margin_c", name="Heat need margin", native_min_value=0, native_step=0.1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["heat_need_margin_c"]),
    DeyeNumberDescription(key="manual_override_cooldown_min", name="Manual override cooldown", native_min_value=0, native_step=5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["manual_override_cooldown_min"]),
    DeyeNumberDescription(key="emergency_shed_discharge_w", name="Emergency shed discharge", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["emergency_shed_discharge_w"]),
    DeyeNumberDescription(key="battery_capacity_kwh", name="Battery capacity", native_min_value=1, native_step=1, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["battery_capacity_kwh"]),
    DeyeNumberDescription(key="overnight_bedroom_taper_target_temp", name="Overnight bedroom taper target", native_min_value=5, native_max_value=30, native_step=0.5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["overnight_bedroom_taper_target_temp"]),
    DeyeNumberDescription(key="max_fallback_soc_age_minutes", name="Max fallback SOC age", native_min_value=0, native_step=5, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["max_fallback_soc_age_minutes"]),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DeyeThresholdNumber(coordinator, description) for description in NUMBERS)


class DeyeThresholdNumber(DeyeEnergyManagerEntity, NumberEntity):
    entity_description: DeyeNumberDescription

    def __init__(self, coordinator, description: DeyeNumberDescription) -> None:
        super().__init__(coordinator, description.key, description.name or description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        return float(self.coordinator.entry.options.get(self.entity_description.key, self.entity_description.default))

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_option(self.entity_description.key, float(value))
