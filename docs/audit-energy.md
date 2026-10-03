# Energy/control audit

Scope: this audit covers the refreshed repo source for the core energy path: forecast/SOC planning, paid-time reserve lowering, cheap-grid charging, Deye programme writes, EV charger/Taycan/WiCAN handling, and export-limited/curtailment leftovers. It does not audit cooling internals or prove which Home Assistant automations still consume published entities; live-use notes below come from the operator handoff, not from this repo.

## Short answer

Gut this system, do not restart it first. The useful spine is still there: `decision.py` computes one pure decision, `build_deye_plan()` converts that decision into Deye writes, and `coordinator.py` owns the HA service calls behind feature gates. A rewrite would mostly recreate that actuator boundary and then rediscover old HA entity contracts.

The smallest safe path is to keep the inverter/EV spine, freeze the entity names that HA automations read, and delete or split the policy chunks around it once live dependencies are checked.

Keep now:

- Forecast tiering, 7am/4pm SOC targets, paid-time discharge restore, cheap-grid top-up/preserve, Deye programme mapping, write suppression, and conflict checks.
- EV solar/manual charging and WiCAN SOC support while live HA automations and scripts depend on those entities.
- Advisory sensors during migration, because they are probably cheaper than finding every dashboard/automation break after deletion.

Remove or hide after the HA dependency check:

- Thermal comfort/bedroom/underfloor policy if that is moving to HA automations.
- Export-limited curtailment controls if export-limited mode is no longer part of the operating model.
- Duplicate legacy aliases and number settings that no longer influence decisions.
- Cooling policy until the cooling audit identifies the small rule worth keeping.

## Live use snapshot

Operator handoff says the live setup now has core, EV, and grid-charge gates enabled. Export-limited mode and thermal control are off. EV solar automation reads `binary_sensor.garage_deye_energy_manager_ev_solar_charge_allowed` plus solar/manual switches. `script.timxon_ev_charger_start` and the stop path write programme powers using the manager's bypass/restore number entities. Night bypass sync automation is off.

That means the current EV entities are live integration points. Do not treat them as harmless advisory outputs, and do not delete them until the HA automation/script ownership of charger start/stop and programme power writes is deliberately replaced.

## Current core flow

Repo facts:

- Actuator defaults remain mostly safe. `deye_control_enabled`, `grid_charge_control_enabled`, `ev_control_enabled`, thermal, direct climate, PV load-test, cooling, and export-limited gates default false in settings/features (`custom_components/deye_energy_manager/models.py:15`, `custom_components/deye_energy_manager/const.py:220`).
- The coordinator samples HA state into `EnergyManagerInputs`, including battery, grid, forecast, charger, Taycan/Porsche SOC, WiCAN-derived SOC, thermal, and cooling inputs (`custom_components/deye_energy_manager/coordinator.py:1048`, `custom_components/deye_energy_manager/models.py:232`).
- `decide()` remains the main pure policy boundary. It derives forecast tier, active Deye slot, reserve SOC, paid-grid avoidance, thermal/curtailment state, EV action, and grid-charge requirements (`custom_components/deye_energy_manager/decision.py:1771`).
- `build_deye_plan()` is the inverter boundary. It maps a decision to capacity targets, charge-mode select values, programme power targets, and grid-charge switch state (`custom_components/deye_energy_manager/decision.py:2709`).
- `_apply_deye_plan()` is the normal Deye write path. Capacity writes are gated by Deye control, charge select/switch writes by grid-charge control, and programme power writes by EV control (`custom_components/deye_energy_manager/coordinator.py:1666`).
- Write helpers suppress unavailable entities, no-op same values, repeated writes inside the cooldown window, and rapid flip-flopping (`custom_components/deye_energy_manager/coordinator.py:1585`).

Unknowns outside repo:

- Which sensors/binary sensors current HA automations still read.
- Whether physical Deye programme row layout still needs duplicate boundary mirroring.
- Whether Solcast, Taycan cloud, WiCAN, and charger entities are all reliable live sources.

## Forecast and SOC planning

What it does:

- Forecast tiering subtracts a safety buffer from tomorrow's forecast, then maps the result to `excellent/good/medium/poor/dreadful/brutal` reserve/charge targets (`custom_components/deye_energy_manager/decision.py:270`).
- `evening_energy_plan()` calculates 7am and 4pm targets from base load, evening heating/EV allowance, safety buffer, battery capacity, forecast, and committed flexible load (`custom_components/deye_energy_manager/decision.py:550`).
- Cheap-grid energy budget uses the derived 7am target rather than blindly aiming at 100%; tests cover that behavior (`tests/components/deye_energy_manager/test_decision.py:783`).
- Paid-grid avoidance lowers active reserve to the minimum SOC floor when importing paid power and SOC is above that floor (`custom_components/deye_energy_manager/decision.py:491`).

Keep this. It directly matches the desired core job: set inverter percentages/toggles from battery, forecast, tariff window, and car charging.

Simplify later:

- Paid-time reserve knobs look more complex than current behavior. `paid_time_floor_soc()` returns `min_soc_floor`, and `paid_time_discharge_target_soc()` effectively resolves to that floor for the protected path (`custom_components/deye_energy_manager/decision.py:459`, `custom_components/deye_energy_manager/decision.py:465`). If no HA automation reads those number entities, remove or convert them to compatibility aliases.
- Missing tomorrow forecast falls to 0 kWh and therefore the harshest tier (`custom_components/deye_energy_manager/decision.py:273`). That is conservative, but if forecast sensors are flaky it can cause unnecessary charging.

## Deye plan and write gates

What it does:

- Tariff windows are hard-coded: cheap grid 21:00-07:00, daytime 07:00-13:00 and 13:00-17:00, then peak (`custom_components/deye_energy_manager/decision.py:421`).
- Default programme starts are `07:00`, `13:00`, `17:00`, `20:50`, `20:55`, `21:00`; the active slot is found by row order (`custom_components/deye_energy_manager/models.py:50`, `custom_components/deye_energy_manager/decision.py:390`).
- Cheap-grid preserve sets capacity while keeping charge mode `No Grid or Gen`; cheap-grid charge sets capacity and `Allow Grid` (`custom_components/deye_energy_manager/decision.py:623`, `custom_components/deye_energy_manager/decision.py:2749`).
- Deye programme power is also used by the EV path: when EV control is enabled, active slot programme power is set to bypass or restore watts (`custom_components/deye_energy_manager/decision.py:2772`).
- Manual restore paths can call `_apply_deye_plan(..., override_gates=True)`, so button/manual behavior intentionally bypasses normal feature gates (`custom_components/deye_energy_manager/coordinator.py:1623`).

Keep this as one module/integration. It is the part least suited to HA YAML because the inverter writes need clamping, row mapping, same-cycle conflict detection, and write-thrash protection near the actuator calls.

Simplify later:

- Drop duplicate cheap-grid boundary mirroring if the live inverter no longer needs it (`custom_components/deye_energy_manager/decision.py:353`).
- Keep one owner for programme power writes. Right now the manager and live HA scripts both matter. Splitting this before deciding ownership will create races.

## EV charger, Taycan, and WiCAN

Repo facts:

- EV settings now include solar start PV threshold, bypass/restore programme powers, manual target SOC, and WiCAN freshness/energy thresholds (`custom_components/deye_energy_manager/models.py:119`, `custom_components/deye_energy_manager/const.py:316`).
- Default entity IDs include Taycan/Porsche sensors, charger switch/current/voltage/connector/session entities, and `script.timxon_ev_charger_start` (`custom_components/deye_energy_manager/const.py:34`).
- `ev_decision()` chooses an EV action from charger availability, connector state, charger-request state, EV/Taycan SOC, cheap-grid window, manual override, solar-arrival latch, PV threshold, battery priority, and discretionary budget (`custom_components/deye_energy_manager/decision.py:1525`).
- Manual charging override clamps the target SOC to 40-100%, requires a present Taycan/WiCAN SOC, starts below target, and stops at target or when cleared (`custom_components/deye_energy_manager/decision.py:1556`, `custom_components/deye_energy_manager/decision.py:1645`).
- Solar charging is blocked during manual override and cheap-grid windows; it also needs battery recovery/priority, daytime solar arrival or latch, PV above the start threshold, no startup power deficit, and available discretionary budget (`custom_components/deye_energy_manager/decision.py:1676`, `custom_components/deye_energy_manager/decision.py:2324`).
- Current actions include `ev_charger_start`, `ev_charger_stop`, `ev_grid_bypass_start`, `ev_grid_bypass_hold`, `ev_grid_bypass_restore`, and `allow_solar_charge` (`custom_components/deye_energy_manager/decision.py:1691`).
- When EV control is enabled, `async_apply_decision()` can call the configured start script, turn off the charger control switch, clear manual override at SOC cutoff, and then apply the Deye plan (`custom_components/deye_energy_manager/coordinator.py:1325`).
- `_apply_deye_plan()` writes Deye programme powers behind the EV control gate (`custom_components/deye_energy_manager/coordinator.py:1709`).

WiCAN facts:

- Charger events can trigger a local WiCAN SOC query on connector connect, charge start, charge stop, or session-energy threshold (`custom_components/deye_energy_manager/coordinator.py:516`, `custom_components/deye_energy_manager/wican.py:124`).
- The WiCAN parser validates successful, numeric 0-100% responses (`custom_components/deye_energy_manager/wican.py:20`).
- SOC resolution prefers fresh WiCAN SOC, then fresh cloud/Taycan SOC, then the newest last-known-good value (`custom_components/deye_energy_manager/wican.py:199`).
- The integration exposes WiCAN/effective Taycan SOC sensors and a manual refresh button (`custom_components/deye_energy_manager/sensor.py:138`, `custom_components/deye_energy_manager/button.py:25`).
- Tests cover local SOC cutoff, manual target start/stop, target 40%, manual ownership through 07:00, daytime solar gating, and EV solar latch behavior (`tests/components/deye_energy_manager/test_decision.py:1259`, `tests/components/deye_energy_manager/test_decision.py:1575`).

Keep this for now. It is live, it writes, and it is already entangled with Deye programme power. The lazy split is not a new EV integration yet; it is a clearer ownership decision:

- If the manager owns EV charging, keep charger start/stop and programme power writes inside this integration and make HA automations consume only manager entities/buttons.
- If HA automations own EV charging, turn this integration into advisory sensors and remove its start/stop writes after migrating the live scripts.

Do not half-split it. Two owners writing the same charger/programme power state is the brittle part.

## Export-limited and curtailment leftovers

This changed in the refreshed source. The old audit claim that PV load-test recommendation is permanently false is now wrong.

Current repo behavior:

- `export_limited_mode_enabled`, `thermal_control_enabled`, and `pv_load_test_control_enabled` still exist as gates (`custom_components/deye_energy_manager/models.py:15`, `custom_components/deye_energy_manager/const.py:220`).
- The old thermal comfort matrix is now explicitly demoted: the code comment says thermal control is limited to absorbing PV that cannot be exported or accepted by the battery, while old forecast/comfort calculations remain as compatibility diagnostics (`custom_components/deye_energy_manager/decision.py:2225`).
- Curtailment signal requires export-limited mode, thermal control, heating mode, load/cooldown availability, enough SOC, expected PV above threshold, low battery charge acceptance, no meaningful battery discharge, grid import within tolerance, and export within the keep threshold (`custom_components/deye_energy_manager/decision.py:2229`).
- Actual curtailment control also requires `pv_load_test_control_enabled`; recommendation can still be raised when curtailment signal exists and there are add candidates (`custom_components/deye_energy_manager/decision.py:2264`).
- Proposed thermal actions are now curtailment add/shed/idle actions, not the old broad comfort scheduler (`custom_components/deye_energy_manager/decision.py:2281`, `custom_components/deye_energy_manager/decision.py:2429`).
- The force-test button still exists and is gated by PV load-test/direct thermal controls (`custom_components/deye_energy_manager/button.py:68`).

Live handoff says export-limited and thermal are off, so this path is inactive live. If export is now allowed and the system no longer needs curtailment testing, this is a good deletion candidate after checking HA automations for `pv_load_test_*`, `export_soak_*`, and thermal action sensors.

Do not keep this merely because it exists. Keep it only if the inverter still clips PV in a way that a managed heater load can usefully diagnose or absorb.

## Coupling points that make deletion tricky

- `EnergyManagerSettings` mixes core inverter controls, EV controls, WiCAN, thermal policy, underfloor/bedroom heat, cooling, export-limited curtailment, grid-loss notification, and legacy aliases in one dataclass (`custom_components/deye_energy_manager/models.py:10`).
- `EnergyManagerDecision` is one large object consumed by sensors, binary sensors, coordinator actions, and tests (`custom_components/deye_energy_manager/models.py:323`, `custom_components/deye_energy_manager/sensor.py:26`, `custom_components/deye_energy_manager/binary_sensor.py:23`).
- `decide()` still computes more than one subsystem in one pass: forecast, paid-grid avoidance, EV, cheap grid, thermal/curtailment, cooling-adjacent diagnostics, and action summaries (`custom_components/deye_energy_manager/decision.py:1771`).
- The published HA entity contract is broad, and some entities may exist only to keep old automations/dashboards working.

This points to extraction by responsibility, with compatibility sensors during transition, rather than a blank rewrite.

## Suggested split

Smallest useful split:

1. `deye_energy_core`: forecast tier, SOC targets, tariff window, paid-time discharge target, cheap-grid preserve/top-up, `DeyePlan`, and Deye write gates.
2. `ev_charger`: Taycan/WiCAN SOC resolution, manual target SOC, solar permission, charger start/stop, and requested Deye programme power. Decide one owner before splitting HA scripts.
3. `curtailment_thermal`: only export-limited/curtailment soak if it is still needed. Otherwise delete it after entity dependency checks.
4. `cooling`: defer to the cooling audit; if retained, keep one small controller with clear ownership and simple safety gates.

Transition path:

- First document live HA dependencies on entities/scripts.
- Preserve current entity names while moving internals.
- Remove inactive controls one subsystem at a time.
- Delete compatibility aliases only after HA no longer references them.

## Retain/delete checklist

Retain now:

- `forecast_tier()`, `evening_energy_plan()`, `paid_grid_avoidance_state()`, `cheap_grid_state()`, `ev_decision()`, `build_deye_plan()`.
- `_apply_deye_plan()`, `_call_number_set()`, `_call_select_option()`, `_call_switch()`, `_call_script()`, and write-thrash suppression.
- WiCAN/Taycan effective SOC resolution and manual EV target handling.
- EV solar permission binary sensor and manual charging override while live automations use them.

Delete or hide after HA dependency check:

- Export-limited/curtailment switches, numbers, sensors, and force-test button if the site no longer needs curtailment testing.
- Thermal comfort/bedroom/underfloor policy if moved to HA automations.
- Paid-time reserve number settings that no longer change behavior.
- Duplicate Deye row mirroring if the physical programme schedule no longer needs it.
- Legacy heat aliases once naming is settled.

Do not move to HA YAML:

- Deye programme-row mapping.
- Whole-percent capacity clamping.
- Same-cycle write conflict detection.
- Write cooldown/thrash suppression.
- One-owner programme power arbitration for EV bypass/restore.

Good HA automation candidates:

- Bedroom overnight heat, if it only arms/disarms climate entities from published SOC/forecast sensors.
- Thermal soak/shed after the policy is reduced to a small rule.
- Notifications and dashboard-only advisory behavior.

## Decision

Ponytail answer: gut around the spine. Keep the inverter planner/writer and the live EV/WiCAN/manual charger path. Remove inactive thermal/export-limited/cooling policy only after checking live HA entity references. A rewrite is only attractive if that dependency check shows almost nothing reads the current entity contract.
