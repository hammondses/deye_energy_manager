# Release Notes

## v0.5.14

- Add the root repository license required by HACS validation.
- Supersede `v0.5.13`; controller behavior is unchanged from that release.

## v0.5.13

- Add a single Deye program-write planner so cheap-grid, paid-grid avoidance, EV bypass, thermal policy, and restore paths no longer write conflicting inverter settings independently.
- Add Deye write de-duplication, per-entity cooldowns, write diagnostics, and thrash protection for repeated program capacity/select changes.
- Rework cheap-grid planning around separate 7am `morning_start_soc_target` and 4pm `evening_peak_soc_target`, with projected 4pm SOC and reason diagnostics.
- Prevent cheap-grid preserve from leaking stale high targets into Prog3 after the cheap period exits.
- Retire thermal script actuation from runtime paths; thermal force buttons now require direct climate control.
- Add regression coverage for cheap-grid top-up/preserve/exit behavior, thermal shed stability during cheap grid, and write thrash detection.

## v0.5.12

- Fix coordinator startup after v0.5.11 by importing the shared `time_between` helper used by EV/base-load detection.

## v0.5.11

- Persist thermal runtime state across Home Assistant restarts, including manual override cooldowns, pending confirmation windows, lease state, and last add/shed/rotation timestamps.
- Apply paid-grid import grace before paid-grid avoidance decisions so short import spikes do not immediately alter reserve policy.
- Add optional `home_occupancy` entity mapping for underfloor scheduled comfort; if it is not configured, schedule-only mode continues to work.
- Gate force EV and thermal script buttons behind their matching control switches/actuation modes so manual buttons do not bypass the configured write path.
- Add regression coverage for grace-filtered paid import and underfloor occupancy behavior.

## v0.5.10

- Fix HA sensor metadata warnings by removing `energy` device class from forecast/budget estimate sensors that are measurements, not total meters.
- Make actuator write helpers compare live HA state before trusting cached writes, so external changes or failed writes can be corrected on the next cycle.
- Prevent inferred EV charging from contaminating the dynamic base-load estimate when no dedicated EV power sensor is configured.
- Gate comfort heat and scheduled underfloor actions behind manager/thermal control.
- Keep emergency shed-all as the explicit action when emergency discharge thresholds are crossed, even if ownership flags are stale.
- Use the thermal start charge threshold for pre-peak preserve reasoning instead of the legacy heat threshold.
- Implement the `restore_deye_normal` button for Prog6/1/2/3 EV-bypass restore and No Grid charge reset.
- Add missing Repairs translation entries and regression coverage for the fixed safety paths.

## v0.5.9

- Make the rolling energy budget target phase-aware: cheap-grid night now budgets to the 7am morning target instead of the daily/full battery target.
- Add `energy_budget_target_soc` and `energy_budget_target_name` sensors so dashboards can show the current operational target without guessing.
- Keep daytime solar planning tied to the daily battery target while avoiding misleading overnight `need to 100%` budget reasons.
- Add regression coverage for cheap-grid night SOC near the morning target with daily target still set to 100%.

## v0.5.8

- Fix default cheap-grid preserve SOC mismatch so all settings paths use 30%, not 50%.
- In cheap-grid preserve mode, explicitly reset Prog6/Prog1/Prog2/Prog3 charge selects to `No Grid or Gen` to clear stale `Allow Grid` state from older releases.
- Keep reserve preservation capacity-only; active battery charging remains limited to `grid_charge_required`.
- During paid-rate periods, lower active reserve to the emergency SOC floor instead of preserving battery and forcing paid import.
- Let EV cheap-grid bypass suppress battery top-up while active, then allow battery top-up to resume immediately after the EV stop condition clears the latch.
- Add regression coverage proving default medium-forecast cheap-grid behavior does not target 60%, EV bypass suppresses top-up, and paid-grid avoidance uses the battery down to floor.

## v0.5.7

- Change cheap-grid policy to calculate a 7am morning target SOC instead of using a generic high overnight charge target.
- Prefer reserve-only preserve mode so overnight house load uses cheap grid directly instead of charging and later discharging the battery.
- Add `morning_target_soc` and `cheap_grid_topup_required` diagnostics.
- Use `top_up_to_morning_target` mode for modest cheap-grid charging only until the morning bridge target is reached.
- Reserve `heavy_grid_charge` mode for dreadful/brutal forecasts or conservative strategy.
- Lower default cheap-grid preserve SOC from 50% to 30%.
- Apply morning preserve target to current and upcoming cheap-period Deye programme reserves.
- Add regression tests for medium/good/dreadful forecast targets, preserve-at-target behavior, EV bypass coexistence, and 7am exit.

## v0.5.6

- Split cheap-grid reserve preservation from active grid charging.
- Add native cheap-grid preserve/charge toggles and target SOC numbers.
- Add cheap-grid preserve required, preserve target, mode, and reason diagnostics.
- Treat the whole 21:00-07:00 off-peak window as eligible for cheap-grid preservation/charging policy.
- Write active Deye programme capacity/selects for the current slot instead of hard-coding only early programmes.
- Keep EV cheap-grid bypass separate from preserve/charge and retain reserve protection while EV bypass is active.
- Add regression tests for preserve-only, charge, high-SOC idle, and EV-bypass coexistence.

## v0.5.5

- Add local HACS/Home Assistant brand icon at `custom_components/deye_energy_manager/brand/icon.png`.
- Supersede `v0.5.4`, which added HACS validation but failed the brand-assets validation check.
- Packaging-only release; no controller behavior changes.

## v0.5.4

- Clean HACS metadata to current documented `hacs.json` fields.
- Add official HACS validation workflow for integration packaging checks.
- Document the HACS custom repository install/update path.
- Packaging-only release; no controller behavior changes.

## v0.5.3

- Fix solar-soak permission so negative discretionary budget can never report `solar_soak_allowed` or `thermal_allowed=true`.
- Require positive budget, battery target reachable, no paid-grid avoidance, no shed-level battery discharge, and enough budget for the smallest candidate load minimum run before solar soak is allowed.
- Fix underfloor diagnostics so floor-slab loads use underfloor thresholds instead of global room-air comfort values.
- Prevent underfloor with solar soak disabled from reporting `needs_soak` against heat-soak targets.
- Add regression tests for negative budget, too-small positive budget, paid-grid block, discharge shed override, and underfloor diagnostic thresholds.

## v0.5.2

- Add an internal persisted last-known-good SOC cache using Home Assistant storage.
- Load the restored SOC cache before the first coordinator refresh, so energy-budget calculations can run while Modbus SOC is still `unknown` after startup.
- Update the SOC resolver to prefer live numeric SOC, then fresh internal restored SOC, then optional helper fallback, then unavailable.
- Save every live numeric SOC and timestamp back to the internal cache.
- Add last-good SOC and timestamp attributes to SOC diagnostic sensors and diagnostics downloads.
- Add regression tests for budget calculation with restored SOC, stale fallback behavior, and underfloor policy using restored SOC.

## v0.5.1

- Replace blunt thermal permission gates with a rolling discretionary energy-budget calculation.
- Add sensors for remaining solar budget, battery kWh needed to target, expected house load to solar end, discretionary energy budget, base-load estimate, and energy-budget reason.
- Add configurable daily battery target SOC, charge efficiency, dynamic base-load estimate, house-load buffer, and discretionary-load safety margins.
- Use the rolling kWh budget for thermal soak, EV solar charging, PV load tests, and candidate load selection.
- Treat Bathroom underfloor as a scheduled floor-slab comfort load, not a room-air comfort load or default solar thermal battery.
- Add underfloor schedule controls, floor comfort thresholds, 12 C target, 14 C max target, SOC/grid guards, and underfloor policy diagnostics.
- Default Bathroom underfloor to `floor_underfloor`, `floor_slab`, comfort min 9 C, comfort target 12 C, normal target 12 C, no cooling, no fan, no solar soak, and no unowned battery shed.

## v0.5.0

- Add thermal policy states for battery priority, comfort-only heat, morning preheat, solar soak, normalise, shed, and emergency shed.
- Add solar phase diagnostics and morning battery-priority behavior so forecast-full override no longer full-sends thermal soak at low morning SOC.
- Add dedicated bedroom morning preheat policy with its own target, fan mode, SOC floor, grid-import guard, and forecast-recovery check.
- Add paid-time grid avoidance policy, reserve-floor diagnostics, solar-arrived detection, and active-slot Deye reserve targeting.
- Add lease/owner diagnostics for managed thermal loads, including manual/external override, pending confirmation, desired state, and lease reason.
- Add per-load unowned battery-shed and never-emergency-shed options.
- Keep battery-discharge shed/emergency decisions ahead of EV/grid/thermal discretionary actions.
- Fix EV cheap-grid bypass program order to Prog6/Prog1/Prog2/Prog3 and add force start/restore buttons.
- Add native entities for comfort/preheat/paid-grid tuning and expanded diagnostics.
- Add regression tests for morning battery priority, morning preheat, paid-grid reserve behavior, and emergency candidate selection.

## v0.4.6

- Fix `thermal_should_shed` so high battery discharge sets the shed-needed sensor even when no owned load is available.
- Fix emergency shed so it is based on discharge threshold, not ownership flags.
- Add `shed_blocked_no_owned_loads` expected action when shedding is needed but no eligible managed load can be acted on.
- Improve high-discharge reason strings so they no longer report `battery charge 0W, forecast_full_override=False`.
- Narrow unowned active-load detection to real `hvac_action`/power evidence while still allowing soak-like target/fan detection.

## v0.4.5

- Add opt-in unowned managed-load shedding on battery discharge.
- Add `switch.deye_energy_manager_shed_unowned_managed_loads_on_battery_discharge`.
- Detect soak-like unowned managed heat pumps from HVAC mode, target temperature, room temperature, and fan mode.
- Add per-load diagnostic attributes for unowned shed candidacy and reason.
- Improve thermal shed reason strings when battery discharge is high but no owned loads exist.

## v0.4.4

- Add last-known-good local Deye SOC fallback support.
- Add `soc_source` and `soc_age_minutes` sensors plus SOC attributes on decision sensors.
- Keep SOC unavailable as `None`; unknown/unavailable SOC is never converted to `0.0`.
- Allow charge-rate based thermal add and discharge/emergency shed decisions even when SOC is unavailable.
- Add README helper/automation guidance for local SOC cache helpers.

## v0.4.3

- Fix coordinator crash caused by a stale `slugify` reference in per-load diagnostics.
- Build per-load diagnostics through a fail-safe helper so diagnostic errors cannot make all integration entities unavailable.
- Add regression tests for default diagnostic load keys and diagnostic failure handling.

## v0.4.2

- Add native heat/cool soak and normal fan-mode select entities.
- Direct thermal control now sets supported climate fan modes during soak and normalise actions.
- Fan mode calls are skipped when the climate does not expose `fan_modes` or the selected mode is unsupported.
- Per-load diagnostics now include current fan mode, supported fan modes, desired fan modes, and fan-mode skip reasons.

## v0.4.1

- Fix per-load thermal diagnostic sensor registration by using stable managed-load slugs.
- Default diagnostic sensors now register as `dining`, `bedroom`, `office`, `hallway`, and `underfloor` thermal status entities.
- Add setup migration for existing installs so stored managed loads receive stable slugs.
- Make legacy heat/script controls visibly map into thermal controls during cutover.
- Keep direct thermal control as the canonical path while leaving legacy heat entities as aliases for now.

## v0.4.0

- Thermal storage controls with heating/cooling/auto modes.
- Native heat/cool soak and normal target temperature controls.
- Forecast-full override for earlier thermal soaking on good/excellent forecast days.
- Direct/script/advisory thermal actuation modes with direct climate control safety gates.
- EV cheap-grid bypass scaffolding and control entities.
- Per-load thermal diagnostic status sensors.
- Thermal cooldown and anti-short-cycle protection.
- Home Assistant diagnostics download and Repair issue support.
- Recent proposed action log for dry-run visibility before direct control.
- Existing managed load editor in the integration options flow.
- Outdoor temperature and Southern Hemisphere month fallback for thermal auto mode.
