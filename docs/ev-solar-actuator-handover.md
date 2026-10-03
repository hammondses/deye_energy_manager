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

These names are expected but not guaranteed: the integration gives sensors a
unique ID from the key, while Home Assistant creates the entity ID from the
friendly name. Resolve the registered entity IDs from those unique IDs after
deployment, or set explicit entity IDs before building the automation.

## OCPP telemetry finding, October 3

The mounted configuration contains OCPP integration version 0.12.0. Its
`ocpp.trigger_custom_message` service maps `requested_message: MeterValues` to
the OCPP 1.6 `TriggerMessage(MeterValues)` request. The integration handles
incoming `MeterValues` and updates current, power and voltage entities. This
proves the software path exists; it does **not** by itself prove that every
measurand was included in a reply while a transaction is suspended. During
follow-up, the root agent issued one `MeterValues` request around 15:30 local
time; the HA service succeeded, voltage changed from 242 V to 245.5 V, and the
energy register changed from 474.736 kWh to 474.764 kWh. No further request was
issued during this follow-up.

The persisted TIMXON settings are `meter_interval: 60`, `idle_interval: 900`,
and sampled measurands `Energy.Active.Import.Register`, `Power.Active.Import`,
`Current.Import`, and `Voltage`. On OCPP 1.6 the integration sends these as
`MeterValueSampleInterval=60` and `ClockAlignedDataInterval=900` when the
charger connects. The persisted values are desired configuration, not a
read-back proving the charger accepted them. The 900-second clock-aligned
setting represents a 15-minute idle reporting cadence when supported; it does
not guarantee the charger implements idle reports.

The original `ha_get_state` snapshot around 15:15 showed current and active
power at zero with timestamps around 13:53, voltage at 242 V from around 13:52,
and `SuspendedEV` status / charge control on around 13:53. After the 15:30
request, `ha_get_state` continued to project the current/power timestamps from
13:53. A read-only template evaluated inside Home Assistant at 15:34 instead
reported `last_reported` around 15:32 for current, power, voltage and energy;
the current/power values remained zero. Therefore the state-read tool's
projection was stale, while Home Assistant's own state machine had re-reported
all four entities.

That still does **not** establish per-measurand freshness. In this integration,
the OCPP 1.6 `on_meter_values` handler processes the samples actually present,
then schedules a full charger-device update; the sensor platform dispatches
all active entities on that update. Consequently a current/power entity can get
a fresh HA `last_reported` time because some other MeterValues field arrived,
even when that packet omitted current/power. The integration exposes no
per-measurand sample timestamp, and no raw payload for the 15:30 reply was
captured. The observed sample proves the TriggerMessage path can elicit at least
some fresh OCPP telemetry, but it does not prove the idle packet contained
`Current.Import` and `Power.Active.Import`.

Before allowing those values to drive the planner, add or obtain per-measurand
freshness: preferably have the OCPP integration expose each sensor's most recent
source-sample timestamp (or dispatch only the measurands actually present in a
MeterValues packet), then use that timestamp in the manager. Alternatively use
a separate live EV power meter, with explicit unit normalization. The OCPP
`sensor.evcharger_power_active_import` is in kW, while the manager currently
interprets its configured EV-power mapping as watts; do not map it directly
until that unit boundary is corrected. The currently blank mapping uses
current × voltage as the fallback. Do not infer per-measurand freshness from
the generic HA `last_reported` timestamp. Also verify the charger's effective
`MeterValueSampleInterval` and `ClockAlignedDataInterval` by read-back when
approved. No additional charger request is needed to establish this distinction.

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

The initial read-only review issued no charger calls. Subsequent authorized
meter-only diagnostics are recorded below; no new EV handover was enabled.

## Meter request observation

At approximately 15:30 on October 3, a single `ocpp.trigger_custom_message`
request for `MeterValues` completed successfully. Charger voltage changed from
242 to 245.5 V with a 15:30:03 report timestamp. Current and power remained zero
with 13:53 timestamps. No TriggerMessage system-log entry was returned. This
proves a fresh voltage update, not fresh current/power. Investigate unchanged-value
reporting and entity routing before concluding that the charger stopped sending
those measurands or relaxing the planner freshness requirement.

## Confirmed idle packet from Core service logs

The later packet capture was found through `ha_get_logs` with
`source=system_service`, `slug=core`; the raw `error_log` search had missed it.
At 15:43:30.635 local time, Core logged an inbound connector-1 MeterValues
message without a transaction ID. Its meter timestamp was 02:42:19.772Z and
it contained power 0 W, current 0.00 A, voltage 248.5 V and imported energy
together, with Sample.Periodic context. The sanitized packet is retained in
`automation-candidates/ocpp-idle-meter-evidence.json`.

This confirms that the TIMXON can report actual current/power while suspended.
It does not establish that every future entity refresh contains every measurand,
or that the charger's clock exactly matches HA. The manager reads HA state in
process, not the stale MCP projection observed during this audit. Keep bounded
data-loss behavior and independent battery/grid feedback in the actuator. A
per-measurand timestamp enhancement would strengthen diagnostics, but no OCPP
source change has been made. The logger was read back at its original WARNING
level after the temporary capture.
