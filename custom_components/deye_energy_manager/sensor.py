"""Sensor platform for Deye Energy Manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DeyeEnergyManagerEntity
from .models import EnergyManagerDecision


@dataclass(frozen=True, kw_only=True)
class DeyeSensorDescription(SensorEntityDescription):
    value_fn: Callable[[EnergyManagerDecision], Any]


SENSORS: tuple[DeyeSensorDescription, ...] = (
    DeyeSensorDescription(key="active_plan", name="Active plan", value_fn=lambda d: ",".join(d.proposed_actions) or "advisory_only"),
    DeyeSensorDescription(key="forecast_mode", name="Forecast mode", value_fn=lambda d: d.forecast_mode),
    DeyeSensorDescription(key="current_slot", name="Current slot", value_fn=lambda d: d.active_slot),
    DeyeSensorDescription(key="current_tariff_window", name="Current tariff window", value_fn=lambda d: d.tariff_window),
    DeyeSensorDescription(key="today_forecast_kwh", name="Today forecast", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, device_class=SensorDeviceClass.ENERGY, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.forecast_today_kwh),
    DeyeSensorDescription(key="remaining_forecast_kwh", name="Remaining forecast", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, device_class=SensorDeviceClass.ENERGY, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.forecast_remaining_today_kwh),
    DeyeSensorDescription(key="tomorrow_forecast_kwh", name="Tomorrow forecast", native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, device_class=SensorDeviceClass.ENERGY, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.forecast_tomorrow_kwh),
    DeyeSensorDescription(key="target_17_soc", name="Target 17 SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.target_17_soc),
    DeyeSensorDescription(key="current_reserve_soc", name="Current reserve SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.current_reserve_soc),
    DeyeSensorDescription(key="grid_charge_target_soc", name="Grid charge target SOC", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.grid_charge_target_soc),
    DeyeSensorDescription(key="battery_charge_w", name="Battery charge", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.battery_charge_w),
    DeyeSensorDescription(key="battery_discharge_w", name="Battery discharge", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.battery_discharge_w),
    DeyeSensorDescription(key="pv_power_now_w", name="PV power now", native_unit_of_measurement=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d.pv_power_now_w),
    DeyeSensorDescription(key="expected_action", name="Expected action", value_fn=lambda d: ",".join(d.proposed_actions) or "none"),
    DeyeSensorDescription(key="last_decision_reason", name="Last decision reason", value_fn=lambda d: d.reason),
    DeyeSensorDescription(key="last_control_action", name="Last control action", value_fn=lambda d: d.now.isoformat()),
    DeyeSensorDescription(key="ev_hold_until", name="EV hold until", device_class=SensorDeviceClass.TIMESTAMP, value_fn=lambda d: d.ev_hold_until),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DeyeSensor(coordinator, description) for description in SENSORS)


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
        return self.entity_description.value_fn(self.coordinator.data)

