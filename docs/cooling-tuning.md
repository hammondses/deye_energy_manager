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
| Cooling feedback step | 5% | Size of a normal fan adjustment; repeated checks of the same report cannot keep stepping. |
| Cooling temperature stale timeout | 60 s | Treat older reports as missing; adjustable 15–600 s. |
| Cooling minimum active fan | 10% | Lower active-fan bound in the existing controller. |
| Cooling maximum normal fan | 70% | Normal-operation ceiling; emergency/recovery can use 100%. |
| Cooling failsafe fan | 50% | Missing-temperature floor; never reduce an already higher speed. |
| Cooling curve idle fan | 15% | Baseline contribution before load/temperature adjustments. |
| Cooling curve fan per kW | 3.5%/kW | Load contribution to the baseline. |
| Cooling temperature gain | 5%/C | Temperature correction to the load curve. |

Temperature thresholds/deadband accept 0.1 C increments. Existing controls also
cover fan-failure trip temperature, trip delay, minimum RPM, and the Deye limits
to restore manually after protection. Control toggles remain explicit and are
never enabled by changing a tuning value.

The minimum-hunt switch selects the existing trend-based step controller; curve
gain controls govern the other mode. Recovery thresholds describe our external
fan policy, not verified internal-fan specifications. DC temperature is currently
being observed; it is not a second proven recovery trigger. The 65 C DC start
observation and unknown DC stop threshold still need validating.

Use [cooling-tuning-card.yaml](cooling-tuning-card.yaml) as a manual dashboard card.
It uses the current household entity names; adjust the prefix if HA assigns a
different name. It does not require custom frontend components. Temperature graphs
use the live source sensors, including the DC sensor whose manager mapping is
not yet corrected. Change one setting at a time and observe the temperature slope
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
