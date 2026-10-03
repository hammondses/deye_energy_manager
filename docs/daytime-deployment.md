# Daytime solar planner deployment notes

This is a deployment checklist, not authorization to change the live manager or
charger. The inspected live Home Assistant copy is `0.6.0b11`; the repository
checkout at inspection was `0.6.0b17`. The live manager entry is loaded. Its
persisted options currently have `advisory_enabled=true`,
`deye_control_enabled=true`, `ev_control_enabled=true`,
`grid_charge_control_enabled=true`, and no `daytime_plan_enabled` or
`daytime_ev_writer` setting. Those live control gates are existing state and
must not be changed as part of installing advisory code.

## What reloads what

- **Updating Python files:** plan one Home Assistant Core restart after copying
  the new integration files and manifest into the mounted configuration. A
  config-entry reload unloads and sets up the existing integration entry again;
  it is a runtime reconnect/re-setup, not a reliable Python module re-import.
  The planner's new code and new platform entities must therefore be verified
  after a Core restart. The normal Home Assistant config-entry reload remains
  useful for option changes and recovery, but it must not be treated as proof
  that changed Python source has loaded. Home Assistant describes config-entry
  reload as unloading and setting the entry up again ([reload action docs](https://www.home-assistant.io/actions/homeassistant.reload_config_entry/)); its loader caches imported components and platforms ([Home Assistant loader source](https://github.com/home-assistant/core/blob/dev/homeassistant/loader.py#L1038)).
- **Changing numeric/text/switch/select options:** the manager's entities write
  config-entry options and request a coordinator refresh. These settings do
  not require a Core restart. The integration update listener also refreshes
  the coordinator in place for ordinary option changes.
- **Changing the entity map or configured heat-load list:** the update listener
  explicitly reloads this config entry because registered state listeners and
  entities may change. This is still only a config-entry reload; it does not
  reload edited Python modules.
- **Reloading HA automations:** use the automation reload only after editing
  automation YAML. The manager's Python update and its automation reload are
  independent operations, so the actuator automation can be reloaded without
  restarting HA after its own configuration is changed.
- Home Assistant's config-entry reload action is available as
  `ha_reload_core(entry_id=<manager entry id>)` in the connected HA tools. It
  reloads that integration instance only; do not use it as the Python-source
  deployment step.

The manager's option entity unique IDs use
`<config-entry-id>_<option-key>`. Sensor entities similarly use
`<config-entry-id>_<sensor-key>`. Resolve actual entity IDs from the entity
registry by unique ID after deployment; do not predict them from display names
or hardcode a config-entry ID in reusable automation YAML.

## Minimal staged rollout

1. Save a timestamped backup of the entire currently installed integration
   directory and record its manifest (`0.6.0b11`) before replacing files. Keep
   the existing Home Assistant config-entry options and automation backups.
2. Validate the candidate integration and focused tests in the repository.
   Copy the reviewed candidate files and matching manifest to the mounted
   integration directory, then perform one Home Assistant Core restart. Do not
   change Deye/inverter options during this code installation.
3. Confirm the loaded entry is healthy, its manifest is the intended version,
   no setup errors appear, and resolve new planner sensors and tuning controls
   by unique ID. The live 32 kWh manager capacity is the owner's selected model
   capacity; preserve it.
4. Leave the `daytime_plan_enabled` switch option off initially. Set the EV
   power entity map through the manager's Configure → Entities flow
   to `sensor.evcharger_power_active_import`. The new coordinator boundary
   converts an entity whose unit is `kW` to watts; it rejects unknown units and
   falls back to current × voltage. Do not hand-edit `.storage` or use this
   sensor as watts. This map change is expected to reload only the manager
   entry. Verify base-load subtraction against `essential power - EV power`.
5. Review the new tuning controls against the installation: 16.56 kW array,
   8° tilt, 2° azimuth, 18 kW PV DC ceiling, 12 kW inverter AC cap, 10 kW
   export cap, 13.5 kW site ceiling, actual battery capacity and the currently
   available BMS charge limit. Solar-planner azimuth uses clockwise degrees
   from north; Solcast uses negative east / positive west, so Solcast `-2°`
   maps to planner `+2°` (2° east of north). Keep that sign conversion explicit
   when checking the roof orientation. The acceptance-curve option defaults
   empty and the planner reports invalid until it is supplied. For advisory
   comparison only, an explicitly provisional engineering curve can be entered
   using the observed battery behavior as a starting estimate, for example
   `[[0,13.5],[0.85,13.5],[0.90,6.8],[0.96,3.0],[0.99,0.5],[1.0,0.0]]`.
   Label and treat such values as provisional; compare predicted acceptance
   with BMS/charge history before using any planner output to control hardware.
   Leave forecast risk blend at its configured value until P10/P50 behavior has
   been compared.
6. After verifying inputs and source age, enable the `daytime_plan_enabled`
   switch option to calculate advisory outputs. It gates advisory calculation and
   does not itself actuate inverter or EV hardware. Review status/reason,
   forecast source time, target reachability, and clipping/advisory outputs over
   representative daylight data; no Deye actuator should consume them during
   this validation stage.
7. Prepare the replacement EV automation disabled and complete review of its
   integer OCPP profile payload, manual-override guards, hysteresis, and delayed
   ownership checks. Do not select external ownership in advance: the existing
   solar automation and manager may still both issue stop/start actions.
8. For a daytime cutover, use one coordinated sequence: disable the old EV
   solar automation, select `external_automation` in the manager's **Daytime EV
   charger writer**, then enable the reviewed replacement automation. The new
   writer setting yields non-manual manager charger start/stop decisions from
   07:00 through 20:59; manual charge-to-target and overnight manager ownership
   remain in place. Do not change the independent battery/inverter gates or
   overnight reserve logic. Verify single ownership in traces after the
   sequence; do not induce test commands on the live charger.

## Runtime configuration route

Use the Home Assistant integration Configure flow or its option entities;
don't edit `.storage` directly.

- The `Entities` menu exposes the `ev_power` mapping and saving it causes a
  manager entry reload.
- `daytime_plan_enabled` is a switch option. The array/inverter/forecast tuning
  values are number options, and `solar_plan_charge_acceptance_curve` is a text
  option. These options are refreshed by the manager coordinator without a
  Home Assistant restart.
- `daytime_ev_writer` is the `Daytime EV charger writer` select. Its default is
  `manager`; select `external_automation` only at the explicit ownership
  handover step.
- The current live options contain `ev_control_enabled=true`. Do not turn this
  off as a shortcut for external daytime ownership: the new writer option is
  specifically scoped to non-manual daytime charger start/stop. Leave
  manual/overnight and battery-reserve behavior intact.

## Rollback

If the entry fails to load or the new advisory behaves incorrectly:

1. Disable the daytime planner switch if it is available. For a cutover
   rollback, disable the replacement automation, set the manager's Daytime EV
   charger writer back to `manager`, then re-enable the old EV solar automation.
   Verify manual and overnight behavior remains manager-owned.
2. Restore the timestamped pre-deployment integration directory and its
   matching `0.6.0b11` manifest, then restart Home Assistant Core once so the
   restored Python modules are imported.
3. Restore only the backed-up manager options that were changed during rollout.
   Do not reset/reconfigure the Deye inverter. Confirm the manager entry is
   loaded and the original actuator options and EV automation are present.

No runtime option, automation, integration file, or inverter setting was
changed while preparing this checklist.
