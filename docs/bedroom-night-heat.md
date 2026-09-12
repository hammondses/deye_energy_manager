# Bedroom night heat: one explicit press

Migrated on 13 September 2026 with manager v0.6.0b9.

`input_button.bedroom_night_heat` triggers `automation.bedroom_night_heat_button_only`.
Only when `climate.bedroom_heatpump` is off, it sends one `climate.set_temperature`
command with heat mode and 17°C. Already-running settings are untouched. There is
no periodic, startup, temperature or off-state trigger. Restored button timestamps
are ignored. Manual off therefore stays off; another button press is required.
The native automation is editable in HA; its deployed configuration is saved in
[bedroom-night-heat.yaml](bedroom-night-heat.yaml). Buttons are on Home and Heating.

The manager's night actuator methods and arm switch were removed. Old persisted
armed state is ignored. Legacy decision fields remain disarmed for compatibility.
The former night policy's scheduled cutoffs, charging suppression and shedding of
other rooms no longer run as part of this button. Ordinary thermal feature gates
are unchanged (thermal control was off at migration).

Removed the old arm-switch condition from the legacy cheap-grid enforcer, since
it must not depend on a deleted switch. Backups of affected live files are in
`/tmp/ha-bedroom-migration` in the development workspace. No live heat-on test was
performed because the user was going to bed; config loading and static regression
checks verify the one-shot/off-only contract without operating the heat pump.
