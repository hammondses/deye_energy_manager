# Release Notes

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
