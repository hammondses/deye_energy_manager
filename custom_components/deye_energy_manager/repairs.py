"""Repair issue helpers for Deye Energy Manager."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from .const import PROG_CAPACITY_ENTITIES, PROG_POWER_ENTITIES


async def async_update_issues(hass: HomeAssistant, coordinator) -> None:
    """Create or clear actionable repair issues."""

    from homeassistant.helpers import issue_registry as ir

    issues = repair_issue_definitions(
        coordinator.settings,
        coordinator.entity_map,
        coordinator.heat_loads,
        lambda entity_id: hass.states.get(entity_id) is not None,
    )
    for issue_id, payload in issues.items():
        _issue(ir, hass, issue_id, True, payload["title"], payload["fix"])

    for issue_id in REPAIR_ISSUE_IDS - issues.keys():
        _issue(ir, hass, issue_id, False, "", "")


REPAIR_ISSUE_IDS = {
    "missing_required_deye_entity",
    "missing_solcast_forecast_entity",
    "climate_entity_unavailable",
    "ownership_helper_missing",
    "power_sensor_invalid",
    "direct_no_climates",
    "thermal_enabled_mode_off",
    "scripts_retired",
    "ev_power_invalid",
    "ev_bypass_missing_deye_power_entities",
    "ev_cheap_grid_bypass_disabled",
    "paid_grid_avoidance_no_capacity_entities",
    "porsche_entity_unavailable",
}


def repair_issue_definitions(
    settings,
    entity_map: dict[str, str],
    heat_loads: list[dict[str, object]],
    state_exists: Callable[[str], bool],
) -> dict[str, dict[str, str]]:
    """Return active repair issues from plain settings and entity availability."""

    issues: dict[str, dict[str, str]] = {}
    required_deye_entities = [
        entity_map.get("primary_soc_entity") or entity_map.get("battery_soc", ""),
        entity_map.get("battery_power", ""),
        entity_map.get("essential_power", ""),
    ]
    missing_deye = [entity_id for entity_id in required_deye_entities if entity_id and not state_exists(entity_id)]
    if missing_deye:
        issues["missing_required_deye_entity"] = {
            "title": "Required Deye entity is unavailable",
            "fix": f"Update the Deye entity mapping or restore the missing entity: {', '.join(missing_deye)}.",
        }

    missing_solcast = [
        entity_map.get(key, "")
        for key in ("forecast_tomorrow", "forecast_remaining_today")
        if entity_map.get(key) and not state_exists(entity_map[key])
    ]
    if missing_solcast:
        issues["missing_solcast_forecast_entity"] = {
            "title": "Solcast forecast entity is unavailable",
            "fix": f"Update the Solcast entity mapping or restore the missing entity: {', '.join(missing_solcast)}.",
        }

    enabled_loads = [load for load in heat_loads if bool(load.get("enabled", True))]
    missing_climates = [
        str(load.get("climate_entity", ""))
        for load in enabled_loads
        if str(load.get("climate_entity", "")) and not state_exists(str(load.get("climate_entity", "")))
    ]
    if missing_climates:
        issues["climate_entity_unavailable"] = {
            "title": "Managed climate entity is unavailable",
            "fix": f"Fix or disable the managed load using: {', '.join(missing_climates)}.",
        }

    missing_ownership = [
        str(load.get("ownership_entity", ""))
        for load in enabled_loads
        if str(load.get("ownership_entity", "")) and not state_exists(str(load.get("ownership_entity", "")))
    ]
    if missing_ownership:
        issues["ownership_helper_missing"] = {
            "title": "Thermal ownership helper is missing",
            "fix": f"Create or remap the ownership helper: {', '.join(missing_ownership)}.",
        }

    invalid_power_sensors = [
        str(load.get("optional_power_sensor", ""))
        for load in enabled_loads
        if str(load.get("optional_power_sensor", "")) and not state_exists(str(load.get("optional_power_sensor", "")))
    ]
    if invalid_power_sensors:
        issues["power_sensor_invalid"] = {
            "title": "Managed load power sensor is unavailable",
            "fix": f"Update or clear the optional power sensor: {', '.join(invalid_power_sensors)}.",
        }

    if (
        settings.thermal_actuation_mode == "direct"
        and settings.direct_climate_control_enabled
        and not any(str(load.get("climate_entity", "")) and state_exists(str(load.get("climate_entity", ""))) for load in enabled_loads)
    ):
        issues["direct_no_climates"] = {
            "title": "Direct thermal control has no available climates",
            "fix": "Configure at least one managed thermal load with an available climate entity or disable direct climate control.",
        }

    if settings.thermal_control_enabled and settings.thermal_mode == "off":
        issues["thermal_enabled_mode_off"] = {
            "title": "Thermal control is enabled but thermal mode is off",
            "fix": "Set thermal mode to heating, cooling, or auto, or disable thermal control.",
        }

    if settings.thermal_actuation_mode == "scripts":
        issues["scripts_retired"] = {
            "title": "Thermal script actuation has been retired",
            "fix": "Switch thermal actuation mode to direct with direct climate control enabled, or use advisory mode.",
        }

    if entity_map.get("ev_power") and not state_exists(entity_map["ev_power"]):
        issues["ev_power_invalid"] = {
            "title": "EV power sensor is configured but unavailable",
            "fix": "Update the EV power sensor mapping or clear it from the integration options.",
        }

    ev_bypass_power_entities = [PROG_POWER_ENTITIES[5], PROG_POWER_ENTITIES[0], PROG_POWER_ENTITIES[1], PROG_POWER_ENTITIES[2]]
    if settings.ev_control_enabled and settings.ev_grid_bypass_enabled and any(
        not state_exists(entity_id) for entity_id in ev_bypass_power_entities
    ):
        issues["ev_bypass_missing_deye_power_entities"] = {
            "title": "EV grid bypass is missing Deye programme power entities",
            "fix": "Make sure number.deye_prog6_power, number.deye_prog1_power, number.deye_prog2_power, and number.deye_prog3_power are available.",
        }

    if settings.ev_control_enabled and settings.ev_cheap_grid_charging_enabled and not settings.ev_grid_bypass_enabled:
        issues["ev_cheap_grid_bypass_disabled"] = {
            "title": "EV cheap-grid charging is enabled but EV grid bypass is disabled",
            "fix": "Enable EV grid bypass if the integration should set Deye programme powers to 0W during cheap-grid car charging.",
        }

    porsche_entities = [
        entity_map.get(key, "")
        for key in ("porsche_soc", "porsche_charging_status", "porsche_charging_ends")
        if entity_map.get(key)
    ]
    if settings.ev_control_enabled and porsche_entities and all(not state_exists(entity_id) for entity_id in porsche_entities):
        issues["porsche_entity_unavailable"] = {
            "title": "Configured Porsche entities are unavailable",
            "fix": "Restore the Porsche integration entities or clear those mappings if EV detection should use load sensing only.",
        }

    if settings.paid_time_grid_avoidance_enabled and settings.deye_control_enabled and any(
        not state_exists(entity_id) for entity_id in PROG_CAPACITY_ENTITIES
    ):
        issues["paid_grid_avoidance_no_capacity_entities"] = {
            "title": "Paid grid avoidance cannot write Deye capacity entities",
            "fix": "Restore the Deye programme capacity number entities or disable Deye control.",
        }

    return issues


def _issue(ir, hass: HomeAssistant, issue_id: str, active: bool, title: str, fix: str) -> None:
    if active:
        ir.async_create_issue(
            hass,
            "deye_energy_manager",
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=issue_id,
            translation_placeholders={"title": title, "fix": fix},
        )
    else:
        ir.async_delete_issue(hass, "deye_energy_manager", issue_id)
