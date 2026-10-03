# Shared daytime solar planning

Status: implementation in progress; not deployed. Existing overnight policy is
out of scope for replacement. No Predbat source is incorporated.

## Required outcome

1. Reach the configured house battery target (currently 100%) before night.
2. Preserve enough battery space and charge acceptance to capture otherwise
   clipped DC solar whenever physically feasible.
3. Prefer charging the plugged-in car to exporting, up to its allowed target
   (80%), while protecting the first two objectives.
4. Expose operating thresholds in Home Assistant so tuning does not require a
   new integration version. Battery and EV actuator automations stay separate.

The owner specifies 32 kWh battery capacity. On October 3 the existing live HA
capacity setting was corrected from 30 to 32 kWh and persistence verified.
At 83.6% SOC the manager then reported 5.583 kWh input needed to reach 100%,
consistent with 32 kWh and 0.94 efficiency. Efficiency and reserve settings
remain separate from battery capacity. Inverter max solar/export remained
18/10 kW. The inverse of this individual setting change is setting the same
capacity number back to 30; no other configuration restore is needed.

Insufficient sunlight, a full battery, or a binding BMS limit can make an
objective impossible. Report the predicted shortfall and unavoidable clipping;
do not label an infeasible plan successful or introduce new grid charging to
hide it. Existing forecast-aware overnight preservation/top-up remains intact.

## Evidence motivating the change

The current `decide()` daytime budget subtracts aggregate house use and battery
need from aggregate remaining PV. `hours_until_solar_end()` uses fixed 17:00.
There is no interval SOC/acceptance trajectory. EV solar permission can turn
off immediately when this scalar budget crosses zero.

The existing fast battery automation adjusts charge current. The existing EV
automation uses compatible integer-amp OCPP profiles, but delayed retries need
fresh ownership checks. A new session-current entity was rejected by the charger
with NotSupported; switching to it is not part of this work.

Predbat v9.3.3 separates DC charging from AC output and simulates headroom and
optional SOC-dependent acceptance. Its economic optimizer does not guarantee
this project's completion/headroom objectives. The live Predbat configuration
does not learn a charge curve and includes EV demand in its house-load input.

## Physical accounting

Use kW, kWh and hours internally, with explicit AC/DC boundaries. For interval
length dt, let P be available DC PV, B be DC power entering the battery, A be
solar inverter AC output, and eta_i/eta_b the conversion/charge efficiencies:

    P = B + A / eta_i + clipped_DC
    A <= inverter_AC_limit
    A = house_solar_AC + EV_AC + export_AC
    export_AC <= export_limit
    B <= min(BMS_limit, acceptance_at_SOC, (capacity - energy)/(dt*eta_b))
    next_energy = energy + B*dt*eta_b

The first implementation isolates solar charging physics. The horizon planner
also needs battery discharge for house deficits, reserve constraints and
discharge losses; solar-only interval tests do not prove horizon feasibility.

Non-EV demand is essential power minus measured EV power (unit-normalized).
The manager's existing base-load estimate already removes EV/owned flexible
loads; do not subtract the EV twice. Account for other committed flexible loads
once. Car charging must not create a planned house-battery discharge.

At an already saturated AC limit, adding the EV displaces export; it does not
create additional DC capture capacity. At a binding export limit below the AC
limit, the EV can use spare AC capacity and reduce spill.

## Proposed horizon allocation

Build a timezone-aware five-minute horizon from validated forecast intervals to
a seasonal daylight deadline. Prorate the current partial interval. Never use
tomorrow/3 as today's missing forecast. Reject gaps, overlapping intervals,
nonfinite values and stale data explicitly rather than interpreting them as zero.

For each scenario, simulate a battery-only baseline to establish attainable
completion and clipping with the actual acceptance curve. Then evaluate EV
allocation before export, requiring no worse battery completion or clipping than
that baseline. Prefer earlier useful car energy while plugged in; forecasts must
not assume the car remains available after an unknown departure. Re-plan using
fresh SOC and actual power rather than accumulating an unreconciled budget.

Completion under conservative solar and headroom under high solar are alternative
future scenarios. Evaluate shared near-term actions with future re-planning;
do not combine incompatible scenario bounds into a supposedly feasible single
SOC corridor. If no common action meets both objectives, expose the conflict
and prioritize house completion as requested.

Reserve only chargeable future spill, using time-dependent SOC/acceptance. Once
clipping opportunity has passed, release that reserve. A battery energy deficit
at sunset cannot be repaired with forecast energy arriving after the deadline.

The exact search method and conservative forecast weighting are still under
review. A scalar EV budget divided by remaining daylight is not sufficient:
it would unnecessarily spread charging beyond the car's plug-in window and
miss battery taper deadlines.

The completion calculation now uses continuous stored energy. For each future
interval, F(E) is the end energy after serving non-EV house demand and accepting
as much solar charge as possible, with SOC-band taper integrated across any
threshold crossed inside the interval. Invert this monotone transition backwards:

    required[i] = minimum E such that F_i(E) >= required[i+1]

Cloud deficits drain the house battery within reserve/discharge limits; they are
not silently assigned to grid power. The future recourse assumes no future EV
charging. A current EV recommendation must leave enough battery energy to satisfy
the next boundary. This is a completion constraint, not yet a full clipping
optimizer. No stored-energy rounding is applied at each five-minute step.

The deadline must represent the end of useful charging, bounded by local sunset.
Requiring exactly 100% at astronomical sunset after an hour of normal house
discharge would falsely reject a plan that reached 100% before night. Choose and
expose a forecast-dependent usable-solar deadline; do not conflate it with sunset
or an arbitrary fixed 17:00. Track whether today's target was reached separately.

Before connecting forecast bins to this DC model, establish whether this site's
Solcast output already incorporates inverter conversion/clipping. Modeled AC
output is not interchangeable with available DC PV; do not silently relabel it.
Use the supplier's last successful forecast-fetch timestamp for freshness, not
HA's state timestamp (which may change as a remaining-energy sensor ticks down).

The installed Solcast v4.6.1 site reports 16.5 kW DC modules and 12 kW inverter
capacity, tilt 8 degrees and azimuth -2 degrees. Its HA-side hard forecast cap is
disabled. Today's observed peak forecasts (8.89 kW P50, 10.22 kW P90) do not
establish whether the upstream output clips at 12 kW. Do not infer raw DC peaks
by treating these output forecasts as DC power or by undoing a fixed efficiency
when clipping may already have occurred.

The installed client uses the rooftop-site forecasts endpoint. Solcast documents
[PV output as AC output](https://docs.solcast.com.au/docs/output-parameters).
Observed Deye PV telemetry exceeded 12 kW in 179 samples in a partial October 3
history window; a 17.1 kW sample coincided with approximately 12.13 kW battery
charging and 4.66 kW inverter output. This supports the direct DC charging path,
but does not prove uncurtailed potential can be inferred during clipping.

Available BMS inputs are `sensor.deye_battery_charge_limit_current` and
`sensor.deye_battery_voltage`; the fast automation already uses them. A sample
251 A at 54.687 V implies about 13.7 kW, before the automation's 250 A cap.
Recent BMS limits vary substantially even near 90% SOC, so they do not yet
establish a validated future taper curve. Verify current/voltage/power sensor
semantics and timing before learning acceptance from those channels.

A local irradiance sensor could help validate available sunlight during clipping,
when inverter PV telemetry understates potential production. It cannot recover
an afternoon cloud forecast from current conditions alone. Weather-station
purchase is not a prerequisite; first establish forecast/model error using the
existing telemetry and identify whether irradiance is the missing measurement.

## Control ownership and HA tuning

The manager publishes timestamped validity/reason, battery completion shortfall,
clipping estimate, headroom requirement, battery charge recommendation and EV
allowance from the same plan. Recommendations alone do not write actuators.

The battery automation remains the daytime current actuator, with local BMS and
electrical limits. The EV automation retains whole-amp 6–32 A control, manual
charge-to-target ownership, one-shot stale-session recovery and the 13.5 kW
essential-load ceiling. Explicit ownership must prevent manager and automation
from issuing competing EV writes.

Brief clouds reduce EV current toward 6 A. Sustained completion risk at minimum
current permits stopping; sustained recovered budget/live surplus permits
restart. Timer values and margins belong in HA settings/helpers. Manual takeover
and electrical safety override those timers. Re-check current ownership and
conditions after every delay and immediately before every actuator write.

Invalid planning data blocks new solar starts and current increases. Running
sessions get bounded ride-through subject to live discharge/import limits.
Stale recommendations must not indefinitely preserve battery headroom.

Reuse existing capacity, battery target, efficiency and forecast buffer controls.
Add only missing physical limits, forecast-risk and actuator hysteresis controls.
Changes to these values must refresh decisions without integration reload.

Implemented in the development branch: `ev_solar_target_soc` is a number entity
with an 80% default, separate from `ev_manual_target_soc`. It applies when solar
charging is enabled outside the cheap-grid window. Manual charging keeps its
selected target and normal overnight charging keeps its existing 80% cutoff.
Tests exercise a live options refresh without reload and independent cutoff
decisions. The new number requires the integration update once to become
available; subsequent adjustments do not require another deployment.

## Completion evidence still required

- Pure physical conservation tests: DC capture above AC limit, full battery,
  taper/BMS restriction, EV/export competition, conversion losses, low PV.
- Horizon tests: late PV cannot compensate for a missed acceptance window;
  low-PV days, clear days, cloud recovery, seasonal/DST deadlines and missing
  forecast data; infeasible targets reported explicitly.
- Regression tests preserve overnight reserve/top-up and manual ownership.
- HA tests show settings apply without deploying or restarting the integration.
- Replay telemetry/forecast days and compare predicted completion/clipping.
- Advisory comparison precedes control handover; retain rollback automation
  copies, inspect live traces, integer OCPP requests, dwell/restart behavior,
  and absence of competing writers after deployment.
- Year-round behavior needs seasonal scenario coverage as well as live evidence;
  a passing midday snapshot is not proof of the overall goal.

Development validation on October 3: 228 tests pass. A live-data diagnostic at
86.45% house SOC and 1.463 kW estimated non-EV load gave last net-positive
forecast deadlines of 17:30 (P10) and 18:30 (P50/P90), before 19:38 sunset.
That diagnostic deliberately used AC forecast output as a proxy with ideal
inverter/discharge conversion, no taper, no reserve and no safety buffer. It
validated parser-to-envelope compatibility only; it is not a production plan
or evidence of target feasibility with the complete model.
