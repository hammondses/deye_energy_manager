"""Sensor platform for Deye Energy Manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .decision import slugify
from .entity import DeyeEnergyManagerEntity
from .models import EnergyManagerDecision


@dataclass(frozen=True, kw_only=True)
class DeyeSensorDescription(SensorEntityDescription):
    value_fn: Callable[[EnergyManagerDecision], Any]


SENSORS: tuple[DeyeSensorDescription, ...] = (
    DeyeSensorDescription(key="active_plan", name="Active plan", value_fn=lambda d: ",".join(d.proposed_actions) or "advisory_only"),
    DeyeSensorDescription(key="active_policy", name="Active policy", value_fn=lambda d: d.active_policy),
    DeyeSensorDescription(key="forecast_mode", name="Forecast mode", value_fn=lambda d: d.forecast_mode),
    DeyeSensorDescription(key="current_slot", name="Current slot", value_fn=lambda d: d.active_slot),
    DeyeSensorDescription(key="actual_active_prog", name="Actual active prog", value_fn=lambda d: d.actual_active_prog),
    DeyeSensorDescription(key="actual_active_prog_start", name="Actual active prog start", value_fn=lambda d: d.actual_active_prog_start),
    DeyeSensorDescription(key="actual_active_prog_end", name="Actual active prog end", value_fn=lambda d: d.actual_active_prog_end),
    DeyeSensorDescription(key="actual_program_ranges", name="Actual program ranges", value_fn=lambda d: d.actual_active_prog),
    DeyeSensorDescription(key="disabled_programs", name="Disabled programs", value_fn=lambda d: ",".join(d.disabled_programs) or "none"),
    DeyeSensorDescription(key="logical_tariff_window", name="Logical tariff window", value_fn=lambda d: d.logical_tariff_window),
    DeyeSensorDescription(key="program_schedule_warning", name="Program schedule warning", value_fn=lambda d: d.program_schedule_warning),
    DeyeSensorDescription(key="current_tariff_window", name="Current tariff window", value_fn=lambda d: d.tariff_window),
    DeyeSensorDescription(key="today_forecast_kwh", name="Today forecast", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.forecast_today_kwh),
    DeyeSensorDescription(key="remaining_forecast_kwh", name="Remaining forecast", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.forecast_remaining_today_kwh),
    DeyeSensorDescription(key="tomorrow_forecast_kwh", name="Tomorrow forecast", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.forecast_tomorrow_kwh),
    DeyeSensorDescription(key="target_17_soc", name="Target 17 SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.target_17_soc),
    DeyeSensorDescription(key="current_reserve_soc", name="Current reserve SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.current_reserve_soc),
    DeyeSensorDescription(key="soc_source", name="SOC source", value_fn=lambda d: d.soc_source),
    DeyeSensorDescription(key="soc_age_minutes", name="SOC age minutes", value_fn=lambda d: d.soc_age_minutes),
    DeyeSensorDescription(key="grid_charge_target_soc", name="Grid charge target SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.grid_charge_target_soc),
    DeyeSensorDescription(key="morning_target_soc", name="Morning target SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.morning_target_soc),
    DeyeSensorDescription(key="morning_start_soc_target", name="Morning start SOC target", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.morning_start_soc_target),
    DeyeSensorDescription(key="evening_peak_soc_target", name="Evening peak SOC target", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.evening_peak_soc_target),
    DeyeSensorDescription(key="projected_4pm_soc", name="Projected 4pm SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.projected_4pm_soc),
    DeyeSensorDescription(key="projected_16_00_soc", name="Projected 16:00 SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.projected_4pm_soc),
    DeyeSensorDescription(key="required_4pm_energy_kwh", name="Required 4pm energy", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.required_4pm_energy_kwh),
    DeyeSensorDescription(key="night_grid_topup_kwh_required", name="Night grid topup kWh required", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.night_grid_topup_kwh_required),
    DeyeSensorDescription(key="energy_plan_reason", name="Energy plan reason", value_fn=lambda d: d.energy_plan_reason),
    DeyeSensorDescription(key="desired_deye_plan", name="Desired Deye plan", value_fn=lambda d: d.expected_action),
    DeyeSensorDescription(key="applied_deye_plan", name="Applied Deye plan", value_fn=lambda d: d.expected_action),
    DeyeSensorDescription(key="deye_write_reason", name="Deye write reason", value_fn=lambda d: d.reason),
    DeyeSensorDescription(key="deye_write_suppressed_reason", name="Deye write suppressed reason", value_fn=lambda d: d.reason),
    DeyeSensorDescription(key="deye_plan_conflict_reason", name="Deye plan conflict reason", value_fn=lambda d: d.deye_plan_conflict_reason),
    DeyeSensorDescription(key="deye_write_count_last_hour", name="Deye write count last hour", value_fn=lambda d: 0),
    DeyeSensorDescription(key="cheap_grid_preserve_target_soc", name="Cheap grid preserve target SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.cheap_grid_preserve_target_soc),
    DeyeSensorDescription(key="cheap_grid_mode", name="Cheap grid mode", value_fn=lambda d: d.cheap_grid_mode),
    DeyeSensorDescription(key="cheap_grid_reason", name="Cheap grid reason", value_fn=lambda d: d.cheap_grid_reason),
    DeyeSensorDescription(key="post_cheap_restore_reason", name="Post cheap restore reason", value_fn=lambda d: d.post_cheap_restore_reason),
    DeyeSensorDescription(key="battery_charge_w", name="Battery charge", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.battery_charge_w),
    DeyeSensorDescription(key="battery_discharge_w", name="Battery discharge", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.battery_discharge_w),
    DeyeSensorDescription(key="grid_import_w", name="Grid import", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.grid_import_w),
    DeyeSensorDescription(key="export_power_w", name="Export power", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.export_power_w),
    DeyeSensorDescription(key="thermal_export_margin_w", name="Thermal export margin", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.thermal_export_margin_w),
    DeyeSensorDescription(key="export_soak_reason", name="Export soak reason", value_fn=lambda d: d.export_soak_reason),
    DeyeSensorDescription(key="pv_power_now_w", name="PV power now", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.pv_power_now_w),
    DeyeSensorDescription(key="expected_action", name="Expected action", value_fn=lambda d: d.expected_action),
    DeyeSensorDescription(key="thermal_expected_action", name="Thermal expected action", value_fn=lambda d: d.thermal_action),
    DeyeSensorDescription(key="thermal_action_reason", name="Thermal action reason", value_fn=lambda d: d.thermal_action_reason),
    DeyeSensorDescription(key="thermal_policy_state", name="Thermal policy state", value_fn=lambda d: d.thermal_policy_state),
    DeyeSensorDescription(key="solar_phase", name="Solar phase", value_fn=lambda d: d.solar_phase),
    DeyeSensorDescription(key="effective_thermal_mode", name="Effective thermal mode", value_fn=lambda d: d.effective_thermal_mode),
    DeyeSensorDescription(key="auto_mode_reason", name="Auto mode reason", value_fn=lambda d: d.auto_mode_reason),
    DeyeSensorDescription(key="passive_warming_reason", name="Passive warming reason", value_fn=lambda d: d.passive_warming_reason),
    DeyeSensorDescription(key="battery_priority_reason", name="Battery priority reason", value_fn=lambda d: d.battery_priority_reason),
    DeyeSensorDescription(key="morning_preheat_reason", name="Morning preheat reason", value_fn=lambda d: d.morning_preheat_reason),
    DeyeSensorDescription(key="morning_preheat_load_to_add", name="Morning preheat load to add", value_fn=lambda d: d.morning_preheat_load_to_add),
    DeyeSensorDescription(key="underfloor_policy_state", name="Underfloor policy state", value_fn=lambda d: d.underfloor_policy_state),
    DeyeSensorDescription(key="underfloor_reason", name="Underfloor reason", value_fn=lambda d: d.underfloor_reason),
    DeyeSensorDescription(key="underfloor_load_to_add", name="Underfloor load to add", value_fn=lambda d: d.underfloor_load_to_add),
    DeyeSensorDescription(key="underfloor_current_window", name="Underfloor current window", value_fn=lambda d: d.underfloor_current_window),
    DeyeSensorDescription(key="paid_time_reserve_reason", name="Paid time reserve reason", value_fn=lambda d: d.paid_time_reserve_reason),
    DeyeSensorDescription(key="paid_time_floor_soc", name="Paid time floor SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.paid_time_floor_soc),
    DeyeSensorDescription(key="active_reserve_target_soc", name="Active reserve target SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.active_reserve_target_soc),
    DeyeSensorDescription(key="paid_grid_import_w", name="Paid grid import", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.paid_grid_import_w),
    DeyeSensorDescription(key="solar_arrived_reason", name="Solar arrived reason", value_fn=lambda d: d.solar_arrived_reason),
    DeyeSensorDescription(key="energy_budget_target_soc", name="Energy budget target SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.energy_budget_target_soc),
    DeyeSensorDescription(key="energy_budget_target_name", name="Energy budget target name", value_fn=lambda d: d.energy_budget_target_name),
    DeyeSensorDescription(key="remaining_solar_budget_kwh", name="Remaining solar budget", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.remaining_solar_budget_kwh),
    DeyeSensorDescription(key="battery_kwh_needed_to_target", name="Battery kWh needed to target", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.battery_kwh_needed_to_target),
    DeyeSensorDescription(key="expected_house_load_until_solar_end", name="Expected house load until solar end", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.expected_house_load_until_solar_end_kwh),
    DeyeSensorDescription(key="discretionary_energy_budget", name="Discretionary energy budget", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.discretionary_energy_budget_kwh),
    DeyeSensorDescription(key="energy_budget_reason", name="Energy budget reason", value_fn=lambda d: d.energy_budget_reason),
    DeyeSensorDescription(key="base_load_estimate", name="Base load estimate", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.base_load_estimate_w),
    DeyeSensorDescription(key="last_decision_reason", name="Last decision reason", value_fn=lambda d: d.reason),
    DeyeSensorDescription(key="last_control_action", name="Last control action", value_fn=lambda d: d.now.isoformat()),
    DeyeSensorDescription(key="thermal_load_to_shed", name="Thermal load to shed", value_fn=lambda d: d.thermal_load_to_shed),
    DeyeSensorDescription(key="thermal_load_to_add", name="Thermal load to add", value_fn=lambda d: d.thermal_load_to_add),
    DeyeSensorDescription(key="thermal_load_to_normalise", name="Thermal load to normalise", value_fn=lambda d: d.thermal_load_to_normalise),
    DeyeSensorDescription(key="heat_load_to_shed", name="Heat load to shed", value_fn=lambda d: d.heat_load_to_shed),
    DeyeSensorDescription(key="heat_load_to_add", name="Heat load to add", value_fn=lambda d: d.heat_load_to_add),
    DeyeSensorDescription(key="solar_owned_thermal_load_count", name="Solar owned thermal load count", value_fn=lambda d: d.solar_owned_thermal_load_count),
    DeyeSensorDescription(key="active_thermal_loads", name="Active thermal loads", value_fn=lambda d: ",".join(d.active_thermal_loads) or "none"),
    DeyeSensorDescription(key="projected_soc_08", name="Projected SOC 08:00", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.projected_soc_08),
    DeyeSensorDescription(key="ev_hold_until", name="EV hold until", device_class=SensorDeviceClass.TIMESTAMP, value_fn=lambda d: d.ev_hold_until),
    DeyeSensorDescription(key="ev_decision_reason", name="EV decision reason", value_fn=lambda d: d.ev_decision_reason),
    DeyeSensorDescription(key="ev_expected_action", name="EV expected action", value_fn=lambda d: d.ev_expected_action),
    DeyeSensorDescription(key="ev_detected_power_w", name="EV detected power", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.ev_detected_power_w),
    DeyeSensorDescription(key="recent_proposed_actions", name="Recent proposed actions", value_fn=lambda d: d.expected_action),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [DeyeSensor(coordinator, description) for description in SENSORS]
    for load in coordinator.heat_loads:
        slug = str(load.get("slug") or slugify(str(load.get("name", load.get("climate_entity", "thermal_load")))))
        name = str(load.get("name", load.get("climate_entity", "thermal_load")))
        entities.append(DeyeThermalLoadStatusSensor(coordinator, slug, name))
    async_add_entities(entities)


class DeyeSensor(DeyeEnergyManagerEntity, SensorEntity):
    """Decision sensor."""

    entity_description: DeyeSensorDescription

    def __init__(self, coordinator, description: DeyeSensorDescription) -> None:
        super().__init__(coordinator, description.key, description.name or description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        if self.entity_description.key == "last_control_action":
            return self.coordinator.last_control_action
        if self.entity_description.key == "desired_deye_plan":
            return self.coordinator.desired_deye_plan
        if self.entity_description.key == "applied_deye_plan":
            return self.coordinator.applied_deye_plan
        if self.entity_description.key == "deye_write_reason":
            return self.coordinator.deye_write_reason
        if self.entity_description.key == "deye_write_suppressed_reason":
            return self.coordinator.deye_write_suppressed_reason
        if self.entity_description.key == "deye_write_count_last_hour":
            self.coordinator._trim_deye_write_windows(dt_util.utcnow())
            return len(self.coordinator._deye_write_events)
        if self.entity_description.key == "recent_proposed_actions":
            return self.coordinator.recent_proposed_actions[-1]["proposed_action"] if self.coordinator.recent_proposed_actions else "none"
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        if self.entity_description.key == "recent_proposed_actions":
            return {"entries": list(self.coordinator.recent_proposed_actions)}
        if self.entity_description.key == "actual_program_ranges":
            decision = self.coordinator.data
            if decision is None:
                return None
            return {
                "ranges": decision.actual_program_ranges,
                "disabled_programs": decision.disabled_programs,
                "warning": decision.program_schedule_warning,
            }
        if self.entity_description.key in {"expected_action", "last_decision_reason", "thermal_action_reason", "soc_source", "soc_age_minutes"}:
            decision = self.coordinator.data
            if decision is None:
                return None
            return {
                "raw_soc": decision.raw_soc,
                "resolved_soc": decision.resolved_soc,
                "soc_source": decision.soc_source,
                "soc_age_minutes": decision.soc_age_minutes,
                "last_good_soc": decision.last_good_soc,
                "last_good_updated": decision.last_good_soc_updated.isoformat() if decision.last_good_soc_updated else None,
            }
        return None


class DeyeThermalLoadStatusSensor(DeyeEnergyManagerEntity, SensorEntity):
    """Per-managed-load thermal diagnostic sensor."""

    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator, slug: str, load_name: str) -> None:
        self._load_name = load_name
        self._slug = slug
        super().__init__(coordinator, f"{self._slug}_thermal_status", f"{load_name} thermal status")

    @property
    def native_value(self) -> str | None:
        diagnostic = self.coordinator.load_diagnostics.get(self._slug)
        return diagnostic.state if diagnostic else "unavailable"

    @property
    def extra_state_attributes(self) -> dict[str, object | None]:
        diagnostic = self.coordinator.load_diagnostics.get(self._slug)
        if not diagnostic:
            return {"load_name": self._load_name, "blocked_reason": "diagnostic unavailable"}
        return diagnostic.attributes
