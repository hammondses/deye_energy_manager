"""Select platform for Deye Energy Manager."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_FLEXIBLE_LOAD_PRIORITY,
    DEFAULT_HEAT_MODE,
    DEFAULT_STRATEGY,
    DEFAULT_THERMAL_ACTUATION_MODE,
    DEFAULT_THERMAL_MODE,
    DOMAIN,
    FAN_MODE_DEFAULTS,
    FAN_MODE_OPTIONS,
    FLEXIBLE_LOAD_PRIORITY_OPTIONS,
    HEAT_MODE_OPTIONS,
    STRATEGY_OPTIONS,
    THERMAL_ACTUATION_MODE_OPTIONS,
    THERMAL_MODE_OPTIONS,
)
from .entity import DeyeEnergyManagerEntity

SELECTS = {
    "strategy": ("Strategy", STRATEGY_OPTIONS, DEFAULT_STRATEGY),
    "heat_mode": ("Heat mode", HEAT_MODE_OPTIONS, DEFAULT_HEAT_MODE),
    "thermal_mode": ("Thermal mode", THERMAL_MODE_OPTIONS, DEFAULT_THERMAL_MODE),
    "thermal_actuation_mode": ("Thermal actuation mode", THERMAL_ACTUATION_MODE_OPTIONS, DEFAULT_THERMAL_ACTUATION_MODE),
    "flexible_load_priority": ("Flexible load priority", FLEXIBLE_LOAD_PRIORITY_OPTIONS, DEFAULT_FLEXIBLE_LOAD_PRIORITY),
    "heat_soak_fan_mode": ("Heat soak fan mode", FAN_MODE_OPTIONS, FAN_MODE_DEFAULTS["heat_soak_fan_mode"]),
    "heat_normal_fan_mode": ("Heat normal fan mode", FAN_MODE_OPTIONS, FAN_MODE_DEFAULTS["heat_normal_fan_mode"]),
    "cool_soak_fan_mode": ("Cool soak fan mode", FAN_MODE_OPTIONS, FAN_MODE_DEFAULTS["cool_soak_fan_mode"]),
    "cool_normal_fan_mode": ("Cool normal fan mode", FAN_MODE_OPTIONS, FAN_MODE_DEFAULTS["cool_normal_fan_mode"]),
    "morning_preheat_fan_mode": ("Morning preheat fan mode", FAN_MODE_OPTIONS, FAN_MODE_DEFAULTS["morning_preheat_fan_mode"]),
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DeyeOptionSelect(coordinator, key, *config) for key, config in SELECTS.items())


class DeyeOptionSelect(DeyeEnergyManagerEntity, SelectEntity):
    def __init__(self, coordinator, key: str, name: str, options: list[str], default: str) -> None:
        super().__init__(coordinator, key, name)
        self._key = key
        self._attr_options = options
        self._default = default

    @property
    def current_option(self) -> str:
        option = str(self.coordinator.entry.options.get(self._key, self._default))
        return option if option in self.options else self._default

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            return
        await self.coordinator.async_set_option(self._key, option)
