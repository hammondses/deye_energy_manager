"""Select platform for Deye Energy Manager."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_HEAT_MODE, DEFAULT_STRATEGY, DOMAIN, HEAT_MODE_OPTIONS, STRATEGY_OPTIONS
from .entity import DeyeEnergyManagerEntity

SELECTS = {
    "strategy": ("Strategy", STRATEGY_OPTIONS, DEFAULT_STRATEGY),
    "heat_mode": ("Heat mode", HEAT_MODE_OPTIONS, DEFAULT_HEAT_MODE),
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
        return str(self.coordinator.entry.options.get(self._key, self._default))

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            return
        await self.coordinator.async_set_option(self._key, option)

