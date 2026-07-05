# Agent Editing Notes

This repository is a Home Assistant custom integration for `deye_energy_manager`.

Release/HACS workflow:

- For any code or user-visible behavior change, bump `custom_components/deye_energy_manager/manifest.json` before committing, and keep `RELEASE_NOTES.md` aligned.
- HACS uses the latest GitHub release tag as the remote version, so create/push the matching `vX.Y.Z` tag after a release bump unless explicitly told not to.
- Unless explicitly told not to, commit completed repo changes and push them to `origin` after relevant checks pass.

Keep actuator writes behind feature gates. Defaults must remain:

- `enabled = true`
- `advisory_enabled = true`
- `deye_control_enabled = false`
- `grid_charge_control_enabled = false`
- `ev_control_enabled = false`
- `thermal_control_enabled = false`
- `heat_control_enabled = false`
- `direct_climate_control_enabled = false`
- `pv_load_test_control_enabled = false`

Primary edit locations:

- `custom_components/deye_energy_manager/decision.py`: pure decision engine. Prefer changing behavior here first.
- `custom_components/deye_energy_manager/models.py`: dataclasses for engine inputs/settings/outputs.
- `custom_components/deye_energy_manager/coordinator.py`: Home Assistant state reads and service calls.
- `custom_components/deye_energy_manager/const.py`: default entity IDs, thresholds, select options, and feature defaults.
- `tests/components/deye_energy_manager/test_decision.py`: pure logic regression tests.

Thermal storage is the primary climate-control concept. Do not use `target_17_soc` as a thermal start threshold. Thermal permission must use `thermal_start_min_soc`, `thermal_start_min_charge_w`, `thermal_keep_running_min_charge_w`, and forecast-full override.

PV load testing is separate from normal thermal allowance. It is for export-limited/clipped inverter behavior where expected PV is high but observed battery charge is low. Keep recommendation logic pure in `decision.py`, and keep automatic action behind `pv_load_test_control_enabled`.

Smart thermal rotation uses climate `current_temperature`, `temperature`, `hvac_action`, and optional power sensors. A solar-owned load near/tapering at soak target can be normalised and an unowned/off room needing soak can be added, but automatic control must stay behind explicit thermal/direct toggles.

Manual overrides are respected. If a manager-owned climate is off or its target was lowered below the configured solar target, clear ownership and block that load until the manual override cooldown expires. Emergency shed-all and overnight SOC protection are safety paths; keep their decision logic pure and make direct actions clear ownership flags.

Do not enable actuator toggles automatically. Use advisory sensors first, then enable control gates deliberately.
