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
        "version": "0.5.14",
        "entry": {"entry_id": entry.entry_id, "title": entry.title, "domain": entry.domain},
        "options": _redact(dict(entry.options)),
        "enabled_controls": {
            key: value for key, value in coordinator.settings.__dict__.items() if key.endswith("_enabled")
        },
        "actuation_mode": coordinator.settings.thermal_actuation_mode,
        "thermal_mode": coordinator.settings.thermal_mode,
        "forecast_mode": decision.forecast_mode if decision else None,
        "thermal_policy_state": decision.thermal_policy_state if decision else None,
        "solar_phase": decision.solar_phase if decision else None,
        "paid_grid_avoidance": {
            "required": decision.paid_grid_avoidance_required if decision else None,
            "reason": decision.paid_time_reserve_reason if decision else None,
            "active_reserve_target_soc": decision.active_reserve_target_soc if decision else None,
            "paid_time_floor_soc": decision.paid_time_floor_soc if decision else None,
            "paid_grid_import_w": decision.paid_grid_import_w if decision else None,
            "solar_arrived": decision.solar_arrived if decision else None,
            "solar_arrived_reason": decision.solar_arrived_reason if decision else None,
            "forecast_drain_blocked": decision.forecast_drain_blocked if decision else None,
        },
        "energy_budget": {
            "daily_battery_target_soc": decision.daily_battery_target_soc if decision else None,
            "energy_budget_target_soc": decision.energy_budget_target_soc if decision else None,
            "energy_budget_target_name": decision.energy_budget_target_name if decision else None,
            "remaining_solar_budget_kwh": decision.remaining_solar_budget_kwh if decision else None,
            "battery_kwh_needed_to_target": decision.battery_kwh_needed_to_target if decision else None,
            "expected_house_load_until_solar_end_kwh": decision.expected_house_load_until_solar_end_kwh if decision else None,
            "safety_buffer_kwh": decision.safety_buffer_kwh if decision else None,
            "discretionary_energy_budget_kwh": decision.discretionary_energy_budget_kwh if decision else None,
            "battery_target_reachable_today": decision.battery_target_reachable_today if decision else None,
            "base_load_estimate_w": decision.base_load_estimate_w if decision else None,
            "morning_start_soc_target": decision.morning_start_soc_target if decision else None,
            "evening_peak_soc_target": decision.evening_peak_soc_target if decision else None,
            "projected_4pm_soc": decision.projected_4pm_soc if decision else None,
            "required_4pm_energy_kwh": decision.required_4pm_energy_kwh if decision else None,
            "night_grid_topup_kwh_required": decision.night_grid_topup_kwh_required if decision else None,
            "energy_plan_reason": decision.energy_plan_reason if decision else None,
            "reason": decision.energy_budget_reason if decision else None,
        },
        "cheap_grid": {
            "mode": decision.cheap_grid_mode if decision else None,
            "preserve_required": decision.cheap_grid_preserve_required if decision else None,
            "topup_required": decision.cheap_grid_topup_required if decision else None,
            "morning_target_soc": decision.morning_target_soc if decision else None,
            "preserve_target_soc": decision.cheap_grid_preserve_target_soc if decision else None,
            "grid_charge_required": decision.grid_charge_required if decision else None,
            "grid_charge_target_soc": decision.grid_charge_target_soc if decision else None,
            "reason": decision.cheap_grid_reason if decision else None,
        },
        "deye_writes": {
            "desired_plan": coordinator.desired_deye_plan,
            "applied_plan": coordinator.applied_deye_plan,
            "write_reason": coordinator.deye_write_reason,
            "suppressed_reason": coordinator.deye_write_suppressed_reason,
            "write_count_last_hour": len(coordinator._deye_write_events),
            "thrash_detected": coordinator.deye_write_thrash_detected,
        },
        "underfloor": {
            "allowed": decision.underfloor_comfort_allowed if decision else None,
            "policy_state": decision.underfloor_policy_state if decision else None,
            "reason": decision.underfloor_reason if decision else None,
            "window": decision.underfloor_current_window if decision else None,
            "load_to_add": decision.underfloor_load_to_add if decision else None,
        },
        "ev": {
            "charging_detected": decision.ev_charging_detected if decision else None,
            "grid_bypass_required": decision.ev_grid_bypass_required if decision else None,
            "latch_active": decision.ev_latch_active if decision else None,
            "hold_until": decision.ev_hold_until.isoformat() if decision and decision.ev_hold_until else None,
            "reason": decision.ev_decision_reason if decision else None,
            "expected_action": decision.ev_expected_action if decision else None,
        },
        "battery": {
            "soc": decision.battery_soc if decision else None,
            "raw_soc": decision.raw_soc if decision else None,
            "resolved_soc": decision.resolved_soc if decision else None,
            "soc_source": decision.soc_source if decision else None,
            "soc_age_minutes": decision.soc_age_minutes if decision else None,
            "last_good_soc": decision.last_good_soc if decision else None,
            "last_good_updated": decision.last_good_soc_updated.isoformat() if decision and decision.last_good_soc_updated else None,
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
