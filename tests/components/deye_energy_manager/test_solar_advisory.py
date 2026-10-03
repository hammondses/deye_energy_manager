"""Tests for the current-action solar and EV advisory."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.deye_energy_manager.solar_advisory import (
    SolarAdvisoryInput,
    recommend_solar_action,
)
from custom_components.deye_energy_manager.solar_forecast import parse_detailed_forecast
from custom_components.deye_energy_manager.battery_dynamics import integrate_battery_charge


def make_forecast(
    now: datetime,
    p10_values: list[float],
    p50_values: list[float] | None = None,
):
    p50_values = p50_values or [value + 2.0 for value in p10_values]
    rows = []
    for index, (p10, p50) in enumerate(zip(p10_values, p50_values, strict=True)):
        rows.append(
            {
                "period_start": (now + timedelta(minutes=30 * index)).isoformat(),
                "pv_estimate10": p10,
                "pv_estimate": p50,
                "pv_estimate90": p50 + 2.0,
            }
        )
    deadline = now + timedelta(minutes=30 * len(rows))
    return parse_detailed_forecast(
        rows,
        now=now,
        deadline=deadline,
        source_updated_at=now,
        max_age=timedelta(minutes=60),
    )


def make_input(now: datetime, **updates: object) -> SolarAdvisoryInput:
    values = dict(
        forecast=make_forecast(now, [12.0, 12.0, 12.0, 12.0]),
        now=now,
        current_soc_pct=50.0,
        capacity_kwh=10.0,
        target_soc_pct=60.0,
        reserve_energy_kwh=1.0,
        non_ev_base_house_kw=2.0,
        current_non_ev_house_kw=2.0,
        live_pv_dc_kw=10.0,
        voltage_v=230.0,
        live_bms_max_dc_kw=12.0,
        max_battery_dc_kw=12.0,
        max_discharge_dc_kw=8.0,
        soc_charge_curve=((0.0, 12.0), (0.9, 4.0)),
        site_ac_limit_kw=13.5,
        inverter_ac_limit_kw=12.0,
        export_limit_kw=10.0,
        battery_charge_efficiency=0.94,
        battery_discharge_efficiency=0.94,
        inverter_efficiency=0.96,
        safety_buffer_kwh=0.0,
        max_ev_amps=32,
        ev_allowed=True,
        forecast_p50_weight=0.0,
    )
    values.update(updates)
    return SolarAdvisoryInput(**values)  # type: ignore[arg-type]


def test_reconstructed_forecast_cannot_duplicate_or_extend_covered_intervals():
    now = datetime(2026, 3, 20, 12, tzinfo=timezone.utc)
    inputs = make_input(now)
    forecast = inputs.forecast
    duplicate = replace(forecast, intervals=(forecast.intervals[0], *forecast.intervals))
    plan = recommend_solar_action(replace(inputs, forecast=duplicate))
    assert not plan.valid and "overlap" in plan.reason
    shorter_deadline = replace(forecast, deadline=forecast.deadline - timedelta(minutes=5))
    plan = recommend_solar_action(replace(inputs, forecast=shorter_deadline))
    assert not plan.valid and "deadline" in plan.reason


def test_current_cloud_deficit_is_included_in_required_energy_floor():
    now = datetime(2026, 3, 20, 12, tzinfo=timezone.utc)
    # Only this five-minute interval remains. Even a full battery cannot
    # serve a house deficit and still end the interval at 100%.
    inputs = make_input(now, live_pv_dc_kw=0, target_soc_pct=100,
                        current_soc_pct=100)
    forecast = replace(inputs.forecast, intervals=inputs.forecast.intervals[:1],
                       deadline=now + timedelta(minutes=5))
    plan = recommend_solar_action(replace(inputs, forecast=forecast))
    assert plan.valid
    assert not plan.target_reachable
    assert plan.required_energy_now_kwh is None
    assert plan.completion_margin_kwh is None
    assert plan.recommended_ev_amps == 0


def test_physical_capture_projection_reports_loss_when_battery_is_full():
    now = datetime(2026, 3, 20, 12, tzinfo=timezone.utc)
    inputs = make_input(now, current_soc_pct=100, target_soc_pct=100, live_pv_dc_kw=18)
    inputs = replace(inputs, physical_dc_upper_kw=(18.0,) * len(inputs.forecast.intervals))
    plan = recommend_solar_action(inputs)
    assert plan.valid and plan.target_reachable
    assert plan.clipping_plan_available
    assert plan.clipping_estimate_kwh > 0
    assert plan.clipping_captured_kwh == pytest.approx(0)
    assert plan.clipping_potential_kwh == pytest.approx(plan.clipping_estimate_kwh)
    assert plan.physical_scenario_soc_trajectory[0] == 100


def test_after_clipping_window_charge_all_remaining_pv_and_preserve_ev_priority():
    now = datetime(2026, 3, 20, 12, tzinfo=timezone.utc)
    inputs = make_input(now, live_pv_dc_kw=10, current_soc_pct=50)
    count = len(inputs.forecast.intervals)
    plan = recommend_solar_action(replace(inputs,
        physical_dc_upper_kw=(10.0,) * count,
        clipping_envelope_dc_kw=(10.0,) * count))
    assert plan.valid and plan.target_reachable
    assert plan.charge_all_surplus
    assert plan.physical_clipping_remaining is False
    assert plan.recommended_ev_amps == 32
    remaining = 10 - (2 + 32 * .230) / .96
    assert plan.recommended_battery_dc_kw == pytest.approx(remaining)
    assert plan.physical_scenario_soc_trajectory[1] == pytest.approx(
        50 + remaining * (5 / 60) * .94 / 10 * 100)


def test_cloudy_projection_does_not_release_headroom_before_clear_sky_peak():
    now = datetime(2026, 3, 20, 12, tzinfo=timezone.utc)
    inputs = make_input(now, ev_allowed=False)
    count = len(inputs.forecast.intervals)
    plan = recommend_solar_action(replace(inputs,
        physical_dc_upper_kw=(3.0,) * count,
        clipping_envelope_dc_kw=(18.0,) * count))
    assert plan.valid and plan.physical_clipping_remaining
    assert not plan.charge_all_surplus
    assert plan.physical_clipping_window_end == inputs.forecast.deadline
    assert plan.recommended_battery_dc_kw == pytest.approx(0)


def test_missing_clipping_envelope_does_not_assert_window_has_ended():
    now = datetime(2026, 3, 20, 12, tzinfo=timezone.utc)
    plan = recommend_solar_action(make_input(now))
    assert plan.valid
    assert plan.physical_clipping_remaining is None
    assert not plan.charge_all_surplus


def test_site_ac_ceiling_limits_current_ev_candidate() -> None:
    now = datetime(2026, 1, 15, 1, 0, tzinfo=timezone.utc)
    result = recommend_solar_action(
        make_input(
            now,
            current_soc_pct=80.0,
            target_soc_pct=80.0,
            current_non_ev_house_kw=8.0,
            non_ev_base_house_kw=2.0,
            live_pv_dc_kw=18.0,
            inverter_ac_limit_kw=20.0,
        )
    )

    assert result.valid
    assert result.recommended_ev_amps == 23
    assert 8.0 + result.recommended_ev_amps * 230 / 1000 <= 13.5
    assert result.clipping_plan_available is False
    assert result.clipping_headroom_kwh is None


def test_current_battery_action_captures_dc_beyond_ac_and_export_path() -> None:
    now = datetime(2026, 1, 15, 1, 0, tzinfo=timezone.utc)
    result = recommend_solar_action(
        make_input(
            now,
            live_pv_dc_kw=20.0,
            current_soc_pct=50.0,
            target_soc_pct=60.0,
        )
    )

    assert result.valid
    assert result.recommended_ev_amps == 32
    assert result.instantaneous_dc_excess_after_ac_export_kw == pytest.approx(7.5)
    assert result.recommended_battery_dc_kw == pytest.approx(7.5)
    assert result.clipping_headroom_kwh is None
    assert result.clipping_estimate_kwh is None
    assert not result.clipping_plan_available


def test_recommended_battery_limit_crosses_taper_within_interval() -> None:
    now = datetime(2026, 1, 15, 1, 0, tzinfo=timezone.utc)
    values = make_input(
        now,
        current_soc_pct=89.0,
        target_soc_pct=90.0,
        live_pv_dc_kw=20.0,
        current_non_ev_house_kw=2.0,
        non_ev_base_house_kw=2.0,
        ev_allowed=False,
    )
    result = recommend_solar_action(values)

    assert result.valid
    assert result.recommended_battery_dc_kw == pytest.approx(7.5)
    # The actuator limit must remain the requested ceiling across the taper;
    # the accepted average is lower and is diagnostic only.
    expected = integrate_battery_charge(
        stored_energy_kwh=8.9,
        capacity_kwh=10.0,
        duration_hours=5 / 60,
        available_dc_power_kw=result.recommended_battery_dc_kw,
        bms_max_dc_power_kw=12.0,
        charge_efficiency=0.94,
        soc_charge_curve=((0.0, 12.0), (0.9, 4.0)),
    )
    assert result.recommended_battery_expected_average_dc_kw == pytest.approx(
        expected.average_dc_charge_power_kw
    )
    assert result.recommended_battery_expected_average_dc_kw < result.recommended_battery_dc_kw
    assert result.generated_at == now


def test_infeasible_forecast_blocks_ev_and_preserves_maximum_solar_charge() -> None:
    now = datetime(2026, 1, 15, 1, 0, tzinfo=timezone.utc)
    forecast = make_forecast(now, [0.5, 0.5])
    result = recommend_solar_action(
        make_input(
            now,
            forecast=forecast,
            current_soc_pct=50.0,
            target_soc_pct=100.0,
            current_non_ev_house_kw=3.0,
            non_ev_base_house_kw=3.0,
            live_pv_dc_kw=10.0,
        )
    )

    assert result.valid
    assert not result.target_reachable
    assert result.recommended_ev_amps == 0
    assert result.recommended_battery_dc_kw > 0
    assert result.reason == "target_unreachable_from_forecast"


def test_future_forecast_assumes_no_future_ev_and_returns_current_only_action() -> None:
    now = datetime(2026, 1, 15, 1, 0, tzinfo=timezone.utc)
    forecast = make_forecast(now, [12.0] * 8)
    result = recommend_solar_action(
        make_input(
            now,
            forecast=forecast,
            current_soc_pct=70.0,
            target_soc_pct=80.0,
            live_pv_dc_kw=12.0,
        )
    )

    assert result.valid
    assert result.recommended_ev_amps > 0
    assert result.recommended_battery_dc_kw >= 0
    assert result.deadline == forecast.intervals[-1].end
    assert result.forecast_ac_proxy_used


def test_quantile_weight_and_buffer_use_actual_interval_durations() -> None:
    now = datetime(2026, 1, 15, 1, 0, tzinfo=timezone.utc)
    forecast = make_forecast(now, [4.0, 8.0], [8.0, 12.0])
    result = recommend_solar_action(
        make_input(
            now,
            forecast=forecast,
            forecast_p50_weight=0.5,
            safety_buffer_kwh=1.5,
            ev_allowed=False,
            current_soc_pct=50.0,
            target_soc_pct=60.0,
        )
    )

    # Blended energy is 6*0.5 + 10*0.5 = 8 kWh; the explicit buffer leaves
    # 6.5 kWh available across the actual two-hour forecast horizon.
    assert result.valid
    assert result.forecast_energy_available_kwh == pytest.approx(6.5)


def test_safety_buffer_is_applied_before_trimming_nonpositive_forecast_tail() -> None:
    now = datetime(2026, 1, 15, 1, 0, tzinfo=timezone.utc)
    forecast = make_forecast(now, [8.0, 2.2, 2.0])
    result = recommend_solar_action(
        make_input(
            now,
            forecast=forecast,
            safety_buffer_kwh=1.0,
            ev_allowed=False,
            current_soc_pct=20.0,
            target_soc_pct=30.0,
        )
    )

    # The raw useful horizon contains 5.1 kWh; retain 4.1 kWh after the full
    # buffer, then trim the second bin once it falls below the base-load floor.
    expected_scale = 4.1 / 5.1
    assert result.valid
    assert result.deadline == forecast.intervals[5].end
    assert result.forecast_energy_available_kwh == pytest.approx(
        8.0 * expected_scale * 0.5
    )


def test_no_net_positive_forecast_uses_current_interval_end_as_action_deadline() -> None:
    now = datetime(2026, 1, 15, 1, 0, tzinfo=timezone.utc)
    forecast = make_forecast(now, [0.5, 0.5])
    result = recommend_solar_action(
        make_input(
            now,
            forecast=forecast,
            current_soc_pct=90.0,
            target_soc_pct=90.0,
            live_pv_dc_kw=10.0,
            ev_allowed=False,
        )
    )

    assert result.valid
    assert result.deadline == forecast.intervals[0].end
    assert result.generated_at == now


def test_stale_or_naive_forecast_returns_invalid_advisory_defaults() -> None:
    now = datetime(2026, 1, 15, 1, 0, tzinfo=timezone.utc)
    fresh = make_input(now)
    stale_forecast = replace(
        fresh.forecast,
        source_updated_at=now - timedelta(hours=2),
    )
    stale = recommend_solar_action(
        replace(fresh, forecast=stale_forecast, forecast_max_age=timedelta(minutes=30))
    )
    assert not stale.valid
    assert stale.reason == "forecast source timestamp is stale"
    assert stale.recommended_ev_amps == 0
    assert stale.recommended_battery_dc_kw == 0
    assert not stale.clipping_plan_available

    invalid = recommend_solar_action(replace(fresh, now=datetime(2026, 1, 15, 1, 0)))
    assert not invalid.valid
    assert "timezone-aware" in invalid.reason


def test_invalid_live_values_block_advisory() -> None:
    now = datetime(2026, 1, 15, 1, 0, tzinfo=timezone.utc)
    result = recommend_solar_action(make_input(now, live_pv_dc_kw=float("nan")))
    assert not result.valid
    assert result.recommended_ev_amps == 0
    assert result.reason == "live_pv_dc_kw must be a finite non-negative number"
