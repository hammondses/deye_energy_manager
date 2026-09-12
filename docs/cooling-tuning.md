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
