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

Leave these off until advisory sensors match the current automations.

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

