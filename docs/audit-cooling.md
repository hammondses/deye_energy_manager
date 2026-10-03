# Cooling audit

## Scope and version evidence

This audit is for the current repo state, now aligned with the reported live install: release `v0.5.69` plus audit documentation. Earlier checkout evidence from `v0.5.46` is obsolete for cooling because `v0.5.69` adds minimum-hunt mode, fan-health telemetry, and inverter protection actions.

Live evidence reported separately:

- The live integration manifest was `0.5.69`.
- Live `decision.py`, `coordinator.py`, `models.py`, and `const.py` byte-matched tag `v0.5.69`.
- Live cooling-related toggles were reported on: cooling control, minimum hunt, and fan failure protection.
- Live cooling settings measured now: target `40C`, deadband `1C`, emergency `52C`, fan failure trip `50C`, fan failure delay `5min`.
- Live protection state measured now: fan failure protection is enabled, but protection required is off and protection active is off.
- The user's hardware observation is that internal inverter fans turn on at `50C` and turn off at `40C`. This is treated as observed hardware behaviour, not repo-derived evidence.

The ESPHome fan controller snapshot at [fan-controller.yaml](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/homeassistant-config-snapshot/esphome/fan-controller.yaml:1) appears to be a simple actuator/telemetry device: its YAML requests fan-on at 20% on boot, controls PWM on GPIO5, controls a relay on GPIO7, exposes a Home Assistant speed fan, and publishes RPM from a pulse counter. It does not contain the inverter cooling policy; policy lives in this integration or in HA automations. This audit did not verify that the snapshot exactly matches the flashed device state.

## What exists now

Cooling has three layers:

1. Fan percentage recommendation.
2. Fan health/protection decision.
3. Inverter safety writes when protection trips.

The recommendation engine is a load-fed fan curve with temperature feedback. Throughput is the max absolute value of PV, inverter AC output or essential load, and battery power. Baseline fan percent is idle fan plus throughput kW times percent per kW, capped at max normal fan. Temperature then trims the raw percentage, and emergency temperature forces 100%. See [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:42).

Repo defaults are:

- target temp `45C`
- idle fan `15%`
- fan per kW `3.5%`
- temperature gain `5%/C`
- feedback step `5%`
- target deadband `1C`
- trend deadband `0.2C/min`
- minimum active fan `10%`
- max normal fan `70%`
- emergency temp `48C`
- failsafe fan `50%`
- fan failure trip temp `50C`
- fan failure delay `5min`
- minimum running RPM `200`

See [models.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/models.py:156) and [const.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/const.py:354).

The minimum-hunt mode is a separate feedback branch. If enabled and the inverter is below emergency temp, has valid temperature, has current fan percentage, and throughput is at least 500W, it changes the fan by the feedback step based mainly on temperature band and temperature trend. It can increase above target, hold while warming toward the band, decrease below target, increase while rising inside the band, decrease while falling inside the band, or hold inside the band. See [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:118).

Automatic fan writes are gated by `inverter_cooling_control_enabled`. When enabled, the coordinator writes `fan.turn_off` for desired `0%` or `fan.set_percentage` otherwise. It suppresses repeated changes unless there is a fresh temperature sample or a large load change. See [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1340) and [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1364).

## Fan failure protection

This is not just fan control. If enabled, fan failure protection can directly change inverter export/PV/discharge behaviour.

Fan health is false when the fan controller status entity is not on, fan percentage is unavailable, or RPM is below the configured minimum. See [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:679). The default entity map expects fan status, RPM, max sell power, and max solar power entities. See [const.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/const.py:55).

Protection requires all of:

- `cooling_fan_failure_protection_enabled`
- fan health false
- valid AC temperature
- AC temperature at or above `cooling_fan_failure_temp_c`
- sustained for `cooling_fan_failure_delay_min`

See [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:195) and [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1019).

When protection trips, it runs before normal `control_blocked` handling and returns immediately after applying protection. See [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1335). It captures current max sell, max solar, and programme capacity values, then:

- sets max sell power to `0`
- sets max solar power to `0`
- sets enabled Deye programme capacities to `100%`
- sets programme charge modes to `No Grid or Gen`
- sets grid charge switch false
- applies the Deye plan with `override_gates=True`
- latches active until restore

See [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1422), [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1436), and [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1447).

The restore path is manual via `async_restore_deye_normal`; it restores captured values where available, with configured fallback restore values for max sell and max solar. See [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1315) and [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1469).

## Mismatch with the 50/40 internal fans

The external fan controller is trying to solve several problems at once:

- keep AC temp near a configurable target
- react to inverter load
- avoid large fan jumps without fresh temperature data
- hunt for a minimum speed
- fail safe if temperature data is stale
- force inverter pass-through if external fan telemetry fails while hot

The user-reported internal fan behaviour gives a simpler physical objective: avoid pushing the inverter into its own `50C` internal fan-on threshold, and avoid fighting the inverter's `40C` internal fan-off hysteresis.

The live configuration sits directly on the reported internal-fan hysteresis boundary: target `40C`, deadband `1C`, emergency `52C`, fan failure trip `50C`. With a `40C` target and `1C` deadband, the controller may still settle or hover above the internal fan-off point depending on sensor lag, sensor location, heat soak, and whether the AC temperature sensor is equivalent to the internal fan's own temperature input. Once internal fans engage at the reported `50C`, they will remain on until `40C`, which the current target-band model does not explicitly account for.

Minimum hunt makes the fan curve less load-driven, but it still optimises a target band, not the hardware hysteresis. Fan failure protection uses the same `50C` value as the reported internal fan-on point, which means the protection trip is aligned with the moment the inverter may already have started using its own fans, depending on whether both sensors see the same temperature.

## Risk

Highest risk is fan failure protection, because it can write inverter max sell, max solar, programme capacities, charge modes, and grid charge even if normal Deye/grid/EV gates are off. It may be valuable as an emergency latch, but it should be treated as an inverter-control feature, not cooling decoration.

Second risk is live dependency. The current integration exposes a large cooling surface:

- cooling switches for fan control, minimum hunt, and fan failure protection in [switch.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/switch.py:30)
- cooling number controls for curve tuning, failure thresholds, RPM threshold, and restore fallback values in [number.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/number.py:123)
- cooling sensors and binary sensors for curve internals, RPM, health, protection state, and protection reason in [sensor.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/sensor.py:74) and [binary_sensor.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/binary_sensor.py:66)

Third risk is the ESPHome boot behaviour. The YAML snapshot requests the fan on at 20% during boot, independent of this integration. The intent and actual flashed behaviour are unverified here, but any replacement policy needs to understand that Home Assistant may initially see a fan that is already on. See [fan-controller.yaml](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/homeassistant-config-snapshot/esphome/fan-controller.yaml:4).

## Minimal recommendation

Do not tune this curve further. That is where the complexity came from.

Use this staged path:

1. Keep fan failure protection separate from fan speed control. Rename/mentally treat it as inverter emergency protection.
2. Keep fan failure protection only if you want an automatic export/PV/discharge clamp on external-fan failure. If kept, leave its thresholds explicit and document the recovery button/workflow.
3. Replace fan speed control with one simple HA automation or one tiny integration branch: when AC temp reaches a chosen external-fan-on temperature, set a fixed external fan speed; when AC temp falls to a chosen external-fan-off temperature, turn it off or return to a fixed low speed.
4. Choose those external thresholds from observed data. Do not bake in new guessed thresholds. The only known physical thresholds right now are the user-reported internal `50C on / 40C off`.
5. Keep existing cooling sensors for one compatibility release, then delete curve-only sensors and numbers after checking automations.

The laziest working target is:

- ESPHome remains the fan actuator and RPM reporter.
- Home Assistant owns simple temperature hysteresis.
- This integration keeps only inverter emergency protection if wanted.
- The curve, minimum hunt, load-regime classification, and most tuning numbers go away once nothing consumes their entities.

## Delete list

- `delete:` load-fed fan curve and minimum-hunt logic. Replacement: one temperature hysteresis automation. [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:42)
- `delete:` curve tuning numbers. Replacement: external fan on/off temperatures and fixed fan speed, if automation is kept in integration. [number.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/number.py:123)
- `delete:` curve diagnostics after compatibility window: baseline, trim, raw required, load regime, calibration state. Replacement: AC temp, fan percentage, RPM, protection state. [sensor.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/sensor.py:79)
- `keep-or-delete:` fan failure protection. Keep only as explicit inverter emergency protection; delete if manual monitoring is preferred. [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1447)

## Unknowns

- No proof in the repo that the internal inverter fan thresholds are exactly `50C/40C`; that is user-observed hardware behaviour.
- No full live HA automation/Node-RED/dashboard dependency inventory has been completed.
- The ESPHome YAML inspected may be the relevant fan-controller config, but this audit did not verify the flashed device state.
