# Daytime battery-current automation handover proposal

> **Live status, 3 October 2026:** `0.6.0b20` is deployed and both original
> battery/EV automations are enabled against the shared manager plan. See the
> [live handover record](live-solar-handover-2026-10-03.md) for current settings,
> validation limits and rollback. The inspection snapshots and proposed rollout
> steps below are historical; statements that entities are absent or the
> handover is still disabled describe the pre-deployment audit, not current HA.

This is a review proposal only. It changes no Home Assistant state and does not enable the existing inverter automation. The handover remains off until the manager outputs are live and the planner has a configured, validated battery charge-acceptance curve.

## Current actuator path

The live `automation.deye_dc_export_first_curtailment_capture` runs every 10 seconds and on grid CT changes. In its active branch it requires the existing solar-management switch, valid Solcast data, grid connected, export enabled, grid charging off, after 07:00, forecast remaining above 0.1 kWh, and SOC above both reserve floors. These conditions should remain intact.

The automation currently reads `sensor.deye_shadow_recommended_charge_power` in watts and derives an inverter AC target from `sensor.deye_pv_power`:

```text
export_ac_w       = max(0, -grid_ct_w)
house_ac_w        = max(0, inverter_ac_w - export_ac_w)
target_ac_w       = min(inverter_rated_ac_w, house_ac_w + export_limit_ac_w)
legacy_charge_w   = shadow_recommended_charge_power_w
scheduled_ac_w    = max(house_ac_w,
                        min(target_ac_w, max(0, pv_w - legacy_charge_w)))
```

It then computes the current-gate request from observed battery charging plus the AC-output error, clamps to the BMS current limit, and probes up by 1 A when the gate appears binding. Preserve the legacy expression unchanged as the stale-plan fallback. In particular, do not apply the new efficiency conversion to the fallback path; that would alter current behavior when the manager is unavailable or reloading.

## Proposed handover gate

Add one explicit helper, `input_boolean.deye_battery_plan_handover_enabled`, default **off**. The new path is eligible only when this helper is on, the existing active-branch conditions above pass, manager status is exactly `advisory`, and the generated timestamp is no more than 90 seconds old and no more than 5 seconds in the future. The manager refreshes around every 30 seconds, so this allows three refresh intervals. Missing entities, invalid numeric inputs, an unavailable plan, a stale timestamp, or a nonpositive battery voltage selects the unchanged legacy shadow-charge path.

This is the only new automation tuning helper. Reuse the manager's existing inverter-efficiency number, configured DC ceiling, active solar-management switch, BMS limit, and physical clipping-window helper. The manager's `daytime_plan_enabled` and charge-acceptance-curve options remain prerequisites for emitting an advisory; they are not duplicated in the automation.

Expected manager entities (verify the final entity IDs after the manager package is loaded):

- `sensor.garage_deye_energy_manager_solar_plan_status`
- `sensor.garage_deye_energy_manager_solar_plan_generated_at`
- `sensor.garage_deye_energy_manager_solar_plan_recommended_battery_dc_power` (kW DC)
- `number.garage_deye_energy_manager_solar_plan_inverter_efficiency` (existing manager option)

These plan sensor IDs are not present in the current live entity registry. The integration option `daytime_plan_enabled` currently defaults off, and `solar_plan_charge_acceptance_curve` is empty. Until the new entities exist and the manager emits a valid advisory, the helper cannot switch the automation off the legacy path. Require the efficiency number entity to be present and in `(0, 1]`; do not silently substitute a separate hardcoded efficiency in the handover path.

## Handover calculation

The planner output `recommended_battery_dc_power` is a DC-side power request in kW. It must not be used as an AC inverter target or as a current value. Convert it to W, then constrain it by live BMS and inverter limits:

```text
eta                  = inverter efficiency (0 < eta <= 1)
bms_dc_limit_w       = max(0, bms_charge_limit_a * battery_voltage_v)
inverter_dc_limit_w  = configured_max_battery_dc_kw * 1000
plan_request_dc_w    = max(0, plan_recommended_dc_kw * 1000)
plan_dc_w            = min(plan_request_dc_w,
                           bms_dc_limit_w,
                           inverter_dc_limit_w)
pv_for_inverter_ac_w = max(0, pv_dc_w - plan_dc_w) * eta
scheduled_ac_w       = max(house_ac_w,
                           min(target_ac_w, pv_for_inverter_ac_w))
```

`pv_dc_w` is `sensor.deye_pv_power`; it is currently reported in W. `house_ac_w` remains the existing live estimate, `max(0, inverter_ac_w - max(0, -grid_ct_w))`, so actual EV draw remains in the measured load. The conversion uses `eta` because the remaining PV DC must be converted to AC to compare with the inverter AC target. Do not multiply or divide the battery DC recommendation itself by inverter efficiency.

`plan_dc_w` is the manager's current intentional charge request, constrained to what the live BMS and hardware can accept. It is not a hard current ceiling: the planner sees measured PV, which can already be curtailed by the inverter. Preserve the existing bounded 1 A hidden-PV probe when the AC target is met and the current gate is binding. The probe may move above the minimum plan request, but never above live BMS, 250 A, or configured inverter DC limits. It must not probe when those live limits leave no headroom. Do not add an SOC==100 hard-zero: use the live BMS limit, which can be zero while full and can become positive again if SOC falls.

The feedback correction also needs consistent units. The existing AC error is converted back to equivalent DC before calculating battery current:

```text
measured_battery_dc_w = max(0, -battery_power_w)
desired_battery_dc_w  = max(0,
                            measured_battery_dc_w
                            + (inverter_ac_w - scheduled_ac_w) / eta)
current_ceiling_a     = min(bms_charge_limit_a,
                            250,
                            inverter_dc_limit_w / battery_voltage_v)
desired_limit_a       = clamp(round(desired_battery_dc_w / battery_voltage_v),
                              0,
                              current_ceiling_a)
probe_limit_a         = min(current_limit_a + 1, current_ceiling_a)
```

The power signs match the live automation: battery charging is negative `sensor.deye_battery_power`; grid export is negative `sensor.deye_grid_ct_power`. The battery-current control remains the fast feedback actuator. Keep its 60 W AC deadband and existing rate/trigger behavior. Keep the current probe's existing conditions (AC error within 60 W, measured charge near the current limit, and current limit below the live BMS limit), with `probe_limit_a` also respecting the 250 A and configured DC ceilings. Do not cap the probe by `plan_dc_w`; a small bounded probe is how the controller can detect PV output hidden by curtailment.

## Preserve the late-day all-surplus rule

The manager's current recommendation is an action for the next forecast interval: it charges only enough to protect target completion plus PV that would otherwise be physically clipped. It does not by itself encode “charge with all PV after house load once the physical clipping window ends.” Do not let the recommendation weaken that existing rule.

The b16 development planner publishes `solar_plan_physical_clipping_remaining`,
`solar_plan_physical_clipping_window_end` and `solar_plan_charge_all_surplus`.
Its release envelope uses the empirical clear-sky curve with a 1.1 enhancement
factor, independently of the weather-scaled capture projection. This remains
an empirical estimate, not a guarantee. Geometry and overall scale are HA
settings. A cloudy current observation cannot shorten this release envelope.

When no remaining envelope interval exceeds
`min(inverter_ac_limit, non_ev_base_house + export_limit) / eta`, the planner
keeps its completion-safe EV recommendation and requests all remaining live
PV for the battery, within BMS/hardware limits. The automation should consume
that resulting charge recommendation, without a duplicate late-day calculation
or new dependency on shadow helpers. Missing envelope data must not mean that
the clipping window has ended. Verify the new entities before enabling handover.

## Priority and coordination notes

The manager chooses `recommended_ev_amps` and `recommended_battery_dc_power` as one plan. The OCPP automation may ramp actual EV current after the manager calculates that plan. The battery automation should continue using actual inverter/export measurements and live house load, which includes the EV, rather than pretending the requested EV amps are already flowing. This keeps the battery gate responsive during ramp-up/down. A short export/battery-charge mismatch can still occur until the next manager refresh; the battery loop must never discharge the house battery to chase the plan.

The existing post-clipping rule and manual boundaries remain higher priority than a stale or missing plan: preserve the current solar-management switch, grid-charge-off condition, grid-connected/export-enabled checks, and both SOC floors. Do not make plan status, completion reachability, or an unvalidated physical capture estimate a new actuator permission. `target_reachable=no` may still have a useful battery-current recommendation to salvage available PV; the recommendation can be consumed while the existing hard gates hold.

## Review and validation before any live handover

1. Confirm the three manager output entity IDs and units, the inverter-efficiency source, and that status/timestamp remain fresh through a manager reload.
2. Confirm the acceptance curve is populated from reviewed evidence and the plan status becomes `advisory` only for valid, fresh inputs.
3. Compare the proposed `plan_dc_w`, AC target, and current target with live traces at low PV, high PV, close to export cap, a changing EV load, and SOC taper.
4. Verify the manager releases headroom only when its envelope shows no remaining clipping opportunity and targets PV surplus after house/permitted EV load.
5. Keep `input_boolean.deye_battery_plan_handover_enabled` off through those checks. No inverter or automation change is included here.
