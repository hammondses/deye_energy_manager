# Faster cooling — staged on overhaul

The faster AC/DC capture schedules are live as of 12 September 2026. The
manager changes are not deployed: the installed manager remains v0.5.69 until a
separate cutover. The stock external fans were removed; the external replacement
fans and fan-failure protection must remain. The remaining internal fans reportedly
start at AC temperature 50 C. The fan was observed off when HA reported 44 C,
superseding the earlier reported 40 C threshold. The exact internal cutoff is
unknown because reporting skips intermediate readings. Use 44 C or lower as
a provisional recovery endpoint pending observations with faster reporting.
This is not evidence that AC temperature alone controls the internal fan.

On 12 September 2026, HA recorded DC transformer temperature 39.92 C at
14:40 NZST while AC was 46.05 C. AC subsequently reached 44.125 C at 14:48;
the latest DC reading was 38.4 C at 14:47. DC was therefore reported below
40 C several minutes before the reported AC 44 C observation. This does not
establish the fan cutoff: reports are averaged and there is no timestamped
internal-fan state measurement. AC-only, DC-only, and combined conditions
remain unconfirmed. Observe both temperature channels at the faster schedule
before treating the provisional recovery endpoint as a hardware rule.

The inspected Sunsynk add-on uses `single-phase-16kw` definitions with
`/share/hass-addon-sunsynk/mysensors.py`. Radiator temperature comes from the common
single-phase register 91 at 0.1 C resolution; the custom converter does not need
changing. HA exposes this as `sensor.deye_ac_temperature`.

Previous radiator schedule: read every 15 s, report every 60 s or a 1 C change.
Previously, DC transformer temperature was read every 15 s and reported every 300 s or 1 C.
HA history confirms approximately those reporting intervals.

## Cutover settings

Applied to both `radiator_temperature` and `dc_transformer_temperature` in the
add-on's SCHEDULES (all other entries preserved):

```yaml
- KEY: radiator_temperature
  READ_EVERY: 5
  REPORT_EVERY: 15
  CHANGE_ANY: true
  CHANGE_BY: 0
  CHANGE_PERCENT: 0
```

This checks for changes every five seconds, publishes every changed value, and
sends a scheduled report every 15 seconds. The installed add-on 1.2.0 Supervisor
schema silently truncates `CHANGE_BY: 0.3` to `0`; report-on-change is used
instead so small changes reach HA without modifying the converter. Polling faster does not guarantee that the
inverter itself produces a new measurement each time. Scheduled reports use the
add-on's averaging. Back up the existing add-on options, apply through Supervisor,
restart the add-on, and verify fresh HA reports and absence of Modbus timeouts
before installing the branch manager. Do not edit its converter or credentials.

Set the existing manager target number to **45 C** and emergency temperature to
**48 C** at cutover. The live values inspected were 40 C and 52 C. Defaults do not
overwrite existing user options. The new controller caps full-speed activation at
48 C even if an old emergency option is higher; a lower configured value is honoured.
The 45 C target replaces the initial 38 C proposal to balance fan noise against
thermal headroom. Rising-temperature feedback is retained: the heatsink can
continue warming after airflow increases. These are initial tuning values,
not a guarantee that temperature cannot exceed 50 C.

Cooling evaluates every five seconds, using a 30–60 second temperature trend.
An ordinary adjustment requires a fresh temperature report; repeated evaluations
do not keep stepping the fan on the same sample. Emergency and failsafe increases
bypass that restriction. Energy/EV/climate control retains its 30-second timer.

At 50 C, persist a recovery flag and command 100% external fan until a valid reading
is at or below 44 C. Missing readings cannot clear recovery. Without stored recovery
state, assume recovery is needed until a cool reading establishes otherwise. This
tracks a temperature-based inference, not measured internal-fan status. Existing
hot fan-failure inverter protection and manual restore remain separate.

Both temperature channels now use the faster schedule. The previous DC
five-minute reports were too sparse to identify a fan transition reliably.
The user also reports DC can start the internal fans at approximately 65 C;
the DC shutoff threshold is unknown, and neither DC threshold is verified. Retain both temperature
histories during this investigation and note the exact time the internal fan
starts/stops; reconsider Recorder exclusions after calibration.

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

Live capture change: Supervisor options backed up to
`/config/deye_energy_manager_backups/sunsynk-options-before-fast-temperatures-20260912T025305Z.json`
on HA, with restricted permissions. Only the two temperature schedules changed.
Only the Sunsynk add-on was restarted; HA and manager control settings were not changed.

Verification: the running add-on reports registers 90 and 91 with read 5 s /
report 15 s. HA history contains new 0.1 C changes on both entities after the
restart (AC 43.2 → 43.1 → 43.0 C; DC 35.9 → 35.8 → 35.6 C).
No Modbus timeout was found in the inspected startup log. A separate MQTT
warning says `homeassistant/status` is empty and cautions about availability
after an HA restart; investigate that birth-topic configuration separately.
