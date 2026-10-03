# Home Assistant automation candidates

These files are reusable review/deployment artifacts, not an automatic installer.
Resolved versions were deployed into the **original** battery and EV automation
IDs on 3 October 2026 with manager `0.6.0b20`. Both originals are enabled. The
separate review copies in HA remain disabled and must not be enabled alongside
them. See the [live handover record](../live-solar-handover-2026-10-03.md) for
current settings, evidence and rollback.

For another deployment, re-read the destination automation and compare its
configuration before replacement. The battery source hash `74cba31e818cbad2`
identifies the pre-handover backup, not the current live configuration. Resolve
entity IDs from the destination registry and preserve existing helper tuning.
The historical pre-deployment rendering checks below do not describe current
entity availability.

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

The EV actuator handover is captured in `ev-plan-handover.json`. Its resolved version is deployed; for reuse, its manager writer select, feature switches, and plan sensors must be resolved in the live registry before use. The helper manifest distinguishes one-time `creation_default` values from runtime `initial` values so existing timer/latch tuning can restore after Home Assistant restarts. Active EV modulation still requires recent numeric OCPP current and power readings. A stopped restart may proceed without fresh idle meters only when the charge switch is off, the connector reports Preparing/Finishing, transaction ID is zero, and a recent OCPP websocket pong confirms the charger is online. Grid-voltage fallback is limited to 600 seconds to match the manager's accepted freshness window. OCPP sample timestamps are not exposed, so HA receipt freshness is the available bound.

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

The EV candidate now has eleven executable action-path scenarios in addition to
its template/structure checks. These cover short-cloud recovery, sustained
charge shortfall with a missed timer event, failed stop, asynchronous start,
invalid grid data, target changes during delays, adoption at target, and a
site-load jump that reduces a delayed retry's current. The small interpreter
models the relevant action subset; it is not Home Assistant's script engine.

The candidate's sequential variable expressions also rendered successfully in
HA's own Jinja engine against live states on October 3. With the new manager
entities absent, `plan_fresh=false`, `external_owner=false`, and
`restart_qualified_now=false`; no actuator service was called. HA action-schema validation, entity resolution and helper provisioning were
completed during deployment. A full live stop/restart cycle and positive-power
response remain observational limits; see the live handover record.

For the full-house-battery restart path, SOC freshness is inherited from the
fresh valid manager plan, which validates SOC through its planning input and
verified MQTT receipt handling. Deployment must verify that the automation's
SOC entity is the manager's configured battery SOC source. A second raw
`last_reported <= 120 seconds` rule would prevent a seven-minute restart dwell
when an unchanged SOC sensor reports less often; both initial and delayed
restart checks therefore use the fresh-plan contract.

## Battery damping — 4 October 2026

The shared-plan battery path now ignores AC errors up to 200 W and current
corrections below 3 A. Material increases can occur after 10 seconds since the
current-limit entity last changed; reductions wait 45 seconds. A live BMS/DC
ceiling reduction bypasses these delays. The 1 A hidden-PV probe requires
inverter AC output within 200 W of `min(rated AC, house + export limit)` and
120 seconds since the last gate change. This prevents probing far below any
physical bottleneck and then immediately correcting the probe back down.

These are settling periods since a gate change, not continuous-condition dwell
timers. The existing 10-second loop and telemetry triggers remain active.
Threshold variables are editable in the HA automation. The manager's headroom
policy and exact legacy fallback are unchanged; damping applies when the
shared plan is usable. No Core restart is needed for the automation update.

### Adaptive capture update — 4 October, 12:13 NZDT

The initial 1 A / 120 s probing was too slow during confirmed curtailment.
A second regime now opens by 5 A after at least 10 s when AC output is within
60 W of the physical AC/export ceiling and measured battery current remains
within 1.5 A of its limit. Every probe requires numeric battery/inverter/grid
reports received at least 5 s after the last gate change and no older than
90 s. It therefore waits for real feedback before repeating; 10 s is a minimum,
not a guaranteed command rate. Away from tight saturation, the existing
1 A / 120 s near-ceiling probe, correction deadband and slower release remain.

All 368 regression tests passed. HA rendered the live expressions before
deployment. Source release 0.6.0b22 records this automation-only update; manager
Python remains 0.6.0b20 and the forecast/headroom strategy is unchanged.
Rollback uses `docs/live-config-backups/2026-10-04-battery-before-adaptive.json`
through the automation API; current config is saved alongside as
`2026-10-04-battery-adaptive.json`.

Live verification: readback matched hash `0e71ddf27d4e8d67`. At 12:14:02
the gate increased from 26 A to 31 A. Battery charging rose from about 1.32 kW
to 1.65 kW while export remained about 9.98 kW. Subsequent traces waited for
the next inverter report before another probe; inverter telemetry currently
reports roughly once per minute. This confirms a successful bounded capture
step, not full-day performance.
