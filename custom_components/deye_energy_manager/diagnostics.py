"""Diagnostics support for Deye Energy Manager."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {"token", "password", "secret", "api_key"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    coordinator = hass.data[DOMAIN][entry.entry_id]
    decision = coordinator.data
    return {
        "version": "0.4.1",
        "entry": {"entry_id": entry.entry_id, "title": entry.title, "domain": entry.domain},
        "options": _redact(dict(entry.options)),
        "enabled_controls": {
            key: value for key, value in coordinator.settings.__dict__.items() if key.endswith("_enabled")
        },
        "actuation_mode": coordinator.settings.thermal_actuation_mode,
        "thermal_mode": coordinator.settings.thermal_mode,
        "forecast_mode": decision.forecast_mode if decision else None,
        "battery": {
            "soc": decision.battery_soc if decision else None,
            "power_w": decision.battery_power_w if decision else None,
            "charge_w": decision.battery_charge_w if decision else None,
            "discharge_w": decision.battery_discharge_w if decision else None,
        },
        "entity_map": coordinator.entity_map,
        "managed_thermal_loads": coordinator.heat_loads,
        "per_load_status": {
            slug: {"state": diag.state, "attributes": diag.attributes}
            for slug, diag in coordinator.load_diagnostics.items()
        },
        "last_decision_reason": decision.reason if decision else None,
        "last_control_action": coordinator.last_control_action,
        "recent_proposed_actions": list(coordinator.recent_proposed_actions),
    }


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("REDACTED" if key in TO_REDACT else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
