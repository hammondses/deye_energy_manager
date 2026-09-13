# Cooling controls without restarting HA

Once the overhaul version is installed, all cooling number/switch controls apply
live and persist in the integration's config entry. Find them on the Deye Energy
Manager device or under Configure → Cooling. Editing a value does not restart HA
or reload the integration. Changing the cooling interval replaces only that timer.
Installing new Python code is a separate deployment step, not a tuning operation.

The existing integration already applies ordinary number changes in place. This
branch adds the missing timing and recovery controls and removes the hidden 48 C
override. Existing user settings are preserved when upgrading.

| Control | Default | Effect |
| --- | --- | --- |
| Cooling target temperature | 45 C | Aim for this heatsink temperature. |
| Cooling target deadband | 1 C | Band either side of target where trend matters. |
| Cooling emergency temperature | 48 C | Request 100% external fan at this reading; no hidden cap. |
| Cooling recovery trigger temperature | 50 C | Latch recovery cooling after a hot AC reading. |
| Cooling recovery release temperature | 44 C | Release recovery at or below this AC reading. Set below the trigger. |
| Cooling update interval | 5 s | Evaluate cooling every 1–60 s, independently of energy/EV decisions. |
| Cooling trend window | 60 s | Measure direction over the latest 30–300 s of readings. |
| Cooling trend minimum observation | 30 s | Require 5–30 s of observations before using a slope. |
| Cooling trend deadband | 0.2 C/min | Ignore smaller slopes as jitter. |
| Cooling maximum feedback step | 10% | Cap of 1–10 percentage points per fresh report; existing saved values are preserved. Minimum hunt uses 1% inside the target band and grows with error outside it. |
| Cooling temperature stale timeout | 60 s | Treat older reports as missing; adjustable 15–600 s. |
| Cooling minimum active fan | 10% | Lower active-fan bound in the existing controller. |
| Cooling maximum normal fan | 70% | Normal-operation ceiling; emergency/recovery can use 100%. |
| Cooling failsafe fan | 50% | Missing-temperature floor; never reduce an already higher speed. |
| Cooling curve idle fan | 15% | Baseline contribution before load/temperature adjustments. |
| Cooling curve fan per kW | 3.5%/kW | Load contribution to the baseline. |
| Cooling temperature gain | 5%/C | Curve correction; in minimum hunt, scales adjustment size with temperature error outside the target band. |

Temperature thresholds/deadband accept 0.1 C increments. Existing controls also
cover fan-failure trip temperature, trip delay, minimum RPM, and the Deye limits
to restore manually after protection. Control toggles remain explicit and are
never enabled by changing a tuning value.

The minimum-hunt switch selects the trend-based controller. With the default
45 C target, 1 C deadband and 5%/C gain, a trend inside 44–46 C requests a
1-point correction; 0.5 C outside the band requests 3 points, 1 C requests 5,
and 2 C requests 10 (subject to the configured cap). A hot but clearly falling
reading still holds speed. Emergency/recovery overrides remain immediate.
The curve-per-kW and idle controls govern the other mode. Recovery thresholds describe our external
fan policy, not verified internal-fan specifications. DC temperature is currently
being observed; it is not a second proven recovery trigger. The 65 C DC start
observation and unknown DC stop threshold still need validating.

Use [cooling-tuning-card.yaml](cooling-tuning-card.yaml) as a manual dashboard card.
It uses the current household entity names; adjust the prefix if HA assigns a
different name. It does not require custom frontend components. Temperature graphs
use the live source sensors, including the DC sensor mapped to `sensor.deye_dc_transformer_temperature`. Change one setting at a time and observe the temperature slope
and fan response before the next adjustment. A target does not guarantee no overshoot.

Sunsynk capture remains a separate add-on setting: both AC/DC channels currently
poll every 5 s, publish every change and have a 15 s scheduled report. Editing those
settings requires an add-on restart, not an HA restart. A faster manager interval
cannot create temperature samples the add-on has not supplied.

## Observing and restoring tuning (0.6.0b5)

Use the companion card's `overhaul` branch (0.4.0-beta.1) for live numbers,
AC/DC history, fan commands, and the Energy/Timeline views. The integration also
exposes these as ordinary entities for native HA dashboards.

Press **Mark internal fan started/stopped** when you hear a transition. The
persistent timeline records both temperature values and their individual report
timestamps, external fan percentage/RPM, PV, AC and battery power. These are manual
observations, not inferred fan states or verified hardware thresholds.

**Save cooling preset** stores one known-good tuning configuration. **Restore
cooling preset** restores its numeric tuning and trend-step option in one update,
leaving actuator gates unchanged. Both operations appear in the timeline.

The latest 50 events survive manager reloads. Identical recommendations with only
new timestamps or numeric explanation changes do not append events. HA automation
consumers can listen for `deye_energy_manager_event` and filter `entry_id`/`kind`.

Deployment status: manager/card changes remain on their respective overhaul
branches. The live MQTT birth/will messages were changed to retained messages;
a new subscriber confirmed retained `online`. The default DC entity mapping and
HA options-dialog compatibility fix are staged here and require installation.
The bedroom heating implementation remains in the manager pending a separate
migration that preserves its current behavior and automation dependencies.

## Unchanged MQTT temperatures (0.6.0b6)

HA's MQTT sensor can receive repeated numeric readings without updating the
entity's `last_reported`. Treating that timestamp as the polling heartbeat caused
false 50% failsafe bursts followed by repeated downward steps.

The manager now uses the latest non-retained numeric receipt on that entity's
configured MQTT state topic, provided its value matches the entity. The existing
60-second timeout still applies to that receipt. Unrelated MQTT activity cannot
keep a temperature alive. This also lets an unchanged temperature flatten the
trend, without forcing duplicate recorder writes.

This uses HA's existing bounded MQTT receive cache. If MQTT metadata is absent or
its internal layout changes, the manager falls back conservatively to the entity
timestamp. Tested against the installed HA Core 2026.8.3. AC and DC manual
observation timestamps use the same receipt handling.


## Thermal lag

A new report is not proof that the heatsink has responded to the last speed
change. The one-report/one-command guard fixes duplicate escalation; smaller
near-target steps reduce its size but do not establish closed-loop stability.
Observe complete warming/cooling cycles after deployment. Do not infer that a
historical-input replay predicts temperatures with different airflow.

Ambient temperature is not required by this controller: its effect appears in
the measured heatsink response. The garage sensor may be used for comparison,
but its placement may not represent inlet air; no ambient compensation or new
sensor dependency is introduced here.

## 13 September: normal curve cycling (v0.6.0b11)

After minimum hunt was disabled, 14:15–14:37 NZST history still showed fan speeds
27–100% with AC at 44–47.2°C. Inspection identified a separate normal-curve cliff:
it demanded maximum fan one degree below emergency. The load-collapse branch also
allowed an immediate drop to the raw curve without a bounded thermal reduction.

The normal curve now increases temperature demand continuously from target to
emergency, and a load fall no longer bypasses thermal feedback or the maximum
reduction step. A stable temperature at target holds existing fan demand through
a cloud. Full emergency, stale-temperature and recovery behavior remain intact.
This is a bounded correction, not a validated replacement thermal model. Minimum
hunt remains off on this installation. DC-driven control is still outstanding;
these changes do not establish protection against the observed 65.8°C DC peak.
