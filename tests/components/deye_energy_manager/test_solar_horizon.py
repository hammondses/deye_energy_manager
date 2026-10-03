"""Tests for the continuous battery-completion horizon envelope."""

import math
import time

import pytest

from custom_components.deye_energy_manager.solar_horizon import (
    SolarHorizonInterval,
    SolarHorizonSettings,
    plan_battery_completion,
)


def settings(**updates: object) -> SolarHorizonSettings:
    values = dict(
        capacity_kwh=10.0,
        target_energy_kwh=10.0,
        reserve_energy_kwh=2.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        inverter_efficiency=1.0,
        inverter_ac_limit_kw=12.0,
        max_discharge_dc_power_kw=8.0,
        soc_charge_curve=((0.0, 8.0),),
    )
    values.update(updates)
    return SolarHorizonSettings(**values)  # type: ignore[arg-type]


def interval(
    pv: float,
    house: float,
    duration: float = 0.25,
    bms: float = 8.0,
) -> SolarHorizonInterval:
    return SolarHorizonInterval(duration, pv, house, bms)


def test_multiple_cloud_intervals_include_house_battery_discharge() -> None:
    intervals = [
        interval(0.0, 4.0),
        interval(0.0, 4.0),
        interval(8.0, 2.0),
        interval(8.0, 2.0),
    ]
    result = plan_battery_completion(
        intervals,
        settings(target_energy_kwh=8.0),
        initial_energy_kwh=6.0,
    )

    # Two cloudy intervals consume 2 kWh of stored energy before solar returns.
    assert result.forward_energy_by_boundary_kwh[0] == pytest.approx(6.0)
    assert result.forward_energy_by_boundary_kwh[1] == pytest.approx(5.0)
    assert result.forward_energy_by_boundary_kwh[2] == pytest.approx(4.0)
    assert result.forward_energy_by_boundary_kwh[-1] == pytest.approx(7.0)
    assert result.terminal_shortfall_kwh == pytest.approx(1.0)
    assert not result.target_reachable_from_initial


def test_late_pv_with_low_acceptance_cannot_repair_completion_shortfall() -> None:
    intervals = [interval(0.0, 2.0), interval(10.0, 0.0, bms=0.5)]
    result = plan_battery_completion(
        intervals,
        settings(
            capacity_kwh=10.0,
            target_energy_kwh=9.0,
            reserve_energy_kwh=0.0,
            soc_charge_curve=((0.0, 8.0), (0.8, 1.0)),
        ),
        initial_energy_kwh=8.0,
    )

    assert result.forward_energy_by_boundary_kwh == pytest.approx((8.0, 7.5, 7.625))
    assert result.terminal_shortfall_kwh == pytest.approx(1.375)
    assert result.required_energy_by_boundary_kwh[0] == pytest.approx(9.375)
    assert not result.target_reachable_from_initial


def test_small_charge_gains_accumulate_without_per_interval_rounding() -> None:
    intervals = [interval(0.5, 0.0, duration=0.2) for _ in range(4)]
    result = plan_battery_completion(
        intervals,
        settings(
            capacity_kwh=5.0,
            target_energy_kwh=1.0,
            reserve_energy_kwh=0.0,
            charge_efficiency=0.9,
            soc_charge_curve=((0.0, 8.0),),
        ),
        initial_energy_kwh=0.0,
    )

    assert result.forward_energy_by_boundary_kwh[-1] == pytest.approx(0.36)
    assert result.terminal_shortfall_kwh == pytest.approx(0.64)
    assert all(
        later >= earlier
        for earlier, later in zip(
            result.forward_energy_by_boundary_kwh,
            result.forward_energy_by_boundary_kwh[1:],
        )
    )


def test_full_target_is_reachable_exactly_and_empty_horizon_is_reported() -> None:
    enough_solar = plan_battery_completion(
        [interval(2.0, 0.0, duration=0.5)],
        settings(
            capacity_kwh=5.0,
            target_energy_kwh=1.0,
            reserve_energy_kwh=0.0,
            charge_efficiency=1.0,
            soc_charge_curve=((0.0, 2.0),),
        ),
        initial_energy_kwh=0.0,
    )
    assert enough_solar.terminal_energy_kwh == pytest.approx(1.0)
    assert enough_solar.terminal_shortfall_kwh == pytest.approx(0.0)
    assert enough_solar.required_energy_by_boundary_kwh[0] == pytest.approx(0.0)
    assert enough_solar.target_reachable_from_initial

    empty = plan_battery_completion([], settings(), initial_energy_kwh=9.0)
    assert empty.required_energy_by_boundary_kwh == (10.0,)
    assert empty.terminal_energy_kwh == pytest.approx(9.0)
    assert empty.terminal_shortfall_kwh == pytest.approx(1.0)
    assert not empty.target_reachable_from_initial


def test_house_discharge_respects_reserve_and_ac_limits() -> None:
    result = plan_battery_completion(
        [interval(0.0, 12.0)],
        settings(
            capacity_kwh=10.0,
            target_energy_kwh=2.0,
            reserve_energy_kwh=2.0,
            inverter_ac_limit_kw=4.0,
            max_discharge_dc_power_kw=2.0,
        ),
        initial_energy_kwh=4.0,
    )

    # AC output headroom serves only 4 kW * 0.25 h, bounded further by a 2 kW
    # battery-side DC limit (2 kWh * 0.25 h at unit efficiencies).
    assert result.forward_energy_by_boundary_kwh[-1] == pytest.approx(3.5)


def test_dc_surplus_charges_even_when_ac_house_demand_exceeds_inverter_limit() -> None:
    result = plan_battery_completion(
        [interval(18.0, 13.0)],
        settings(
            capacity_kwh=10.0,
            target_energy_kwh=10.0,
            reserve_energy_kwh=0.0,
            inverter_ac_limit_kw=12.0,
            charge_efficiency=1.0,
        ),
        initial_energy_kwh=5.0,
    )

    # 12 kW AC serves house load; 6 kW DC remains for the battery while the
    # remaining 1 kW house demand is grid supplied. No simultaneous discharge.
    assert result.forward_energy_by_boundary_kwh[-1] == pytest.approx(6.5)


def test_near_zero_dc_remainder_does_not_suppress_house_battery_discharge() -> None:
    inverter_efficiency = 0.96
    discharge_efficiency = 0.9
    result = plan_battery_completion(
        [interval(1.136, 3.0, duration=1.0)],
        settings(
            capacity_kwh=10.0,
            target_energy_kwh=0.0,
            reserve_energy_kwh=0.0,
            charge_efficiency=1.0,
            discharge_efficiency=discharge_efficiency,
            inverter_efficiency=inverter_efficiency,
            max_discharge_dc_power_kw=10.0,
        ),
        initial_energy_kwh=4.0,
    )

    expected_withdrawal = (
        3.0 - 1.136 * inverter_efficiency
    ) / (inverter_efficiency * discharge_efficiency)
    assert result.forward_energy_by_boundary_kwh[-1] == pytest.approx(
        4.0 - expected_withdrawal
    )


def test_unreachable_from_full_capacity_propagates_none_backwards() -> None:
    result = plan_battery_completion(
        [interval(0.0, 8.0), interval(0.0, 8.0)],
        settings(
            capacity_kwh=10.0,
            target_energy_kwh=10.0,
            reserve_energy_kwh=0.0,
        ),
        initial_energy_kwh=10.0,
    )

    assert result.required_energy_by_boundary_kwh == (None, None, 10.0)
    assert result.terminal_shortfall_kwh == pytest.approx(4.0)


def test_invalid_physical_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        plan_battery_completion(
            [interval(-1.0, 0.0)], settings(), initial_energy_kwh=5.0
        )
    with pytest.raises(ValueError):
        plan_battery_completion(
            [interval(0.0, 1.0, duration=0.0)], settings(), initial_energy_kwh=5.0
        )
    with pytest.raises(ValueError):
        plan_battery_completion(
            [], settings(soc_charge_curve=((0.2, 3.0),)), initial_energy_kwh=5.0
        )
    with pytest.raises(ValueError):
        plan_battery_completion([], settings(), initial_energy_kwh=11.0)


def test_150_interval_horizon_is_bounded_and_finite() -> None:
    intervals = [
        interval(12.0 if i % 3 else 0.0, 2.0 + (i % 4) * 0.25, duration=5 / 60)
        for i in range(150)
    ]
    started = time.perf_counter()
    result = plan_battery_completion(
        intervals,
        settings(
            capacity_kwh=32.0,
            target_energy_kwh=30.0,
            reserve_energy_kwh=5.0,
            soc_charge_curve=((0.0, 12.0), (0.8, 7.0), (0.95, 2.0)),
        ),
        initial_energy_kwh=14.0,
    )
    elapsed = time.perf_counter() - started

    assert len(result.forward_energy_by_boundary_kwh) == 151
    assert len(result.required_energy_by_boundary_kwh) == 151
    assert all(math.isfinite(value) for value in result.forward_energy_by_boundary_kwh)
    assert elapsed < 2.0
