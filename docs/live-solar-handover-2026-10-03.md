# Live solar controller handover — 3 October 2026

The shared planner and separate battery/EV actuators were enabled together at
approximately 17:46 Pacific/Auckland. Runtime `0.6.0b20` was installed through
HACS from tag `v0.6.0b20`; all 33 installed integration files matched the reviewed
source. Home Assistant Core was restarted and the manager loaded successfully.
All 359 regression tests and GitHub CI passed.

## Active configuration

- The existing `automation.timxon_ev_solar_surplus_charging` (ID
  `1786590120813`) now runs the resolved EV handover controller. Its original
  writer was disabled before the configuration was replaced in place.
- The existing `automation.deye_dc_export_first_curtailment_capture` (ID
  `1790639409049`) now consumes the shared battery recommendation when the plan
  is fresh. Its original writer was likewise disabled before replacement.
- Both original entity IDs are enabled. Neither active configuration forces
  `initial_state: false`; normal HA state restoration applies after restart.
- Daytime solar planning is on, the daytime EV writer is `external_automation`,
  and `input_boolean.deye_battery_plan_handover_enabled` is on.
- The EV power map is `sensor.evcharger_power_active_import`. The manager
  converts its kW unit to watts. The official integration options flow saved
  this mapping after the optional-empty-entity default fix.
- Battery capacity is 32 kWh; the solar EV target is 80%. The EV settings are
  12 minutes sustained deficit, 7 minutes restart qualification, 5 minutes
  invalid-data grace, and a 13.5 kW site ceiling. These are HA controls.
- The provisional charge-acceptance curve remains
  `[[0,13.5],[0.85,13.5],[0.90,6.8],[0.96,3.0],[0.99,0.5],[1.0,0.0]]`.
  It is a conservative planning model, not a measured battery acceptance curve.

Manual EV charging and overnight control remain manager-owned. Integer raw OCPP
profile 9102 remains the TIMXON control method. A confirmed idle restart requires
charge control off, Preparing/Finishing connector status, transaction ID zero,
and a successful pong below 1,000 ms reported within 120 seconds. The installed
OCPP timeout is 20 seconds, whose 20,000 ms failure sentinel is excluded. Idle
meter values need not refresh; active charging retains strict meter freshness.
Grid voltage may be up to 600 seconds old to accommodate five-minute reporting.

## Live evidence and limits

The EV trace `c49eb9ba5d39a1c3a2996bd286832bc5` at 17:46:39 completed normally:
external ownership, online charger, confirmed stopped session, and fresh manager
plan were all true. Stale idle EV meters were accepted only as zero EV load.
The planner recommended 0 A; live surplus was negative and restart qualification
was false, so the stopped charger received no start command.

Battery traces at 17:46:40 and 17:46:50 completed normally with
`manager_plan_usable: true`. With PV below house demand and a 0 kW charge
recommendation, the controller correctly made no charge-current write. The
current-limit setting remained 250 A and the BMS limit was 125 A; that setting
does not override the BMS limit. This confirms branch selection and the
zero-surplus path, not a measured high-power step response.

HA configuration validation passed and startup logs contained no manager or
new-controller errors. Deye maximum solar stayed at 18 kW and maximum sell at
10 kW. The final app inventory found Predbat still running, while its old
notification entities were absent; their saved values could not be verified.
Because the shared manager no longer consumes Predbat outputs, its app was
stopped, autostart set to manual, and watchdog disabled. Read-back confirmed
`stopped`, `boot: manual`, and `watchdog: false`; its configuration was retained.
No Predbat mode/read-only control or inverter reset was used.
The disabled review copies remain non-actuating staging
artifacts; they must never be enabled alongside the active originals.

Full-day capture performance and positive battery-current response were not
observed during this late-day cutover. The regression suite covers positive
power conversion, conservative completion decisions, idle restart, stale-data
protection, and stop/restart hysteresis. Further curve tuning can be done in HA
without another integration release or Core restart.

## Rollback

Before restoring an actuator, turn off its current automation with
`stop_actions: true`. Restore its reviewed original configuration through the
HA automation API, then enable it. Set the daytime EV writer back to `manager`
before restoring the old EV automation, and turn the battery-plan handover
helper off before restoring the old battery automation. Never run old and new
writers together. Leave manual/overnight feature gates unchanged.

Exact pre-handover configs are saved on the agent host as
`/tmp/deye-cutover-original-ev.json` and
`/tmp/deye-cutover-original-battery.json`; manager options are in
`/tmp/deye-cutover-manager-options.json`. The detailed commissioning receipt is
`/tmp/deye-live-handover-receipt-20261003.json`. These temporary host artifacts
should not be treated as permanent backups. The prior EV config is also
tracked in `docs/live-config-backups/2026-10-03-timxon-operational-status-guards.json`.
The prior battery automation is tracked in
`docs/live-config-backups/2026-10-03-battery-before-shared-plan.json`.
