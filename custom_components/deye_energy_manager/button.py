"""Button platform for Deye Energy Manager commands."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DeyeEnergyManagerEntity

BUTTONS = {
    "apply_plan_now": "Apply plan now",
    "recalculate_now": "Recalculate now",
    "restore_deye_normal": "Restore Deye normal",
    "force_shed_one_heat_load": "Force shed one heat load",
    "force_add_one_heat_load": "Force add one heat load",
    "force_test_one_pv_load": "Force test one PV load",
    "force_rotate_heat_load": "Force rotate heat load",
    "clear_ev_latch": "Clear EV latch",
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(DeyeCommandButton(coordinator, key, name) for key, name in BUTTONS.items())


class DeyeCommandButton(DeyeEnergyManagerEntity, ButtonEntity):
    def __init__(self, coordinator, key: str, name: str) -> None:
        super().__init__(coordinator, key, name)
        self._key = key

    async def async_press(self) -> None:
        if self._key == "clear_ev_latch":
            await self.coordinator.async_clear_ev_latch()
        elif self._key == "apply_plan_now":
            await self.coordinator.async_apply_decision()
        elif self._key == "force_shed_one_heat_load":
            await self.coordinator.hass.services.async_call("script", "deye_energy_manager_shed_one_heat_load", {}, blocking=False)
        elif self._key == "force_add_one_heat_load":
            await self.coordinator.hass.services.async_call("script", "deye_energy_manager_add_one_heat_load", {}, blocking=False)
        elif self._key == "force_test_one_pv_load":
            await self.coordinator.hass.services.async_call("script", "deye_energy_manager_add_one_heat_load", {}, blocking=False)
        elif self._key == "force_rotate_heat_load":
            await self.coordinator.hass.services.async_call("script", "deye_energy_manager_shed_one_heat_load", {}, blocking=False)
            await self.coordinator.hass.services.async_call("script", "deye_energy_manager_add_one_heat_load", {}, blocking=False)
        else:
            await self.coordinator.async_request_refresh()
