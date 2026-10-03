# Home Assistant automation candidates

These files are review artifacts, not deployed configuration. The battery handover JSON contains a full candidate copy of the live automation read from Home Assistant and its source config hash (`74cba31e818cbad2`). It has not been written back to HA.

Before any deployment, re-read `automation.deye_dc_export_first_curtailment_capture` and compare the source hash. Rebuild the candidate from the current config if it changed. Then resolve each ID below in the live entity registry; the manager output entities and handover helper were absent during this audit, so the candidate must remain disabled until the manager version publishing these b16 outputs is installed and the data is fresh.

Required registry entries:

- `input_boolean.deye_battery_plan_handover_enabled` — create if absent, initial state off.
- `sensor.garage_deye_energy_manager_solar_plan_status`
- `sensor.garage_deye_energy_manager_solar_plan_generated_at`
- `sensor.garage_deye_energy_manager_solar_plan_recommended_battery_dc_power` — kW DC.
- `sensor.garage_deye_energy_manager_solar_plan_charge_all_surplus` — reported for visibility/triggering; its late-day policy is already reflected in the battery recommendation. The automation does not calculate a second clipping-window policy.
- `number.garage_deye_energy_manager_solar_plan_inverter_efficiency` — use this existing setting; no efficiency fallback is used in the manager path.
- `number.garage_deye_energy_manager_solar_plan_battery_max_charge_dc_kw` — live configured DC ceiling.
- `sensor.deye_battery_charge_limit_current` and `sensor.deye_battery_voltage` — existing BMS inputs.

The candidate retains the current active solar/export/grid/SOC gates, shadow-power formula and probe expression when the helper is off or manager data is invalid/stale. A valid manager recommendation is a minimum intentional DC charge request. The 1 A hidden-PV probe can exceed that request, but is bounded by current BMS acceptance, the existing 250 A ceiling and configured inverter DC capacity. It never uses an SOC==100 hard stop; live BMS acceptance remains authoritative. The actuator continues to use actual inverter and export values, so EV ramp changes are reflected through the measured house load.

Freshness is limited to 90 seconds old and 5 seconds future skew. Do not turn on the helper as part of installing the manager. Validate the candidate against live traces first; leave the helper off until that review is complete.

The companion offline tests execute Jinja templates from the JSON against synthetic states. They check fallback parity and unit/limit behavior, but they are not a substitute for validating Home Assistant's template rendering and live traces.

## Read-only live rendering check

On October 3, the candidate's sequential variable templates were rendered with
Home Assistant's own Jinja engine against live states, without calling actuator
services. With the handover helper absent/off, `manager_plan_usable` was false,
and both the selected and legacy AC targets were 9488 W; the current request
was 1 A. This verifies the fallback calculation for that snapshot, not control
performance, template behavior under all inputs, or the full action schema.

`ocpp-idle-meter-evidence.json` records a sanitized Core-log packet showing
current, power and voltage together while suspended. Charger identifiers are
omitted. The temporary OCPP logger level was verified restored to WARNING.
