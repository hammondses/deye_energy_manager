"""Number platform for Deye Energy Manager thresholds."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
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
    DeyeNumberDescription(key="ev_start_load_jump_w", name="EV start load jump", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["ev_start_load_jump_w"]),
    DeyeNumberDescription(key="ev_stop_load_drop_w", name="EV stop load drop", native_unit_of_measurement=UnitOfPower.WATT, native_min_value=0, native_step=100, mode=NumberMode.BOX, default=NUMBER_DEFAULTS["ev_stop_load_drop_w"]),
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
