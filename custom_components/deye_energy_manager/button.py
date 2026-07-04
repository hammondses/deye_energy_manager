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
    "emergency_shed_all_heat_loads": "Emergency shed all heat loads",
    "clear_ev_latch": "Clear EV latch",
    "force_ev_grid_bypass_start": "Force EV grid bypass start",
    "force_ev_grid_bypass_restore": "Force EV grid bypass restore",
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
        elif self._key == "force_ev_grid_bypass_start":
            if not self._ev_force_allowed():
                await self._blocked("force EV bypass blocked: EV control/grid bypass disabled")
                return
            await self.coordinator.async_force_ev_grid_bypass(True)
        elif self._key == "force_ev_grid_bypass_restore":
            if not self.coordinator.settings.ev_control_enabled:
                await self._blocked("force EV restore blocked: EV control disabled")
                return
            await self.coordinator.async_force_ev_grid_bypass(False)
        elif self._key == "apply_plan_now":
            await self.coordinator.async_apply_decision()
        elif self._key == "restore_deye_normal":
            await self.coordinator.async_restore_deye_normal()
        elif self._key == "force_shed_one_heat_load":
            if not self._thermal_direct_force_allowed():
                await self._blocked("force thermal shed blocked: direct climate control disabled")
                return
            await self.coordinator.async_force_shed_one_heat_load()
        elif self._key == "force_add_one_heat_load":
            if not self._thermal_direct_force_allowed():
                await self._blocked("force thermal add blocked: direct climate control disabled")
                return
            await self.coordinator.async_force_add_one_heat_load()
        elif self._key == "force_test_one_pv_load":
            if not (self.coordinator.settings.pv_load_test_control_enabled and self._thermal_direct_force_allowed()):
                await self._blocked("force PV load test blocked: PV load test/direct climate control disabled")
                return
            await self.coordinator.async_force_test_one_pv_load()
        elif self._key == "force_rotate_heat_load":
            if not self._thermal_direct_force_allowed():
                await self._blocked("force thermal rotate blocked: direct climate control disabled")
                return
            await self.coordinator.async_force_rotate_heat_load()
        elif self._key == "emergency_shed_all_heat_loads":
            if not self._thermal_direct_force_allowed():
                await self._blocked("force thermal emergency shed blocked: direct climate control disabled")
                return
            await self.coordinator.async_force_emergency_shed_all_heat_loads()
        else:
            await self.coordinator.async_request_refresh()

    def _ev_force_allowed(self) -> bool:
        return self.coordinator.settings.ev_control_enabled and self.coordinator.settings.ev_grid_bypass_enabled

    def _thermal_direct_force_allowed(self) -> bool:
        settings = self.coordinator.settings
        return (
            settings.thermal_control_enabled
            and settings.thermal_actuation_mode == "direct"
            and settings.direct_climate_control_enabled
        )

    async def _blocked(self, reason: str) -> None:
        self.coordinator.last_control_action = reason
        await self.coordinator.async_request_refresh()
