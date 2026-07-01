"""Switch platform for Deye Energy Manager feature gates."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FEATURE_DEFAULTS
from .entity import DeyeEnergyManagerEntity

SWITCHES = {
    "enabled": "Enabled",
    "advisory_enabled": "Advisory enabled",
    "deye_control_enabled": "Deye control enabled",
    "grid_charge_control_enabled": "Grid charge control enabled",
    "ev_control_enabled": "EV control enabled",
    "heat_control_enabled": "Heat control enabled",
    "direct_climate_control_enabled": "Direct climate control enabled",
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DeyeFeatureSwitch(coordinator, key, name) for key, name in SWITCHES.items())


class DeyeFeatureSwitch(DeyeEnergyManagerEntity, SwitchEntity):
    """Feature toggle backed by config-entry options."""

    def __init__(self, coordinator, key: str, name: str) -> None:
        super().__init__(coordinator, key, name)
        self._key = key

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.entry.options.get(self._key, FEATURE_DEFAULTS[self._key]))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_option(self._key, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_option(self._key, False)

