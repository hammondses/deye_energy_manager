# Deye Energy Manager

Home Assistant custom integration for Deye battery reserve planning, Solcast-aware grid charging, EV grid-bypass policy, solar heat diversion decisions, and diagnostics.

The integration defaults to advisory/read-only behavior:

- `switch.deye_energy_manager_enabled`: on
- `switch.deye_energy_manager_advisory_enabled`: on
- every actuator/control switch: off

Install through HACS as a custom repository after this project is pushed to GitHub:

1. HACS -> Custom repositories
2. Add the repository URL
3. Category: Integration
4. Install `Deye Energy Manager`
5. Restart Home Assistant
6. Settings -> Devices & services -> Add integration -> Deye Energy Manager

## Control Gates

Actual writes are guarded by explicit toggles:

- `switch.deye_energy_manager_deye_control_enabled`
- `switch.deye_energy_manager_grid_charge_control_enabled`
- `switch.deye_energy_manager_ev_control_enabled`
- `switch.deye_energy_manager_heat_control_enabled`
- `switch.deye_energy_manager_direct_climate_control_enabled`
- `switch.deye_energy_manager_pv_load_test_control_enabled`

Leave these off until advisory sensors match the current automations.

## PV Load Testing

When inverter export is disabled or clipped, observed battery charge can understate available PV. The integration exposes:

- `switch.deye_energy_manager_export_limited_mode_enabled`
- `binary_sensor.deye_energy_manager_pv_load_test_recommended`
- `switch.deye_energy_manager_pv_load_test_control_enabled`

The recommendation becomes true only when expected PV is high, remaining forecast is healthy, battery SOC is above the configured test floor, observed battery charge is still low, and no solar-owned heat load is already on. The integration will not automatically test a load unless `pv_load_test_control_enabled` is explicitly turned on.

When a solar-owned room is close to target and another managed room is materially below target, the integration also exposes:

- `binary_sensor.deye_energy_manager_heat_rotation_recommended`
- `sensor.deye_energy_manager_heat_load_to_shed`
- `sensor.deye_energy_manager_heat_load_to_add`

This is for heat pumps that taper after reaching setpoint. In direct-control mode it can shed the satisfied room and add the colder room, but only when heat control, direct climate control, export-limited mode, and PV load-test control are all explicitly enabled.

## Heat Safety Features

Manual override cleanup:

- If a manager-owned climate is manually turned off, ownership is cleared.
- If a manager-owned heat target is lowered below the configured solar target, ownership is cleared.
- That load is blocked from automatic re-add until `manual_override_cooldown_min` expires.

Emergency shed-all:

- `binary_sensor.deye_energy_manager_emergency_shed_all_required`
- `number.deye_energy_manager_emergency_shed_discharge_w`

When battery discharge exceeds the emergency threshold, all manager-owned heat loads are shed immediately in direct-control mode, and their ownership flags are cleared. Script mode calls `script.deye_energy_manager_emergency_shed_all_heat_loads`.

Overnight protection:

- `sensor.deye_energy_manager_projected_soc_08`
- `binary_sensor.deye_energy_manager_overnight_protection_required`
- `binary_sensor.deye_energy_manager_bedroom_heat_taper_recommended`

The integration projects SOC at 08:00 from current discharge and configured battery capacity. If projected SOC falls below the morning reserve target, it recommends shedding nonessential heat. Owned bedroom heat can be tapered to `overnight_bedroom_taper_target_temp`.

## Agentic Editing

The integration is intentionally organized so ChatGPT or another HA MCP-capable agent can discover and edit behavior:

- Pure policy logic: `custom_components/deye_energy_manager/decision.py`
- Pure dataclasses: `custom_components/deye_energy_manager/models.py`
- HA state collection and safe writes: `custom_components/deye_energy_manager/coordinator.py`
- Feature toggles and thresholds: `custom_components/deye_energy_manager/const.py`
- Home Assistant config/options flow: `custom_components/deye_energy_manager/config_flow.py`
- Pure tests: `tests/components/deye_energy_manager/test_decision.py`

Use `AGENTS.md` as the editing map for future agent sessions.

## Local Test

```bash
python3 -m pytest
```
