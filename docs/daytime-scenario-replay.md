# Offline daytime scenario replay

Run the deterministic, offline check from the repository root:

```sh
python3 tools/replay_daytime_scenarios.py
```

Run one scenario or request JSON output with:

```sh
python3 tools/replay_daytime_scenarios.py --case target_unreachable --json
```

The tool imports the pure solar advisory modules only. It does not connect to
Home Assistant, read live state, or call any service. Its four checks are
algorithm smoke scenarios, not a year-round energy-yield proof or a forecast
backtest.

## Synthetic assumptions

- The horizon starts at 07:00 UTC on a fixed synthetic date and runs in
  five-minute steps. PV follows a symmetric half-sine curve from zero at
  horizon edges to the case's configured peak; there are no clouds or forecast
  errors.
- The forecast P10, P50, and P90 curves are identical and each equals the
  synthetic DC curve multiplied by 0.96. This intentionally treats the
  synthetic forecast as an AC-side proxy; it is not sourced from Solcast or a
  measured PV profile.
- The model uses a 32 kWh battery, a 3.2 kWh reserve, 1.6 kW non-EV house load,
  94% battery charge/discharge efficiency, 96% inverter efficiency, a flat
  13.5 kW BMS/charge-acceptance ceiling, 12 kW inverter AC limit, 10 kW export
  limit, and 13.5 kW site AC limit. Forecast safety buffer is zero.
- The EV is always allowed and hungry, requested current is capped at 32 A,
  and each amp is modelled as 0.24 kW. There is no Taycan 80% target or
  departure-time requirement in this replay.
- An independent five-minute power ledger then allocates house and EV AC load,
  accepted PV battery DC charge, export and residual clipped PV. A house deficit
  draws from the home battery down to the 10% reserve; any remaining shortfall
  is explicitly counted as grid import. The EV is never served from battery
  energy, and its requested amps are checked against live synthetic PV support.

Because the solar planner and the separate energy ledger make independent
simplifications, these numbers are useful for repeatable behavior checks only.
In particular, zero estimated clipping here does not establish that the real
system captures all DC PV above the inverter AC limit. Real battery taper,
forecast uncertainty, seasonal daylight, voltage/current limits, inverter
conversion behavior and actual EV availability need separate validation.

## Baseline results

Running the command above produced:

| Scenario | Horizon / peak PV / starting SOC | Plan feasible at start / any step | Actual maximum / ending SOC | Actually reached 100%? | EV | Estimated clipped PV | House grid import |
|---|---:|---:|---:|---:|---:|---:|---:|
| `short_low_solar` | 8 h / 8 kW / 60% | yes / yes | 100.00% / 98.53% | yes | 13.56 kWh | 0.000 kWh | 0.000 kWh |
| `long_high_solar` | 12 h / 16.5 kW / 30% | yes / yes | 100.00% / 98.94% | yes | 62.24 kWh | 0.000 kWh | 0.000 kWh |
| `medium_solar` | 10 h / 12 kW / 40% | yes / yes | 100.00% / 98.78% | yes | 38.00 kWh | 0.000 kWh | 0.000 kWh |
| `target_unreachable` | 4 h / 1 kW / 20% | no / no | 20.00% / 10.00% | no | 0.00 kWh | 0.000 kWh | 1.067 kWh |

“Reachable at start” and “reachable at any step” come from the advisory's
receding-horizon feasibility answer. “Maximum SOC” and “ending SOC” come from
the separate approximate energy ledger. The low-solar case demonstrates that
the tool preserves and reports the planner's unreachable result rather than
assuming every day can finish the battery. It also drains the battery only to
its configured reserve, counts the remaining house shortfall as grid import,
and leaves EV energy at zero.
