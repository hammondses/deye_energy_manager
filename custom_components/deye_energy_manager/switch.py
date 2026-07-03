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
    "ev_grid_bypass_enabled": "EV grid bypass enabled",
    "ev_solar_charging_enabled": "EV solar charging enabled",
    "ev_cheap_grid_charging_enabled": "EV cheap grid charging enabled",
    "heat_control_enabled": "Heat control enabled",
    "thermal_control_enabled": "Thermal control enabled",
    "direct_climate_control_enabled": "Direct climate control enabled",
    "pv_load_test_control_enabled": "PV load test control enabled",
    "export_limited_mode_enabled": "Export limited mode enabled",
    "return_to_normal_on_shed_enabled": "Return to normal on shed enabled",
    "forecast_full_override_enabled": "Forecast full override enabled",
    "thermal_rotation_enabled": "Thermal rotation enabled",
    "shed_unowned_managed_loads_on_battery_discharge": "Shed unowned managed loads on battery discharge",
    "morning_preheat_enabled": "Morning preheat enabled",
    "passive_warming_guard_enabled": "Passive warming guard enabled",
    "paid_time_grid_avoidance_enabled": "Paid time grid avoidance enabled",
    "underfloor_schedule_enabled": "Underfloor schedule enabled",
    "underfloor_require_home": "Underfloor require home",
    "underfloor_allow_paid_grid": "Underfloor allow paid grid",
    "dynamic_base_load_estimate_enabled": "Dynamic base load estimate enabled",
    "auto_mode_month_fallback_enabled": "Auto mode month fallback enabled",
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
