"""Binary sensor platform for Deye Energy Manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DeyeEnergyManagerEntity
from .models import EnergyManagerDecision


@dataclass(frozen=True, kw_only=True)
class DeyeBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[EnergyManagerDecision], bool]


BINARY_SENSORS = (
    DeyeBinarySensorDescription(key="battery_priority_satisfied", name="Battery priority satisfied", value_fn=lambda d: d.battery_priority_satisfied),
    DeyeBinarySensorDescription(key="thermal_allowed", name="Thermal allowed", value_fn=lambda d: d.thermal_allowed),
    DeyeBinarySensorDescription(key="thermal_should_shed", name="Thermal should shed", value_fn=lambda d: d.thermal_should_shed),
    DeyeBinarySensorDescription(key="thermal_should_emergency_shed", name="Thermal should emergency shed", value_fn=lambda d: d.thermal_should_emergency_shed),
    DeyeBinarySensorDescription(key="thermal_rotation_recommended", name="Thermal rotation recommended", value_fn=lambda d: d.thermal_rotation_recommended),
    DeyeBinarySensorDescription(key="passive_warming_likely", name="Passive warming likely", value_fn=lambda d: d.passive_warming_likely),
    DeyeBinarySensorDescription(key="comfort_heat_allowed", name="Comfort heat allowed", value_fn=lambda d: d.comfort_heat_allowed),
    DeyeBinarySensorDescription(key="solar_soak_allowed", name="Solar soak allowed", value_fn=lambda d: d.solar_soak_allowed),
    DeyeBinarySensorDescription(key="export_soak_available", name="Export soak available", value_fn=lambda d: d.export_soak_available),
    DeyeBinarySensorDescription(key="full_send_soak_allowed", name="Full send soak allowed", value_fn=lambda d: d.full_send_soak_allowed),
    DeyeBinarySensorDescription(key="morning_preheat_allowed", name="Morning preheat allowed", value_fn=lambda d: d.morning_preheat_allowed),
    DeyeBinarySensorDescription(key="underfloor_comfort_allowed", name="Underfloor comfort allowed", value_fn=lambda d: d.underfloor_comfort_allowed),
    DeyeBinarySensorDescription(key="paid_grid_avoidance_required", name="Paid grid avoidance required", value_fn=lambda d: d.paid_grid_avoidance_required),
    DeyeBinarySensorDescription(key="solar_arrived", name="Solar arrived", value_fn=lambda d: d.solar_arrived),
    DeyeBinarySensorDescription(key="forecast_drain_blocked", name="Forecast drain blocked", value_fn=lambda d: d.forecast_drain_blocked),
    DeyeBinarySensorDescription(key="discretionary_budget_positive", name="Discretionary budget positive", value_fn=lambda d: d.discretionary_budget_positive),
    DeyeBinarySensorDescription(key="battery_target_reachable_today", name="Battery target reachable today", value_fn=lambda d: d.battery_target_reachable_today),
    DeyeBinarySensorDescription(key="forecast_full_override_active", name="Forecast full override active", value_fn=lambda d: d.forecast_full_override_active),
    DeyeBinarySensorDescription(key="heat_allowed", name="Heat allowed", value_fn=lambda d: d.heat_allowed),
    DeyeBinarySensorDescription(key="heat_should_shed", name="Heat should shed", value_fn=lambda d: d.heat_should_shed),
    DeyeBinarySensorDescription(key="pv_load_test_recommended", name="PV load test recommended", value_fn=lambda d: d.pv_load_test_recommended),
    DeyeBinarySensorDescription(key="heat_rotation_recommended", name="Heat rotation recommended", value_fn=lambda d: d.heat_rotation_recommended),
    DeyeBinarySensorDescription(key="emergency_shed_all_required", name="Emergency shed all required", value_fn=lambda d: d.emergency_shed_all_required),
    DeyeBinarySensorDescription(key="overnight_protection_required", name="Overnight protection required", value_fn=lambda d: d.overnight_protection_required),
    DeyeBinarySensorDescription(key="bedroom_heat_taper_recommended", name="Bedroom heat taper recommended", value_fn=lambda d: d.bedroom_heat_taper_recommended),
    DeyeBinarySensorDescription(key="grid_charge_required", name="Grid charge required", value_fn=lambda d: d.grid_charge_required),
    DeyeBinarySensorDescription(key="cheap_grid_preserve_required", name="Cheap grid preserve required", value_fn=lambda d: d.cheap_grid_preserve_required),
    DeyeBinarySensorDescription(key="cheap_grid_topup_required", name="Cheap grid topup required", value_fn=lambda d: d.cheap_grid_topup_required),
    DeyeBinarySensorDescription(key="ev_grid_mode_required", name="EV grid mode required", value_fn=lambda d: d.ev_grid_mode_required),
    DeyeBinarySensorDescription(key="ev_charging_detected", name="EV charging detected", value_fn=lambda d: d.ev_charging_detected),
    DeyeBinarySensorDescription(key="ev_grid_bypass_required", name="EV grid bypass required", value_fn=lambda d: d.ev_grid_bypass_required),
    DeyeBinarySensorDescription(key="ev_solar_charge_allowed", name="EV solar charge allowed", value_fn=lambda d: d.ev_solar_charge_allowed),
    DeyeBinarySensorDescription(key="ev_latch_active", name="EV latch active", value_fn=lambda d: d.ev_latch_active),
    DeyeBinarySensorDescription(key="pre_peak_preserve_required", name="Pre peak preserve required", value_fn=lambda d: d.pre_peak_preserve_required),
    DeyeBinarySensorDescription(key="safe_to_discharge", name="Safe to discharge", value_fn=lambda d: d.battery_soc is not None and d.battery_soc >= d.current_reserve_soc),
    DeyeBinarySensorDescription(key="forecast_data_valid", name="Forecast data valid", value_fn=lambda d: d.forecast_data_valid),
    DeyeBinarySensorDescription(key="control_blocked", name="Control blocked", value_fn=lambda d: d.control_blocked),
    DeyeBinarySensorDescription(key="deye_write_thrash_detected", name="Deye write thrash detected", value_fn=lambda d: False),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DeyeBinarySensor(coordinator, description) for description in BINARY_SENSORS)


class DeyeBinarySensor(DeyeEnergyManagerEntity, BinarySensorEntity):
    entity_description: DeyeBinarySensorDescription

    def __init__(self, coordinator, description: DeyeBinarySensorDescription) -> None:
        super().__init__(coordinator, description.key, description.name or description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        if self.entity_description.key == "deye_write_thrash_detected":
            return self.coordinator.deye_write_thrash_detected
        return self.entity_description.value_fn(self.coordinator.data)
