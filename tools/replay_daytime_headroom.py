"""Offline sensitivity replay for docs/daytime-headroom-review.md.

Run from the repository root with:
    python3 tools/replay_daytime_headroom.py
"""

from datetime import datetime, timezone
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.deye_energy_manager.solar_advisory import (
    _CurrentAction,
    SolarAdvisoryInput,
    _capture_projection,
    _current_step,
    _forecast_horizon,
    _horizon_settings,
    _required_energy_now,
    recommend_solar_action,
)
from custom_components.deye_energy_manager.solar_forecast import parse_detailed_forecast
from custom_components.deye_energy_manager.solar_horizon import plan_battery_completion


def main() -> None:
    now = datetime(2026, 3, 20, 12, tzinfo=timezone.utc)
    rows = [
        {
            "period_start": (now + timedelta(minutes=30 * i)).isoformat(),
            "pv_estimate10": 12.0,
            "pv_estimate": 12.0,
            "pv_estimate90": 14.0,
        }
        for i in range(16)
    ]
    deadline = now + timedelta(hours=8)
    forecast = parse_detailed_forecast(
        rows,
        now=now,
        deadline=deadline,
        source_updated_at=now,
        max_age=timedelta(minutes=60),
    )
    count = len(forecast.intervals)
    curve = ((0.0, 13.5), (0.85, 13.5), (0.90, 8.0), (0.95, 4.0), (0.98, 1.0), (1.0, 0.0))
    inputs = SolarAdvisoryInput(
        forecast=forecast,
        now=now,
        current_soc_pct=50.0,
        capacity_kwh=32.0,
        target_soc_pct=100.0,
        reserve_energy_kwh=0.0,
        non_ev_base_house_kw=4.0,
        current_non_ev_house_kw=4.0,
        live_pv_dc_kw=22.0,
        voltage_v=230.0,
        live_bms_max_dc_kw=13.5,
        max_battery_dc_kw=13.5,
        max_discharge_dc_kw=12.0,
        soc_charge_curve=curve,
        site_ac_limit_kw=13.5,
        inverter_ac_limit_kw=12.0,
        export_limit_kw=10.0,
        battery_charge_efficiency=0.94,
        battery_discharge_efficiency=0.94,
        inverter_efficiency=0.96,
        safety_buffer_kwh=0.0,
        physical_dc_upper_kw=(22.0,) * count,
        clipping_envelope_dc_kw=(22.0,) * count,
        max_ev_amps=0,
        ev_allowed=False,
        forecast_p50_weight=0.0,
    )

    plan = recommend_solar_action(inputs)
    horizon, _, _ = _forecast_horizon(inputs, now)
    settings = _horizon_settings(inputs)
    future = plan_battery_completion(
        horizon[1:], settings, initial_energy_kwh=16.0
    )
    required_now = _required_energy_now(
        inputs, horizon[0].duration_hours, future.required_energy_by_boundary_kwh[0]
    )
    chosen = _current_step(
        inputs,
        16.0,
        horizon[0].duration_hours,
        plan.recommended_ev_amps,
        future.required_energy_by_boundary_kwh[0],
    )
    assert plan.valid and chosen is not None and required_now is not None
    print(
        "current policy:",
        f"command={plan.recommended_battery_dc_kw:.3f} kW DC",
        f"captured={plan.clipping_captured_kwh:.3f} kWh DC",
        f"potential={plan.clipping_potential_kwh:.3f} kWh DC",
        f"terminal={plan.physical_scenario_soc_trajectory[-1]:.1f}% SOC",
    )

    for request in (0.0, 1.0, 3.0, plan.recommended_battery_dc_kw):
        variant = _CurrentAction(
            chosen.amps,
            chosen.next_energy_kwh,
            request,
            chosen.battery_average_kw,
            chosen.excess_dc_kw,
        )
        projection = _capture_projection(
            inputs,
            now,
            settings,
            variant,
            required_now,
            future.required_energy_by_boundary_kwh,
        )
        assert projection is not None
        print(
            f"first-interval request={request:.3f} kW DC:",
            f"captured={projection.captured_clipping_dc_kwh:.3f} kWh DC",
            f"remaining_clip={projection.predicted_clipped_dc_kwh:.3f} kWh DC",
            f"terminal={projection.terminal_energy_kwh:.3f} kWh",
            f"shortfall={projection.predicted_energy_shortfall_kwh}",
        )


if __name__ == "__main__":
    main()
