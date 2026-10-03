"""Tests for continuous battery energy transitions."""

import pytest

from custom_components.deye_energy_manager.battery_dynamics import (
    discharge_to_house,
    integrate_battery_charge,
)


def test_charge_crosses_soc_taper_band_mid_interval() -> None:
    result = integrate_battery_charge(
        stored_energy_kwh=8.0,
        capacity_kwh=10.0,
        duration_hours=0.25,
        available_dc_power_kw=8.0,
        bms_max_dc_power_kw=8.0,
        charge_efficiency=1.0,
        soc_charge_curve=((0.0, 8.0), (0.9, 2.0)),
    )

    # First 1 kWh at 8 kW reaches 90% in 7.5 minutes, then 30 minutes
    # would allow 1 kWh at 2 kW; this interval has only 15 minutes total.
    assert result.stored_energy_end_kwh == pytest.approx(9.25)
    assert result.dc_charge_energy_kwh == pytest.approx(1.25)
    assert result.average_dc_charge_power_kw == pytest.approx(5.0)
    assert result.unused_available_dc_energy_kwh == pytest.approx(0.75)
    assert result.captured_clipping_dc_energy_kwh == 0.0


def test_clipping_capture_tracks_each_actual_soc_taper_band() -> None:
    result = integrate_battery_charge(
        stored_energy_kwh=7.5,
        capacity_kwh=10.0,
        duration_hours=0.5,
        available_dc_power_kw=5.0,
        bms_max_dc_power_kw=5.0,
        charge_efficiency=1.0,
        soc_charge_curve=((0.0, 5.0), (0.8, 4.0), (0.9, 1.5)),
        otherwise_clipped_dc_power_kw=3.0,
    )

    # Spend 0.1 h at 5 kW, 0.25 h at 4 kW, then 0.15 h at 1.5 kW.
    # Attribute only the min(actual accepted power, 3 kW spill) per band.
    assert result.dc_charge_energy_kwh == pytest.approx(1.725)
    assert result.captured_clipping_dc_energy_kwh == pytest.approx(1.275)


def test_full_battery_captures_no_clipping_energy() -> None:
    result = integrate_battery_charge(
        stored_energy_kwh=10.0,
        capacity_kwh=10.0,
        duration_hours=0.5,
        available_dc_power_kw=5.0,
        bms_max_dc_power_kw=5.0,
        charge_efficiency=0.95,
        soc_charge_curve=((0.0, 5.0),),
        otherwise_clipped_dc_power_kw=4.0,
    )

    assert result.dc_charge_energy_kwh == 0.0
    assert result.captured_clipping_dc_energy_kwh == 0.0


def test_clipping_power_validation_rejects_nonfinite_and_negative_values() -> None:
    base = dict(
        stored_energy_kwh=0.0,
        capacity_kwh=10.0,
        duration_hours=0.25,
        available_dc_power_kw=2.0,
        bms_max_dc_power_kw=2.0,
        charge_efficiency=1.0,
        soc_charge_curve=((0.0, 2.0),),
    )
    for value in (-0.1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            integrate_battery_charge(
                **base, otherwise_clipped_dc_power_kw=value
            )


@pytest.mark.parametrize("capacity_kwh, breakpoint", [(32.0, 0.91), (27.3, 0.87)])
def test_charge_crosses_nonbinary_soc_threshold_without_stalling(
    capacity_kwh: float, breakpoint: float
) -> None:
    efficiency = 0.94
    duration = 0.1
    start = breakpoint - 0.0001
    stored = start * capacity_kwh
    energy_to_breakpoint = (breakpoint * capacity_kwh - stored) / efficiency
    time_to_breakpoint = energy_to_breakpoint / 8.0

    result = integrate_battery_charge(
        stored_energy_kwh=stored,
        capacity_kwh=capacity_kwh,
        duration_hours=duration,
        available_dc_power_kw=8.0,
        bms_max_dc_power_kw=8.0,
        charge_efficiency=efficiency,
        soc_charge_curve=((0.0, 8.0), (breakpoint, 2.0), (1.0, 0.0)),
    )

    expected_dc = 8.0 * time_to_breakpoint + 2.0 * (duration - time_to_breakpoint)
    assert result.dc_charge_energy_kwh == pytest.approx(expected_dc)
    assert result.stored_energy_end_kwh == pytest.approx(
        stored + expected_dc * efficiency
    )
    assert result.stored_energy_end_kwh > stored
    assert result.stored_energy_end_kwh < capacity_kwh
    assert all(
        value >= 0 and value < float("inf")
        for value in (
            result.stored_energy_end_kwh,
            result.dc_charge_energy_kwh,
            result.average_dc_charge_power_kw,
            result.unused_available_dc_energy_kwh,
        )
    )


def test_charge_accounts_for_efficiency_and_partial_available_power() -> None:
    result = integrate_battery_charge(
        stored_energy_kwh=2.0,
        capacity_kwh=8.0,
        duration_hours=0.5,
        available_dc_power_kw=3.0,
        bms_max_dc_power_kw=4.0,
        charge_efficiency=0.8,
        soc_charge_curve=((0.0, 10.0),),
    )

    assert result.dc_charge_energy_kwh == pytest.approx(1.5)
    assert result.stored_energy_end_kwh == pytest.approx(3.2)
    assert result.unused_available_dc_energy_kwh == pytest.approx(0.0)


def test_charge_stops_at_exact_capacity_and_reports_unused_energy() -> None:
    result = integrate_battery_charge(
        stored_energy_kwh=9.0,
        capacity_kwh=10.0,
        duration_hours=1.0,
        available_dc_power_kw=4.0,
        bms_max_dc_power_kw=4.0,
        charge_efficiency=0.8,
        soc_charge_curve=((0.0, 10.0),),
    )

    assert result.stored_energy_end_kwh == pytest.approx(10.0)
    assert result.dc_charge_energy_kwh == pytest.approx(1.25)
    assert result.unused_available_dc_energy_kwh == pytest.approx(2.75)


def test_curve_may_use_100_percent_as_terminal_capacity_marker() -> None:
    result = integrate_battery_charge(
        stored_energy_kwh=9.0,
        capacity_kwh=10.0,
        duration_hours=0.25,
        available_dc_power_kw=4.0,
        bms_max_dc_power_kw=4.0,
        charge_efficiency=1.0,
        soc_charge_curve=((0.0, 4.0), (1.0, 0.0)),
    )

    assert result.stored_energy_end_kwh == pytest.approx(10.0)
    assert result.dc_charge_energy_kwh == pytest.approx(1.0)


def test_zero_acceptance_band_stops_without_losing_energy_precision() -> None:
    result = integrate_battery_charge(
        stored_energy_kwh=8.9,
        capacity_kwh=10.0,
        duration_hours=0.25,
        available_dc_power_kw=6.0,
        bms_max_dc_power_kw=6.0,
        charge_efficiency=0.95,
        soc_charge_curve=((0.0, 6.0), (0.9, 0.0)),
    )

    assert result.stored_energy_end_kwh == pytest.approx(9.0)
    assert result.dc_charge_energy_kwh == pytest.approx(0.1 / 0.95)
    assert result.unused_available_dc_energy_kwh == pytest.approx(
        1.5 - 0.1 / 0.95
    )


def test_charge_is_limited_by_bms_and_keeps_unaccepted_energy() -> None:
    result = integrate_battery_charge(
        stored_energy_kwh=0.0,
        capacity_kwh=5.0,
        duration_hours=0.5,
        available_dc_power_kw=8.0,
        bms_max_dc_power_kw=2.0,
        charge_efficiency=1.0,
        soc_charge_curve=((0.0, 10.0),),
    )

    assert result.dc_charge_energy_kwh == pytest.approx(1.0)
    assert result.unused_available_dc_energy_kwh == pytest.approx(3.0)


def test_charge_validation_rejects_invalid_curve_and_values() -> None:
    base = dict(
        stored_energy_kwh=1.0,
        capacity_kwh=10.0,
        duration_hours=0.25,
        available_dc_power_kw=2.0,
        bms_max_dc_power_kw=2.0,
        charge_efficiency=0.95,
    )
    for curve in (
        (),
        ((0.1, 5.0),),
        ((0.0, 5.0), (0.0, 2.0)),
        ((0.0, 5.0), (0.9, 2.0), (0.8, 1.0)),
        ((0.0, 5.0), (1.0, 0.0), (1.1, 0.0)),
        ((0.0, -1.0),),
    ):
        with pytest.raises(ValueError):
            integrate_battery_charge(**base, soc_charge_curve=curve)

    for updates in (
        {"available_dc_power_kw": float("nan")},
        {"bms_max_dc_power_kw": float("inf")},
        {"stored_energy_kwh": -0.1},
        {"stored_energy_kwh": 10.1},
        {"charge_efficiency": 0.0},
        {"duration_hours": 0.0},
    ):
        with pytest.raises(ValueError):
            integrate_battery_charge(
                **(base | updates), soc_charge_curve=((0.0, 5.0),)
            )


def test_discharge_applies_battery_and_inverter_losses() -> None:
    result = discharge_to_house(
        stored_energy_kwh=10.0,
        required_house_ac_energy_kwh=2.0,
        duration_hours=1.0,
        max_discharge_dc_power_kw=10.0,
        reserve_energy_kwh=0.0,
        discharge_efficiency=0.9,
        inverter_efficiency=0.8,
    )

    assert result.stored_energy_withdrawn_kwh == pytest.approx(2 / 0.72)
    assert result.available_dc_energy_kwh == pytest.approx(2 / 0.8)
    assert result.house_ac_served_kwh == pytest.approx(2.0)
    assert result.house_ac_unserved_kwh == pytest.approx(0.0)
    assert result.stored_energy_end_kwh == pytest.approx(10 - 2 / 0.72)


def test_discharge_respects_reserve_and_reports_unserved_house_energy() -> None:
    result = discharge_to_house(
        stored_energy_kwh=5.0,
        required_house_ac_energy_kwh=10.0,
        duration_hours=1.0,
        max_discharge_dc_power_kw=20.0,
        reserve_energy_kwh=3.0,
        discharge_efficiency=0.8,
        inverter_efficiency=0.9,
    )

    assert result.stored_energy_end_kwh == pytest.approx(3.0)
    assert result.stored_energy_withdrawn_kwh == pytest.approx(2.0)
    assert result.available_dc_energy_kwh == pytest.approx(1.6)
    assert result.house_ac_served_kwh == pytest.approx(1.44)
    assert result.house_ac_unserved_kwh == pytest.approx(8.56)


def test_discharge_respects_power_limit_and_below_reserve_does_not_discharge() -> None:
    limited = discharge_to_house(
        stored_energy_kwh=5.0,
        required_house_ac_energy_kwh=5.0,
        duration_hours=0.5,
        max_discharge_dc_power_kw=1.0,
        reserve_energy_kwh=0.0,
        discharge_efficiency=0.8,
        inverter_efficiency=0.9,
    )
    assert limited.available_dc_energy_kwh == pytest.approx(0.5)
    assert limited.house_ac_served_kwh == pytest.approx(0.45)
    assert limited.house_ac_unserved_kwh == pytest.approx(4.55)

    below_reserve = discharge_to_house(
        stored_energy_kwh=2.0,
        required_house_ac_energy_kwh=1.0,
        duration_hours=1.0,
        max_discharge_dc_power_kw=5.0,
        reserve_energy_kwh=3.0,
        discharge_efficiency=0.9,
        inverter_efficiency=0.9,
    )
    assert below_reserve.stored_energy_end_kwh == pytest.approx(2.0)
    assert below_reserve.house_ac_served_kwh == pytest.approx(0.0)
    assert below_reserve.house_ac_unserved_kwh == pytest.approx(1.0)


def test_discharge_validation_rejects_invalid_values() -> None:
    base = dict(
        stored_energy_kwh=5.0,
        required_house_ac_energy_kwh=1.0,
        duration_hours=1.0,
        max_discharge_dc_power_kw=5.0,
        reserve_energy_kwh=1.0,
        discharge_efficiency=0.9,
        inverter_efficiency=0.9,
    )
    for updates in (
        {"stored_energy_kwh": float("nan")},
        {"required_house_ac_energy_kwh": -1.0},
        {"duration_hours": 0.0},
        {"max_discharge_dc_power_kw": float("inf")},
        {"reserve_energy_kwh": -1.0},
        {"discharge_efficiency": 1.1},
        {"inverter_efficiency": 0.0},
    ):
        with pytest.raises(ValueError):
            discharge_to_house(**(base | updates))
