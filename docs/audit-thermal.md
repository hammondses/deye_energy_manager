# Thermal, Heat, Night Comfort, and PV Load-Test Audit

Date: 2026-09-12
Source checked: `v0.5.69` merged into this worktree.

This is audit-only documentation. No Home Assistant config, deployment, or code behavior was changed.

## Short Answer

Do not rewrite the whole integration first. Keep the integration as the inverter/SOC/forecast/grid-charge/EV arbiter, then peel off bedroom comfort and other simple room behaviors into Home Assistant automations.

The current source has already gutted much of the old thermal matrix: comfort heat, morning preheat, underfloor comfort, overnight dining comfort, rotation, overnight protection, bedroom taper, and emergency thermal shed are still calculated or surfaced for compatibility, but the current decision path forces them off as actuator selectors. Thermal control is now deliberately narrowed to curtailment soak/PV load testing (`custom_components/deye_energy_manager/decision.py:2225`).

Live HA context from the latest check:

- `thermal_control_enabled` / `heat_control_enabled` are off.
- `direct_climate_control_enabled` is on.
- Bedroom night heating was off/disarmed at inspection, but history shows it repeatedly active overnight Sep 6-12. Last observed policy-active session was Sep 12 01:47 to 12:00 NZST. Policy sensors alone do not prove the bedroom climate physically heated.
- The bedroom heat pump itself works fine.
- Live bedroom target was 17C, paid-import disarm threshold was 500W, and the calculated morning target was 20% at inspection. The morning target is dynamic, so do not hard-code 20% into a replacement automation.
- `Bedroom Button Double Press` toggles `switch.garage_deye_energy_manager_bedroom_night_heating_armed`.
- Old Solar Heat automations, solar export heating recovery, and watchdog are off.
- Underfloor and morning-preheat feature toggles are on, but their outer thermal gate is off, so they do not actuate through this manager.

## Public Surface That Can Break Automations

The integration still exposes a wide HA entity surface. Switches include thermal/heat/direct climate, curtailment soak/PV load test, inverter cooling, cooling hunt/protection, export-constrained mode, rotation, unowned shed, morning preheat, overnight dining, underfloor, and related feature gates (`custom_components/deye_energy_manager/switch.py:13`).

It exposes command buttons for apply/recalculate/restore, force thermal add/shed/rotate, force PV load test, emergency shed all, and EV controls (`custom_components/deye_energy_manager/button.py:13`). Those force thermal buttons are blocked unless thermal control, direct actuation, and direct climate control are all enabled (`custom_components/deye_energy_manager/button.py:58`, `custom_components/deye_energy_manager/button.py:89`).

It exposes sensors and binary sensors for cooling, bedroom night heating, old thermal policy diagnostics, curtailment soak, morning preheat, overnight dining, underfloor, add/shed targets, and recent proposed actions (`custom_components/deye_energy_manager/sensor.py:69`, `custom_components/deye_energy_manager/sensor.py:91`, `custom_components/deye_energy_manager/sensor.py:100`, `custom_components/deye_energy_manager/binary_sensor.py:23`).

Default configured heat-load ownership helpers are still dining, underfloor, office, bedroom, and hallway (`custom_components/deye_energy_manager/const.py:78`). The external fan and cooling telemetry defaults now include fan status/RPM and inverter max sell/solar power entities (`custom_components/deye_energy_manager/const.py:55`).

## Gates and Defaults

Actuator defaults remain conservative: Deye, grid charge, EV, heat, thermal, direct climate, PV load test / curtailment soak, inverter cooling, cooling hunt, cooling fan failure protection, and export-constrained mode all default off (`custom_components/deye_energy_manager/const.py:217`).

Some old policy toggles default on even though the outer thermal gate defaults off: return-to-normal, forecast-full override, rotation, morning preheat, passive warming guard, paid-time grid avoidance, underfloor schedule, dynamic base-load estimate, and auto-mode month fallback (`custom_components/deye_energy_manager/const.py:237`).

`heat_control_enabled` and `thermal_control_enabled` still mirror each other when options are changed (`custom_components/deye_energy_manager/coordinator.py:1238`). Recent proposed-action metadata says thermal would actuate only when thermal control, direct actuation mode, and direct climate control are all enabled (`custom_components/deye_energy_manager/coordinator.py:1172`).

The apply loop is different for bedroom night heating: it calls `_apply_bedroom_night_heating()` unconditionally after inverter/EV/Deye writes and before `_apply_heat()` (`custom_components/deye_energy_manager/coordinator.py:1325`). That means bedroom night heating can physically run with the outer thermal gate off, as long as the manager is enabled and direct climate control is on.

## Current Bedroom Night Heating Contract

Preferred destination: Home Assistant automation. The behavior is useful and the bedroom heat pump works; it does not need to live inside the energy manager. Preserve the existing wall-button flow and cutoffs while moving it.

Current source contract:

- Arm/disarm is a runtime switch named `bedroom_night_heating_armed`, persisted in coordinator runtime state (`custom_components/deye_energy_manager/switch.py:79`, `custom_components/deye_energy_manager/coordinator.py:123`, `custom_components/deye_energy_manager/coordinator.py:193`).
- Live automation dependency: `Bedroom Button Double Press` toggles `switch.garage_deye_energy_manager_bedroom_night_heating_armed`.
- If disarmed, manager disabled, or outside 17:00-12:00, it is inactive. Outside 17:00-12:00 it asks to disarm (`custom_components/deye_energy_manager/decision.py:744`).
- From 07:00-12:00, paid grid import above `paid_grid_import_threshold_w` disarms it (`custom_components/deye_energy_manager/decision.py:759`).
- From 09:00-12:00, if solar has not arrived and SOC is unavailable or at/below the calculated morning target, it disarms for unsafe recovery (`custom_components/deye_energy_manager/decision.py:762`).
- While active it reports target `overnight_bedroom_taper_target_temp`, default 17C (`custom_components/deye_energy_manager/decision.py:770`, `custom_components/deye_energy_manager/const.py:352`).
- It suppresses cheap-grid battery charging while armed; cheap-grid preserve still applies (`custom_components/deye_energy_manager/decision.py:661`, `custom_components/deye_energy_manager/decision.py:673`, `custom_components/deye_energy_manager/decision.py:723`).
- If direct climate control is off, it only reports blocked and does not write (`custom_components/deye_energy_manager/coordinator.py:1799`).
- If tariff window is `free_power`, bedroom writes are skipped and `_bedroom_night_setup_applied` is reset, so the next non-free-power active pass performs setup again (`custom_components/deye_energy_manager/coordinator.py:1796`).
- On first physical apply, it calls `_direct_shed_all_heat_loads(... include_unowned=True, exclude_bedroom=True)`, so it turns off other configured heat loads before setting the bedroom (`custom_components/deye_energy_manager/coordinator.py:1802`).
- Then it sets the bedroom climate to heat, target 17C by default, turns on the bedroom ownership helper, and writes a `bedroom_night_heating` lease (`custom_components/deye_energy_manager/coordinator.py:1808`, `custom_components/deye_energy_manager/coordinator.py:2010`).
- Manual disarm can turn the bedroom climate off when direct climate control is enabled (`custom_components/deye_energy_manager/coordinator.py:1276`, `custom_components/deye_energy_manager/coordinator.py:1787`).

Important distinction for review: bedroom night heating does not need `thermal_control_enabled` / `heat_control_enabled`; the old general thermal path does. With the live state you observed, this explains why bedroom night can remain policy-active and can still write if direct climate is on, while underfloor/morning-preheat/general thermal stay inert.

HA automation target:

- Trigger: existing double-press automation toggles an `input_boolean` or helper equivalent.
- Start action while armed and within 17:00-12:00: set `climate.bedroom_heatpump` to heat and 17C.
- Stop/disarm actions: 12:00 cutoff; 07:00-12:00 paid import above the configured threshold; 09:00-12:00 unsafe recovery if solar has not arrived and SOC <= the live morning target; manual toggle off.
- Preserve a reason sensor/helper if dashboards currently use `sensor.garage_deye_energy_manager_bedroom_night_heating_reason`.
- Preserve the cheap-grid suppression input. The current manager suppresses cheap-grid battery charging while bedroom night heating is armed, so the replacement helper must remain visible to the inverter/cheap-grid policy or the policy needs an explicit equivalent condition.
- Do not blindly preserve the current other-room shed. The manager currently turns off other configured heat loads before bedroom setup, but the desired migration should remove heat shedding unless there is a deliberate, reviewed HA automation for it.

## Current Thermal / PV Curtailment Path

The newest source keeps old calculations for diagnostics, then overrides the actuator decision. Current thermal control is explicitly "one job": absorb PV that cannot be exported or accepted by the battery (`custom_components/deye_energy_manager/decision.py:2225`).

Curtailment signal requires: manager enabled, thermal control enabled, export-constrained mode enabled, heating mode, heat loads available, cooldown passed, SOC known and at/above `pv_load_test_min_soc`, current expected PV forecast power above `pv_load_test_min_expected_power_w`, battery charge at/below `pv_load_test_max_battery_charge_w`, battery discharge below 200W, grid import within tolerance, and export at/below keep threshold (`custom_components/deye_energy_manager/decision.py:2249`).

`pv_load_test_recommended` is now active again when that signal is present, there are no currently managed curtailment loads, and a needy candidate exists (`custom_components/deye_energy_manager/decision.py:2264`). The old audit note saying it was retired is stale for `v0.5.69`.

Physical add is still tightly gated: `_apply_heat()` only calls `_direct_add_one_heat_load()` when actuation mode is direct, direct climate control is enabled, `pv_load_test_control_enabled` is true, action is `add_one`, and a target load exists (`custom_components/deye_energy_manager/coordinator.py:1752`).

With live thermal/heat gates off, curtailment soak does not actuate today even though direct climate is on.

Recommendation: keep curtailment/PV soak only if export limiting actually still creates clipped energy you want to absorb. If export is generally allowed now, this should be advisory or removed after checking automations using the curtailment sensors/buttons.

## Retired-In-Practice Thermal Features

Morning preheat, overnight dining comfort, underfloor comfort, comfort heat, thermal rotation, overnight protection, bedroom taper, and emergency thermal shed are forced off after diagnostics in the current decision path (`custom_components/deye_energy_manager/decision.py:2281`). Their switches/sensors still exist, and live HA shows underfloor/morning-preheat toggles on, but the outer thermal gate is off.

Recommendation: move underfloor schedule and any wanted morning bedroom preheat to HA automations. Remove the manager copies after checking automations/dashboards. The useful bedroom behavior should become its own HA automation rather than being merged into generic preheat.

## Inverter Cooling

The fan recommendation still uses throughput, AC temperature, trend, load-change feedback, emergency temperature, optional minimum hunt, and failsafe behavior (`custom_components/deye_energy_manager/decision.py:42`, `custom_components/deye_energy_manager/decision.py:118`).

Newer source also has external fan-failure protection: if enabled and fan telemetry is failed while the inverter remains hot long enough, the coordinator latches protection, sets max sell/solar power to 0, applies a Deye pass-through plan, and requires restore-normal after checking fans (`custom_components/deye_energy_manager/decision.py:195`, `custom_components/deye_energy_manager/coordinator.py:1335`, `custom_components/deye_energy_manager/coordinator.py:1447`).

User finding: the inverter has internal fans that trigger at 50C and turn off around 40C, independent of this integration. That makes the external fan curve a poor fit as an energy-manager concern.

Recommendation: remove automatic external fan curve from this integration, or reduce it to a simple HA hysteresis automation if external fans still help. Treat fan-failure inverter protection as a separate safety decision: keep only if the external fan telemetry is reliable and the max-sell/max-solar writes are genuinely wanted.

## Keep / Move / Remove

Keep in this integration:

- Deye programme percentage/select/power writes, grid-charge switch writes, conflict checks, write cooldown/thrash protection (`custom_components/deye_energy_manager/coordinator.py:1666`).
- SOC/forecast reserve planning, cheap-grid preserve/top-up, paid-grid reserve protection, EV grid-bypass/solar charging/manual charging, and last-known-good SOC.
- Curtailment soak only if the live system still has real export clipping to solve.

Move to Home Assistant automations:

- Bedroom night heating, preserving the button, cutoffs, target, reason visibility, and cheap-grid suppression input. Treat the current "turn off other rooms first" behavior as heat shedding to remove unless deliberately re-approved.
- Underfloor schedule.
- Morning preheat, if still desired.
- Simple external fan hysteresis, if external fans remain useful.

Remove after dependency check:

- Old general solar heat soak, room comfort heat, rotation, ordinary/emergency thermal shedding, unowned shedding, overnight dining comfort, bedroom taper, generic climate fan-mode selects, and legacy `heat_control_enabled` / `heat_mode` compatibility.
- PV/curtailment entities if export-limited clipping is no longer a real use case.

## HA Dependency Check Before Deleting

Search live HA for:

- `switch.garage_deye_energy_manager_bedroom_night_heating_armed`
- `sensor.garage_deye_energy_manager_bedroom_night_heating_reason`
- `binary_sensor.garage_deye_energy_manager_bedroom_night_heating_active`
- `switch.*thermal*`, `switch.*heat*`, `switch.*curtailment*`, `switch.*pv_load_test*`, `switch.*inverter_cooling*`
- `sensor.*thermal*`, `sensor.*cooling*`, `sensor.*underfloor*`, `sensor.*morning_preheat*`, `sensor.*overnight_dining*`
- `button.*force_*heat*`, `button.*force_test_one_pv_load`, `button.*emergency_shed_all_heat_loads`
- Ownership helpers: `input_boolean.solar_owns_dining_heatpump`, `input_boolean.solar_owns_underfloor`, `input_boolean.solar_owns_office_heatpump`, `input_boolean.solar_owns_bedroom_heatpump`, `input_boolean.solar_owns_hallway_heatpump`
- External fan/control entities: `fan.deye_external_fans_cooling_fans`, `binary_sensor.garage_deye_external_fans_device_status`, `sensor.garage_deye_external_fans_cooling_fan_rpm`

The smallest safe path: migrate bedroom night heating to HA automation first, because it is live and useful. Then delete the old room-thermal machinery once dashboards and automations no longer reference its entity surface.
