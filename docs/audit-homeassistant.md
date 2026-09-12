# Live Home Assistant dependency inventory

Read-only inspection on 2026-09-12, approximately 13:22–13:30 Pacific/Auckland. These are point-in-time observations, not promises that a toggle or automation remains unchanged.

## Sources and limits

- Read the live SMB configuration share: `automations.yaml`, `scripts.yaml`, three relevant storage dashboards, `template/deye_sensors.yaml`, root and ESPHome-directory fan controller YAML, deployed manifest, and four deployed Python files.
- Queried HA state and seven days of recorder history through the connected HA read tools.
- The initial HA text search was explicitly incomplete: its automation time budget expired and YAML scripts were not available through its config endpoint. Reading the YAML files directly filled that gap for those files.
- Did not exhaustively traverse all includes, UI helpers, all dashboards, external consumers, or dynamically constructed entity references. Absence from this inventory is not proof that an entity can be deleted.
- Deployed version: v0.5.69. Four central source files match release tag `d13dfe0`. The audit branch was updated to this version after discovering its original v0.5.46 base.
- Selected raw copies are in the locally Git-ignored `homeassistant-config-snapshot/`; these private local files are not part of this committed documentation. YAML line numbers below refer to that dated copy.

## Current gates

| Control | Live state | Meaning for cleanup |
| --- | --- | --- |
| Manager, advisory, Deye, grid-charge, EV control | On | The system is actively controlling energy policy |
| Cheap-grid preserve/charge, EV bypass/solar/cheap-grid charging | On | Preserve these pathways until replaced |
| WiCAN Taycan SOC | On | Include vehicle SOC/targets in the EV contract |
| Thermal control and legacy heat control | Off | General thermal actions are gated off |
| Direct climate control | On | Bedroom night mode can still write independently |
| PV load test, export-limited mode | Off | Unused-at-present curtailment path; confirm clipping is no longer needed |
| Inverter cooling, minimum hunt, fan failure protection | On | Fan policy and inverter protection both need attention |
| Bedroom armed | Off at inspection | Does not imply unused; history proves repeated arming |
| Morning preheat, underfloor schedule | On internally | Outer thermal gate is off; do not mistake individual feature toggles for active writes |
| Overnight dining comfort | Off | No current enabled policy |

Live cooling target was 40 C with a 1 C deadband; emergency temperature 52 C; fan-failure trip 50 C sustained for 5 minutes. Protection required/active were both off. These differ from release defaults. Bedroom target was 17 C, paid-import threshold 500 W, and the calculated morning SOC target was 20% at inspection (the latter is dynamic).

## Automation and script contracts

Entity IDs really use both `deye_energy_manager_` and `garage_deye_energy_manager_` prefixes. Search both. The Python unique ID is entry ID plus entity key (`custom_components/deye_energy_manager/entity.py:18`); a new config entry or renamed key is not a drop-in entity migration.

| Consumer / source | Live status | Dependency / effect |
| --- | --- | --- |
| Bedroom Button Double Press, `automations.yaml:1519` | On; recently triggered | Toggles `switch.garage_deye_energy_manager_bedroom_night_heating_armed` after the existing lights/routine actions |
| TIMXON EV Solar Surplus Charging, `automations.yaml:5873` | On; triggered during inspection | Reads `binary_sensor.garage_deye_energy_manager_ev_solar_charge_allowed`, solar-enabled switch and manual-override switch; writes charger current/availability/control and uses OCPP recovery |
| TIMXON EV Night Charging 7am Stop, `automations.yaml:6155` | On | Despite its name, sets current to 6 A and availability on at 07:00, handing control to daytime solar policy |
| `timxon_ev_charger_start`, `scripts.yaml:1408` | Callable script; idle is not disabled | Reads manager EV bypass programme power; writes Deye programmes 1/2/3/6 and charger controls |
| `timxon_ev_charger_stop`, `scripts.yaml:1445` | Callable script; idle is not disabled | Reads manager restore programme power; writes Deye programmes 1/2/3/6 and charger controls |
| TIMXON EV Night Bypass Sync, `automations.yaml:6103` | Off | Duplicate potential Deye programme power writer; preserve status through migration or remove deliberately |
| Deye scheduled free-power start/end, `automations.yaml:5844`, `:5859` | On | Write `input_boolean.free_power_active`, which remains an energy-policy input |
| Deye Grid Loss Alert | On | Existing independent notification path; integration notification gate is off |
| Solar Export Heating Recovery, `automations.yaml:1881` | Off | Old direct climate controller; disabling manager would not remove this automation |
| Solar Heat emergency/shed/add/override/stage automations, `automations.yaml:4167` onward | Off | Old climate/ownership/helper machinery |
| Solar Forecast Battery Planner and Cheap Grid Charge Enforcer, `automations.yaml:4866`, `:5318` | Off | Old inverter capacity/charge-mode writers; enforcer also references bedroom arm switch |
| EV Night Grid Charge Ramp Detector | Off | Old programme-power writer based on house-load inference |
| Energy Manager Cutover Watchdog | Off | Reads legacy heat-control and heat-should-shed entities |
| `deye_energy_manager_add_one_heat_load`, `scripts.yaml:1041`; `deye_energy_manager_shed_one_heat_load`, `:1214` | Callable scripts | Old climate writes using ownership helpers and `solar_*` settings; check callers before deletion |

The enabled automation named “Solar Heat Controller - Placeholder Off” is a placeholder; its name/enabled state alone is not evidence that thermal control is active. One old EV inverter-control automation entity was unavailable at inspection, which should be accounted for in cleanup rather than interpreted as an active writer.

The active solar EV automation contains actual current modulation, a house-load ceiling, event-based starts, and OCPP retry handling. Moving all Python policy to YAML would add to existing complexity, not start with an empty automation system. The integration's newer manual/SOC control paths and the callable scripts must be reconciled so they do not compete over the same controls.

## Bedroom usage

The user confirms the bedroom heat pump works correctly and prefers an HA automation. Recorder history for the arm switch and active binary sensor shows repeated overnight sessions over September 6–12; the latest sampled session ran approximately 01:47–12:00 on September 12. Both queries returned their complete available result set for the requested seven-day window (21 records each, including restart/unavailable records).

This establishes that the policy was used. It does not measure compressor operation or prove the climate held its target throughout; no such claim is needed given the user's functional confirmation.

Preserve the button and intended comfort behavior. The current implementation also sheds other configured climates on setup even with general thermal off. Separating bedroom ownership from that unwanted shedding is an intentional behavior decision, detailed in [the thermal audit](audit-thermal.md).

## Dashboard dependencies

The three inspected dashboards refer to at least these manager surfaces:

- Main: actual cooling fan percentage, cooling throughput, effective Taycan SOC, detected EV power.
- EV charger: SOC cutoff reached, manual target SOC, effective SOC, active target SOC, SOC source, WiCAN result, manual charging override.
- Free power: grid-charge-required, thermal policy state, thermal-control switch.

Update the thermal/cooling cards when removing those features; keep EV controls intact. The inspected `template/deye_sensors.yaml` contains no direct manager entity references, but other templates were not comprehensively scanned.

## Access result

The SMB account was verified and files were readable. CIFS mounting failed with `Operation not permitted`; the workspace container also lacks a usable FUSE device. `homeassistant-config-snapshot/README.md` clearly marks the local copies as a snapshot. A real mount requires filesystem-mount support from the host running this workspace; changing the home HA VM or its config would not resolve that local restriction.
