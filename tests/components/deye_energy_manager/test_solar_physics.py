"""Tests for the standalone solar interval physics model."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.deye_energy_manager.solar_physics import (
    SolarIntervalInput,
    simulate_solar_interval,
)


def interval(**overrides: float) -> SolarIntervalInput:
    values = {
        "duration_hours": 1.0,
        "pv_dc_kw": 18.0,
        "non_ev_house_ac_kw": 2.0,
        "ev_requested_ac_kw": 0.0,
        "battery_requested_dc_kw": 5.5,
        "battery_stored_kwh": 10.0,
        "battery_capacity_kwh": 30.0,
        "battery_bms_max_dc_kw": 8.0,
        "battery_acceptance_max_dc_kw": 8.0,
        "inverter_ac_limit_kw": 12.0,
        "export_limit_kw": 10.0,
        "inverter_efficiency": 0.96,
        "battery_efficiency": 0.94,
    }
    values.update(overrides)
    return SolarIntervalInput(**values)


def assert_pv_dc_energy_balances(result) -> None:
    accounted = (
        result.dc_to_inverter_energy_kwh
        + result.battery_dc_energy_kwh
        + result.clipped_pv_energy_kwh
    )
    assert result.pv_dc_energy_kwh == pytest.approx(accounted)


def test_dc_battery_captures_solar_above_ac_and_export_limits_with_losses() -> None:
    result = simulate_solar_interval(interval())

    assert result.house_pv_ac_kw == pytest.approx(2.0)
    assert result.export_ac_kw == pytest.approx(10.0)
    assert result.inverter_ac_output_kw == pytest.approx(12.0)
    assert result.battery_charge_dc_kw == pytest.approx(5.5)
    assert result.battery_stored_delta_kwh == pytest.approx(5.17)
    assert result.inverter_conversion_loss_kw == pytest.approx(0.5)
    assert result.battery_charge_loss_kw == pytest.approx(0.33)
    assert result.clipped_pv_dc_kw == pytest.approx(0.0)
    assert_pv_dc_energy_balances(result)


def test_full_battery_cannot_capture_dc_clipping_energy() -> None:
    result = simulate_solar_interval(
        interval(battery_stored_kwh=30.0, battery_requested_dc_kw=8.0)
    )

    assert result.battery_charge_dc_kw == pytest.approx(0.0)
    assert result.battery_stored_end_kwh == pytest.approx(30.0)
    assert result.ev_requested_ac_kw == pytest.approx(0.0)
    assert result.ev_served_ac_kw == pytest.approx(0.0)
    assert result.ev_unserved_ac_kw == pytest.approx(0.0)
    assert result.export_ac_kw == pytest.approx(10.0)
    assert result.clipped_pv_dc_kw == pytest.approx(5.5)
    assert_pv_dc_energy_balances(result)


def test_bms_acceptance_taper_bounds_charge_and_leaves_excess_pv_clipped() -> None:
    result = simulate_solar_interval(
        interval(battery_requested_dc_kw=8.0, battery_bms_max_dc_kw=1.5)
    )

    assert result.battery_charge_dc_kw == pytest.approx(1.5)
    assert result.battery_stored_delta_kwh == pytest.approx(1.41)
    assert result.inverter_ac_output_kw == pytest.approx(12.0)
    assert result.clipped_pv_dc_kw == pytest.approx(4.0)
    assert_pv_dc_energy_balances(result)


def test_modeled_soc_taper_is_separate_from_live_bms_charge_limit() -> None:
    result = simulate_solar_interval(
        interval(
            battery_requested_dc_kw=8.0,
            battery_bms_max_dc_kw=8.0,
            battery_acceptance_max_dc_kw=1.5,
        )
    )

    assert result.battery_charge_dc_kw == pytest.approx(1.5)
    assert result.battery_stored_delta_kwh == pytest.approx(1.41)
    assert result.inverter_ac_output_kw == pytest.approx(12.0)
    assert result.clipped_pv_dc_kw == pytest.approx(4.0)
    assert_pv_dc_energy_balances(result)


def test_ev_demand_displaces_export_at_ac_limit_without_changing_dc_clipping() -> None:
    baseline = simulate_solar_interval(
        interval(battery_requested_dc_kw=0.0, ev_requested_ac_kw=7.0)
    )
    more_ev = simulate_solar_interval(
        interval(battery_requested_dc_kw=0.0, ev_requested_ac_kw=8.0)
    )

    assert baseline.inverter_ac_output_kw == pytest.approx(12.0)
    assert more_ev.inverter_ac_output_kw == pytest.approx(12.0)
    assert (more_ev.ev_served_ac_kw - baseline.ev_served_ac_kw) == pytest.approx(1.0)
    assert (baseline.export_ac_kw - more_ev.export_ac_kw) == pytest.approx(1.0)
    assert more_ev.clipped_pv_dc_kw == pytest.approx(baseline.clipped_pv_dc_kw)
    assert more_ev.inverter_ac_output_kw <= 12.0
    assert_pv_dc_energy_balances(baseline)
    assert_pv_dc_energy_balances(more_ev)


def test_ev_uses_ac_headroom_that_export_limit_cannot_use() -> None:
    lower_ev = simulate_solar_interval(
        interval(
            battery_requested_dc_kw=0.0,
            export_limit_kw=2.0,
            ev_requested_ac_kw=6.0,
        )
    )
    higher_ev = simulate_solar_interval(
        interval(
            battery_requested_dc_kw=0.0,
            export_limit_kw=2.0,
            ev_requested_ac_kw=8.0,
        )
    )

    assert lower_ev.export_ac_kw == pytest.approx(2.0)
    assert higher_ev.export_ac_kw == pytest.approx(2.0)
    assert higher_ev.ev_served_ac_kw - lower_ev.ev_served_ac_kw == pytest.approx(2.0)
    assert higher_ev.inverter_ac_output_kw == pytest.approx(12.0)
    assert higher_ev.clipped_pv_dc_kw < lower_ev.clipped_pv_dc_kw
    assert_pv_dc_energy_balances(lower_ev)
    assert_pv_dc_energy_balances(higher_ev)


def test_low_pv_house_load_takes_priority_over_battery_and_ev() -> None:
    result = simulate_solar_interval(
        interval(
            pv_dc_kw=3.0,
            non_ev_house_ac_kw=4.0,
            ev_requested_ac_kw=3.0,
            battery_requested_dc_kw=2.0,
        )
    )

    assert result.house_pv_ac_kw == pytest.approx(2.88)
    assert result.house_grid_import_ac_kw == pytest.approx(1.12)
    assert result.battery_charge_dc_kw == pytest.approx(0.0)
    assert result.ev_requested_ac_kw == pytest.approx(3.0)
    assert result.ev_served_ac_kw == pytest.approx(0.0)
    assert result.ev_unserved_ac_kw == pytest.approx(3.0)
    assert result.export_ac_kw == pytest.approx(0.0)
    assert result.clipped_pv_dc_kw == pytest.approx(0.0)
    assert_pv_dc_energy_balances(result)


def test_battery_headroom_and_all_physical_caps_are_respected() -> None:
    result = simulate_solar_interval(
        interval(
            duration_hours=0.5,
            battery_stored_kwh=29.5,
            battery_requested_dc_kw=8.0,
            battery_bms_max_dc_kw=7.0,
            inverter_ac_limit_kw=5.0,
            export_limit_kw=3.0,
            ev_requested_ac_kw=4.0,
        )
    )

    assert result.battery_charge_dc_kw == pytest.approx(1.0638297872)
    assert result.battery_stored_end_kwh == pytest.approx(30.0)
    assert result.inverter_ac_output_kw <= 5.0
    assert result.export_ac_kw <= 3.0
    assert result.battery_charge_dc_kw <= 7.0
    assert_pv_dc_energy_balances(result)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pv_dc_kw", -0.1),
        ("non_ev_house_ac_kw", float("nan")),
        ("ev_requested_ac_kw", float("inf")),
        ("battery_bms_max_dc_kw", -1.0),
        ("duration_hours", 0.0),
        ("inverter_efficiency", 0.0),
        ("battery_efficiency", 1.01),
        ("battery_stored_kwh", 31.0),
    ],
)
def test_invalid_physical_inputs_raise_value_error(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        simulate_solar_interval(replace(interval(), **{field: value}))
