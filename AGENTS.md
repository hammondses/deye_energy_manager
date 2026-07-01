# Agent Editing Notes

This repository is a Home Assistant custom integration for `deye_energy_manager`.

Keep actuator writes behind feature gates. Defaults must remain:

- `enabled = true`
- `advisory_enabled = true`
- `deye_control_enabled = false`
- `grid_charge_control_enabled = false`
- `ev_control_enabled = false`
- `heat_control_enabled = false`
- `direct_climate_control_enabled = false`
- `pv_load_test_control_enabled = false`

Primary edit locations:

- `custom_components/deye_energy_manager/decision.py`: pure decision engine. Prefer changing behavior here first.
- `custom_components/deye_energy_manager/models.py`: dataclasses for engine inputs/settings/outputs.
- `custom_components/deye_energy_manager/coordinator.py`: Home Assistant state reads and service calls.
- `custom_components/deye_energy_manager/const.py`: default entity IDs, thresholds, select options, and feature defaults.
- `tests/components/deye_energy_manager/test_decision.py`: pure logic regression tests.

PV load testing is separate from normal heat allowance. It is for export-limited/clipped inverter behavior where expected PV is high but observed battery charge is low. Keep recommendation logic pure in `decision.py`, and keep automatic action behind `pv_load_test_control_enabled`.

Smart heat rotation uses climate `current_temperature` and `temperature` attributes. A solar-owned load near target can be shed and an unowned/off colder load can be added, but automatic control must stay behind explicit heat/direct/PV-load-test toggles.

Do not enable actuator toggles automatically. Use advisory sensors first, then enable control gates deliberately.
