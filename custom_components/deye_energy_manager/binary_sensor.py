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
    DeyeBinarySensorDescription(key="heat_allowed", name="Heat allowed", value_fn=lambda d: d.heat_allowed),
    DeyeBinarySensorDescription(key="heat_should_shed", name="Heat should shed", value_fn=lambda d: d.heat_should_shed),
    DeyeBinarySensorDescription(key="pv_load_test_recommended", name="PV load test recommended", value_fn=lambda d: d.pv_load_test_recommended),
    DeyeBinarySensorDescription(key="heat_rotation_recommended", name="Heat rotation recommended", value_fn=lambda d: d.heat_rotation_recommended),
    DeyeBinarySensorDescription(key="emergency_shed_all_required", name="Emergency shed all required", value_fn=lambda d: d.emergency_shed_all_required),
    DeyeBinarySensorDescription(key="overnight_protection_required", name="Overnight protection required", value_fn=lambda d: d.overnight_protection_required),
    DeyeBinarySensorDescription(key="bedroom_heat_taper_recommended", name="Bedroom heat taper recommended", value_fn=lambda d: d.bedroom_heat_taper_recommended),
    DeyeBinarySensorDescription(key="grid_charge_required", name="Grid charge required", value_fn=lambda d: d.grid_charge_required),
    DeyeBinarySensorDescription(key="ev_grid_mode_required", name="EV grid mode required", value_fn=lambda d: d.ev_grid_mode_required),
    DeyeBinarySensorDescription(key="pre_peak_preserve_required", name="Pre peak preserve required", value_fn=lambda d: d.pre_peak_preserve_required),
    DeyeBinarySensorDescription(key="safe_to_discharge", name="Safe to discharge", value_fn=lambda d: d.battery_soc >= d.current_reserve_soc),
    DeyeBinarySensorDescription(key="forecast_data_valid", name="Forecast data valid", value_fn=lambda d: d.forecast_data_valid),
    DeyeBinarySensorDescription(key="control_blocked", name="Control blocked", value_fn=lambda d: d.control_blocked),
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
        return self.entity_description.value_fn(self.coordinator.data)
