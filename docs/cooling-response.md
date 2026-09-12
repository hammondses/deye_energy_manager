# Faster cooling — staged on overhaul

This change is not deployed. The installed manager remains v0.5.69 until a
separate cutover. The stock external fans were removed; the external replacement
fans and fan-failure protection must remain. The remaining internal fans reportedly
start at AC temperature 50 C and stop at 40 C.

The inspected Sunsynk add-on uses `single-phase-16kw` definitions with
`/share/hass-addon-sunsynk/mysensors.py`. Radiator temperature comes from the common
single-phase register 91 at 0.1 C resolution; the custom converter does not need
changing. HA exposes this as `sensor.deye_ac_temperature`.

Current radiator schedule: read every 15 s, report every 60 s or a 1 C change.
DC transformer temperature is read every 15 s and reported every 300 s or 1 C.
HA history confirms approximately those reporting intervals.

## Cutover settings

Replace the existing radiator entry in the add-on's SCHEDULES (keep other entries):

```yaml
- KEY: radiator_temperature
  READ_EVERY: 5
  REPORT_EVERY: 15
  CHANGE_ANY: false
  CHANGE_BY: 0.3
  CHANGE_PERCENT: 0
```

This checks for changes every five seconds, publishes on a 0.3 C change, and sends
a scheduled report every 15 seconds. Polling faster does not guarantee that the
inverter itself produces a new measurement each time. Scheduled reports use the
add-on's averaging. Back up the existing add-on options, apply through Supervisor,
restart the add-on, and verify fresh HA reports and absence of Modbus timeouts
before installing the branch manager. Do not edit its converter or credentials.

Set the existing manager target number to **38 C** and emergency temperature to
**48 C** at cutover. The live values inspected were 40 C and 52 C. Defaults do not
overwrite existing user options. The new controller caps full-speed activation at
48 C even if an old emergency option is higher; a lower configured value is honoured.
These are initial tuning values, not a guarantee that temperature cannot exceed 50 C.

Cooling evaluates every five seconds, using a 30–60 second temperature trend.
An ordinary adjustment requires a fresh temperature report; repeated evaluations
do not keep stepping the fan on the same sample. Emergency and failsafe increases
bypass that restriction. Energy/EV/climate control retains its 30-second timer.

At 50 C, persist a recovery flag and command 100% external fan until a valid reading
is at or below 40 C. Missing readings cannot clear recovery. Without stored recovery
state, assume recovery is needed until a cool reading establishes otherwise. This
tracks a temperature-based inference, not measured internal-fan status. Existing
hot fan-failure inverter protection and manual restore remain separate.

## Recording

Live HA states and the controller do not depend on Recorder. Merge these entries
into the existing Recorder exclusion list if fast history is not wanted:

```yaml
recorder:
  exclude:
    entities:
      - sensor.deye_ac_temperature
      - sensor.garage_deye_energy_manager_inverter_ac_temperature
      - sensor.garage_deye_energy_manager_cooling_temperature_error
      - sensor.garage_deye_energy_manager_cooling_temperature_trend
      - sensor.garage_deye_energy_manager_cooling_temperature_trim
      - sensor.garage_deye_energy_manager_cooling_reason
```

Excluding only the source leaves duplicated manager temperature history. These
exclusions remove future detailed history/statistics for these entities; retain a
slower sampled temperature entity if graphs are wanted. Existing Activity filters
are separate. Check configuration before restarting HA to load Recorder changes.

References: [Sunsynk schedules](https://kellerza.github.io/sunsynk/reference/schedules),
[HA Recorder](https://www.home-assistant.io/integrations/recorder/),
[HA report timestamps](https://developers.home-assistant.io/blog/2024/03/20/state_reported_timestamp/).
