# Daytime EV solar actuator handover proposal

This is a design handover, not a live automation change. Keep solar planning in
the Deye Energy Manager and charger actions in a separate Home Assistant
automation so the actuator can be reloaded without restarting the manager.
The EV automation must remain disabled from a new plan until the ownership
setting, current advisory entities, telemetry and acceptance curve are all
available and reviewed.

## Ownership and manager boundary

The manager remains the source of the solar EV recommendation, house-battery
completion status, target SOC, forecast validity and decision reason. Its
current options include `ev_control_enabled`, which also gates old EV decisions
and Deye programme writes. Do not turn that option off as a shortcut to avoid
competing daytime writers.

The current development branch adds `daytime_ev_writer`. In
`external_automation` mode, automatic manager start/stop writes yield from 07:00
through 20:59 when manual charge-to-target override is off. Manual override and
overnight manager behavior remain manager-owned. Enable that mode only for the
daytime handover; keep the manager's existing overnight and manual paths
enabled. The separate automation must yield immediately while
`switch.garage_deye_energy_manager_ev_manual_charging_override` is on.

The automation should consume the manager's **current-action** output, not
recreate the forecast budget. Expected manager entities include:

- `sensor.garage_deye_energy_manager_solar_plan_status`
- `sensor.garage_deye_energy_manager_solar_plan_generated_at`
- `sensor.garage_deye_energy_manager_solar_plan_recommended_ev_amps`
- `sensor.garage_deye_energy_manager_solar_plan_target_reachable`
- `sensor.garage_deye_energy_manager_solar_plan_reason`
- existing `sensor.garage_deye_energy_manager_ev_active_target_soc`
- existing `switch.garage_deye_energy_manager_ev_solar_charging_enabled`

Verify those exact IDs after the manager package is loaded. A usable plan must
have status `advisory`, a generation time within 90 seconds (no more than 5
seconds in the future), and numeric recommendations. The forecast source age
and battery completion are manager responsibilities. The automation should not
invent a second aggregate forecast budget.

## OCPP telemetry finding, October 3

The mounted configuration contains OCPP integration version 0.12.0. Its
`ocpp.trigger_custom_message` service maps `requested_message: MeterValues` to
the OCPP 1.6 `TriggerMessage(MeterValues)` request. The integration handles
incoming `MeterValues` and updates current, power and voltage entities. This
proves the software path exists; it does **not** prove the TIMXON accepts the
request or sends a reply while a transaction is suspended. No charger-directed
service was called during this audit.

The persisted TIMXON settings are `meter_interval: 60`, `idle_interval: 900`,
and sampled measurands `Energy.Active.Import.Register`, `Power.Active.Import`,
`Current.Import`, and `Voltage`. On OCPP 1.6 the integration sends these as
`MeterValueSampleInterval=60` and `ClockAlignedDataInterval=900` when the
charger connects. The persisted values are desired configuration, not a
read-back proving the charger accepted them. The 900-second clock-aligned
setting represents a 15-minute idle reporting cadence when supported; it does
not guarantee the charger implements idle reports.

At the read-only snapshot around 15:15 local time, current and active power
were both zero but their last reports were around 13:53; voltage was 242 V,
last reported around 13:52. Connector status was `SuspendedEV` and the charge
control switch was on at about 13:53. Those zero readings are stale and must
not be treated as live confirmation that the EV is drawing no power. A fresh
grid-voltage value can be a voltage estimate only; it cannot refresh EV current
or power. The manager should mark stale EV power unavailable rather than
silently treating it as zero.

The next telemetry check, after explicit review, is to request one
`MeterValues` message while the car is plugged in and `SuspendedEV`, then verify
that the OCPP service succeeds **and** the current/power entities receive a
new `last_reported` time. If it does, separately verify actual charger values
for `MeterValueSampleInterval` and `ClockAlignedDataInterval`, then decide
whether a rate-limited stale-data refresh is needed. An accepted TriggerMessage
without a new MeterValues sample is not fresh telemetry. If the TIMXON rejects
the request or remains silent while suspended, the restart path needs another
live EV power source or a reviewed fail-safe policy before enabling this
automation; stale zero data must not be used to break the restart deadlock.

## Automation state and rules

Preserve the current OCPP raw-profile method: `ocpp.set_charge_rate` on
`devid: evcharger`, connector 1, profile 9102, `TxDefaultProfile`,
`Absolute`, `A`. Send an integer amp limit in the 6–32 A range. Do not migrate
to `number.evcharger_session_current_limit`; the installed integration
currently returns HTTP 500 for that entity. Keep the existing material-change
verification and stale-profile recovery, with ownership, solar permission,
connector and charge-control rechecks after each delay. Manual takeover during
a wait cancels any clear/retry or delayed start.

The controller has five effective states:

1. **Yield.** Manual override is on, another writer owns the charger, or the
   connector is unplugged. Cancel both hysteresis timers; do not send profiles
   or stop a manual session.
2. **Stop for target or disablement.** While this automation owns daytime solar
   charging, reaching the configured active SOC target, disabling solar charging
   or disabling the manager stops the solar session immediately and cancels both
   timers. Merely ceasing profile writes does not stop an already charging car.
   This branch must recheck manual ownership immediately before the stop.
3. **Modulate.** With fresh valid manager advice and fresh actual EV telemetry,
   use the manager's recommendation, capped by the existing live essential-load
   ceiling. For a 13.5 kW ceiling, the instantaneous safety cap is:

   ```text
   non_ev_house_w = max(0, essential_power_w - ev_power_w)
   site_room_a    = floor(max(0, 13500 - non_ev_house_w) / voltage_v)
   request_a      = min(32, recommended_ev_amps, site_room_a)
   ```

   If the resulting request is at least 6 A, send it as a whole integer when it
   differs materially from the previous request. This ceiling is an immediate
   safety clamp; the manager remains responsible for forecast and battery
   completion priority. If current/power are stale, do not use stale zero as
   `ev_power_w` or increase current based on it.
4. **Cloud ride-through.** When the plan recommends less than 6 A or briefly
   becomes unavailable, retain the running session at 6 A rather than cycling
   the charger. Start a configurable deficit timer only while the house battery
   is discharging beyond a configurable threshold (or grid import exceeds its
   threshold) **and** the manager says the daily battery target is at risk or
   unreachable. One bad sample never stops the car. Suggested initial review
   values are 10–15 minutes sustained deficit; calibrate thresholds from live
   traces before use.
5. **Stopped / restart eligible.** When the sustained deficit timer expires,
   stop through the existing charge-control switch and record that this
   controller stopped the session. Restart only when manual override is still
   off, the active Taycan target is not met, connector remains present, manager
   advice is fresh and valid, the completion target remains reachable, and
   either (a) the house battery has reached its daily target or (b) the EV
   recommendation is at least 6 A with measured live surplus for a configurable
   5–10 minutes. A single sunny sample is insufficient. Clear the controller
   stop latch only after a successful restart or explicit user ownership.

The car's current active target (currently 80% for solar charging) remains the
SOC boundary. Do not add a separate Taycan SOC age block: WiCAN SOC updates are
energy-triggered and that could prevent an otherwise eligible restart. Continue
to use the manager's active-target state. The existing one-shot
`SuspendedEV` recovery is retained, but each delayed start must recheck manual
override, solar enablement/permission and connected state. A recovery attempt
must never override manual charge-to-target ownership.

Use independently configurable HA timers for sustained deficit and restart
qualification, plus a boolean latch recording that the solar controller
stopped the car. Keep these as actuator-automation helpers, not manager
forecast inputs. The manager's setting and advice remain live inputs, so editing
the automation or its helpers does not require reloading the integration.

## Before enabling the handover

- Verify that the manager's `daytime_ev_writer: external_automation` selection
  yields only its automatic daytime start/stop writes and preserves overnight
  and manual behavior.
- Load the manager entities and confirm fresh generated timestamps and actual
  EV-amp recommendations with the daytime plan enabled. Do not enable the
  actuator while the charge-acceptance curve is empty or the plan is unavailable.
- Prove suspended-state MeterValues freshness, or agree on an alternate
  measured EV power source / fail-safe rule before the automation can restart.
- Replay brief clouds, sustained deficits, recovery, manual takeover during
  verification, target reached, stale forecasts and OCPP loss. Check that the
  EV remains at 6 A through a short cloud and stops/restarts only after the
  configured dwell periods.
- Confirm no competing daytime automatic charger writer is active, and inspect
  traces for whole-amp `SetChargingProfile` values.

No live OCPP configuration, TriggerMessage, charging profile, or new EV
automation was issued as part of this review.

## Meter request observation

At approximately 15:30 on October 3, a single `ocpp.trigger_custom_message`
request for `MeterValues` completed successfully. Charger voltage changed from
242 to 245.5 V with a 15:30:03 report timestamp. Current and power remained zero
with 13:53 timestamps. No TriggerMessage system-log entry was returned. This
proves a fresh voltage update, not fresh current/power. Investigate unchanged-value
reporting and entity routing before concluding that the charger stopped sending
those measurands or relaxing the planner freshness requirement.
