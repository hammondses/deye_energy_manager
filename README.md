# Deye Energy Manager

Home Assistant custom integration for Deye battery reserve planning, Solcast-aware grid charging, EV grid-bypass policy, thermal storage control, and diagnostics.

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
- `switch.deye_energy_manager_thermal_control_enabled`
- `switch.deye_energy_manager_heat_control_enabled`
- `switch.deye_energy_manager_direct_climate_control_enabled`
- `switch.deye_energy_manager_pv_load_test_control_enabled`

Leave these off until advisory sensors match the current automations.

Options are split into sections in the integration UI:

- Controls
- Thermal
- EV
- Battery
- Managed Loads
- Entity Mapping
- Legacy

## Thermal Storage

The integration now owns native thermal storage decisions and direct climate actuation.

- `select.deye_energy_manager_thermal_mode`: `heating`, `cooling`, `auto`, `off`
- `select.deye_energy_manager_thermal_actuation_mode`: `advisory`, `scripts`, `direct`
- `number.deye_energy_manager_heat_soak_target_temp`
- `number.deye_energy_manager_heat_normal_target_temp`
- `number.deye_energy_manager_cool_soak_target_temp`
- `number.deye_energy_manager_cool_normal_target_temp`
- `number.deye_energy_manager_thermal_start_min_soc`
- `number.deye_energy_manager_thermal_start_min_charge`
- `number.deye_energy_manager_thermal_keep_running_min_charge`
- `number.deye_energy_manager_thermal_shed_discharge`
- `number.deye_energy_manager_thermal_emergency_shed`

Thermal permission uses the thermal thresholds, not the 17:00 battery target. On excellent/good forecast days, `forecast_full_override` can allow thermal soaking earlier when remaining Solcast energy is enough to reach the battery target plus buffer.

Actuation modes:

- `advisory`: decisions only, no service calls
- `scripts`: compatibility bridge to external scripts
- `direct`: integration directly controls climates and ownership booleans

When `thermal_actuation_mode` is `direct` and direct climate control is enabled, the integration directly controls managed climates:

- Heating soak: HVAC `heat`, target `heat_soak_target_temp`
- Heating normalise: HVAC `heat`, target `heat_normal_target_temp`
- Cooling soak: HVAC `cool`, target `cool_soak_target_temp`
- Cooling normalise: HVAC `cool`, target `cool_normal_target_temp`
- Underfloor loads are heating-only and turn off on shed.

Script mode remains available as a compatibility fallback. Legacy `heat_*` entities remain as compatibility aliases, but `thermal_*` entities are preferred.

## EV Charging

EV support is native to the integration and disabled by default.

- `switch.deye_energy_manager_ev_control_enabled`
- `switch.deye_energy_manager_ev_grid_bypass_enabled`
- `switch.deye_energy_manager_ev_solar_charging_enabled`
- `switch.deye_energy_manager_ev_cheap_grid_charging_enabled`
- `number.deye_energy_manager_ev_start_load_jump`
- `number.deye_energy_manager_ev_stop_load_drop`
- `number.deye_energy_manager_ev_active_load_threshold`
- `number.deye_energy_manager_ev_stopped_load_threshold`
- `number.deye_energy_manager_ev_restore_program_power`

Cheap-grid EV bypass detects charging from an optional EV power sensor first, then falls back to essential-load jumps/high load and Porsche signals. When enabled during the cheap window, it sets Deye programme powers 6/1/2/3 to `0`; when EV charging stops, it restores them to `ev_restore_program_power_w`.

EV bypass wins over battery grid charging so the system does not create a battery charge/discharge loop while the car is using cheap grid power.

## Diagnostics And Tuning

The integration exposes one thermal status sensor per managed load, for example:

- `sensor.deye_energy_manager_dining_thermal_status`
- `sensor.deye_energy_manager_bedroom_thermal_status`
- `sensor.deye_energy_manager_office_thermal_status`
- `sensor.deye_energy_manager_hallway_thermal_status`
- `sensor.deye_energy_manager_underfloor_thermal_status`

Each status sensor includes attributes for room temperature, target, ownership, active/tapering state, cooldowns, chosen/not-chosen reasons, and last action timestamps.

Load diagnostic entity IDs use the managed-load `slug`, not the display name. The default slugs are `dining`, `bedroom`, `office`, `hallway`, and `underfloor`.

Legacy heat controls remain as compatibility aliases during the thermal cutover. If `heat_control_enabled` is on, `thermal_control_enabled` is migrated on; `heat_mode = auto_scripts` maps to `thermal_actuation_mode = scripts`, and `heat_mode = auto_direct` maps to `thermal_actuation_mode = direct`. New installs should use the thermal controls directly.

Fan mode controls:

- `select.deye_energy_manager_heat_soak_fan_mode`
- `select.deye_energy_manager_heat_normal_fan_mode`
- `select.deye_energy_manager_cool_soak_fan_mode`
- `select.deye_energy_manager_cool_normal_fan_mode`

Direct thermal control sets soak fan modes before ownership is marked on, and normal fan modes when returning a heat pump to comfort temperature. Fan mode service calls are skipped if the climate does not expose `fan_modes` or if the selected mode is not supported; the per-load diagnostics explain the skip reason.

Cooldown protection:

- `number.deye_energy_manager_min_thermal_run_minutes`
- `number.deye_energy_manager_min_thermal_rest_minutes`
- `number.deye_energy_manager_thermal_rotation_cooldown_minutes`

Emergency shed bypasses cooldowns.

Battery-discharge safety shedding:

- `switch.deye_energy_manager_shed_unowned_managed_loads_on_battery_discharge`

This is off by default. When enabled, battery discharge above the thermal shed threshold can normalise a configured managed heat pump that looks like it is still in a soak state even if its ownership boolean is off. It never acts on climate entities outside the configured managed-load list, and it does not include underfloor loads.

Last-known-good SOC fallback:

- `primary_soc_entity`: defaults to `sensor.deye_battery_soc`
- `fallback_soc_entity`: defaults to `input_number.deye_battery_soc_last_good`
- `fallback_soc_timestamp_entity`: defaults to `input_datetime.deye_battery_soc_last_good_updated`
- `number.deye_energy_manager_max_fallback_soc_age_minutes`: defaults to `360`
- `sensor.deye_energy_manager_soc_source`
- `sensor.deye_energy_manager_soc_age_minutes`

The integration uses live local Deye SOC when numeric. If live SOC is `unknown`/`unavailable`, it can use the local helper value while the timestamp is fresh. It does not use cloud/Solarman SOC entities by default, and it never converts unknown SOC to `0`.

Home Assistant may prefix these entities with the config entry name, for example `sensor.garage_deye_energy_manager_soc_source`. The `input_number` and `input_datetime` fallback helpers are external Home Assistant helpers; the integration reads them but does not create them automatically.

Optional helper example:

```yaml
input_number:
  deye_battery_soc_last_good:
    name: Deye battery SOC last good
    min: 0
    max: 100
    step: 0.1

input_datetime:
  deye_battery_soc_last_good_updated:
    name: Deye battery SOC last good updated
    has_date: true
    has_time: true

automation:
  - alias: Deye battery SOC last-known-good
    triggers:
      - trigger: state
        entity_id: sensor.deye_battery_soc
    conditions:
      - condition: template
        value_template: "{{ states('sensor.deye_battery_soc') | is_number }}"
    actions:
      - action: input_number.set_value
        target:
          entity_id: input_number.deye_battery_soc_last_good
        data:
          value: "{{ states('sensor.deye_battery_soc') | float }}"
      - action: input_datetime.set_datetime
        target:
          entity_id: input_datetime.deye_battery_soc_last_good_updated
        data:
          datetime: "{{ now().isoformat() }}"
```

Dry-run visibility:

- `sensor.deye_energy_manager_recent_proposed_actions`

The sensor attributes include the last 10 proposed actions with subsystem, actuation mode, target, reason, and blocked reason.

Diagnostics download and Home Assistant Repairs are supported for common setup issues such as missing climates, missing scripts in script mode, invalid EV power sensors, and missing Deye programme power entities.

`thermal_mode = auto` can use an optional outdoor temperature sensor, with Southern Hemisphere month fallback:

- Heating fallback: March-November shoulder/heating, especially April-October
- Cooling fallback: December-February

## Release Notes v0.4.0

- Thermal storage controls
- Heating/cooling thermal mode
- Heat/cool soak and normal target temps
- Forecast-full override
- Direct/script/advisory actuation modes
- EV cheap-grid bypass scaffolding/control
- Direct climate control safety gates
- Per-load thermal diagnostics
- Thermal cooldown and anti-short-cycle protection
- Repairs and diagnostics support
- Recent proposed action log
- Existing managed load editor
- Outdoor/season thermal auto mode

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
