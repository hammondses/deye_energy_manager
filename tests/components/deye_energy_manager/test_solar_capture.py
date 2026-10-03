"""Tests for forward solar capture and remaining clipping projections."""

import pytest

from custom_components.deye_energy_manager.solar_capture import project_solar_capture
from custom_components.deye_energy_manager.solar_horizon import (
    SolarHorizonInterval,
    SolarHorizonSettings,
)


def settings(**updates: object) -> SolarHorizonSettings:
    values = dict(
        capacity_kwh=20.0,
        target_energy_kwh=10.0,
        reserve_energy_kwh=2.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        inverter_efficiency=1.0,
        inverter_ac_limit_kw=12.0,
        max_discharge_dc_power_kw=8.0,
        soc_charge_curve=((0.0, 12.0),),
    )
    values.update(updates)
    return SolarHorizonSettings(**values)  # type: ignore[arg-type]


def interval(
    pv: float,
    house: float,
    duration: float = 0.25,
    bms: float = 12.0,
) -> SolarHorizonInterval:
    return SolarHorizonInterval(duration, pv, house, bms)


def test_battery_headroom_captures_dc_above_export_and_ac_path() -> None:
    result = project_solar_capture(
        [interval(18.0, 2.0)],
        settings(),
        initial_energy_kwh=0.0,
        export_limit_kw=10.0,
        required_energy_by_boundary_kwh=(0.0, 0.0),
    )

    # AC serves 2 kW house + 10 kW export; 6 kW DC above that is captured.
    assert result.potential_clipping_dc_kwh == pytest.approx(1.5)
    assert result.captured_clipping_dc_kwh == pytest.approx(1.5)
    assert result.predicted_clipped_dc_kwh == pytest.approx(0.0)
    assert result.terminal_energy_kwh == pytest.approx(1.5)


def test_full_battery_leaves_potential_clipping_uncaptured() -> None:
    result = project_solar_capture(
        [interval(18.0, 2.0)],
        settings(capacity_kwh=10.0),
        initial_energy_kwh=10.0,
        export_limit_kw=10.0,
        required_energy_by_boundary_kwh=(10.0, 10.0),
    )

    assert result.potential_clipping_dc_kwh == pytest.approx(1.5)
    assert result.captured_clipping_dc_kwh == pytest.approx(0.0)
    assert result.predicted_clipped_dc_kwh == pytest.approx(1.5)
    assert result.terminal_energy_kwh == pytest.approx(10.0)


def test_soc_taper_integrates_clipped_capture_across_curve_breakpoint() -> None:
    result = project_solar_capture(
        [interval(20.0, 2.0, duration=5 / 60)],
        settings(
            capacity_kwh=10.0,
            charge_efficiency=0.94,
            inverter_efficiency=0.96,
            soc_charge_curve=((0.0, 12.0), (0.9, 4.0)),
        ),
        initial_energy_kwh=8.9,
        export_limit_kw=10.0,
        required_energy_by_boundary_kwh=(8.9, 8.9),
    )

    # DC excess is 7.5 kW for 5 minutes. Acceptance crosses 90% SOC then
    # tapers, so exact captured energy is below the 0.625 kWh opportunity.
    assert result.potential_clipping_dc_kwh == pytest.approx(0.625)
    assert 0 < result.captured_clipping_dc_kwh < 0.625
    assert result.predicted_clipped_dc_kwh == pytest.approx(
        result.potential_clipping_dc_kwh - result.captured_clipping_dc_kwh
    )
    assert result.terminal_energy_kwh > 8.9


def test_completion_floor_is_preserved_after_current_ev_load() -> None:
    # First-interval house includes the selected EV's AC draw. The planner
    # has chosen extra intentional charging above the completion floor.
    result = project_solar_capture(
        [interval(7.0, 5.0, duration=0.25)],
        settings(
            capacity_kwh=10.0,
            target_energy_kwh=6.0,
            reserve_energy_kwh=0.0,
            charge_efficiency=1.0,
        ),
        initial_energy_kwh=3.9,
        export_limit_kw=10.0,
        required_energy_by_boundary_kwh=(3.9, 4.0),
        first_charge_command_kw=2.0,
    )

    assert result.energy_by_boundary_kwh[-1] == pytest.approx(4.4)
    assert result.charge_command_kw == pytest.approx(2.0)
    assert result.predicted_energy_shortfall_kwh == pytest.approx(0.0, abs=1e-9)


def test_infeasible_completion_floor_charges_all_available_dc() -> None:
    result = project_solar_capture(
        [interval(8.0, 2.0)],
        settings(capacity_kwh=10.0),
        initial_energy_kwh=1.0,
        export_limit_kw=10.0,
        required_energy_by_boundary_kwh=(None, None),
    )

    assert result.charge_command_kw == pytest.approx(6.0)
    assert result.terminal_energy_kwh == pytest.approx(2.5)
    assert result.predicted_energy_shortfall_kwh is None


def test_partial_cloud_interval_discharges_house_only_to_reserve() -> None:
    result = project_solar_capture(
        [interval(0.0, 2.0), interval(0.0, 2.0)],
        settings(
            capacity_kwh=10.0,
            reserve_energy_kwh=3.0,
            target_energy_kwh=8.0,
        ),
        initial_energy_kwh=4.0,
        export_limit_kw=10.0,
        required_energy_by_boundary_kwh=(4.0, 3.5, 3.0),
    )

    assert result.energy_by_boundary_kwh == pytest.approx((4.0, 3.5, 3.0))
    assert result.terminal_energy_kwh == pytest.approx(3.0)
    assert result.captured_clipping_dc_kwh == pytest.approx(0.0)


def test_first_charge_command_is_honored_even_if_it_misses_floor() -> None:
    result = project_solar_capture(
        [interval(10.0, 0.0)],
        settings(
            capacity_kwh=10.0,
            charge_efficiency=1.0,
        ),
        initial_energy_kwh=1.0,
        export_limit_kw=10.0,
        required_energy_by_boundary_kwh=(1.0, 5.0),
        first_charge_command_kw=1.0,
    )

    assert result.charge_command_kw == pytest.approx(1.0)
    assert result.terminal_energy_kwh == pytest.approx(1.25)
    assert result.predicted_energy_shortfall_kwh == pytest.approx(3.75)


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        project_solar_capture(
            [interval(1.0, 0.0)],
            settings(),
            initial_energy_kwh=0.0,
            export_limit_kw=10.0,
            required_energy_by_boundary_kwh=(0.0,),
        )
    with pytest.raises(ValueError):
        project_solar_capture(
            [interval(-1.0, 0.0)],
            settings(),
            initial_energy_kwh=0.0,
            export_limit_kw=10.0,
            required_energy_by_boundary_kwh=(0.0, 0.0),
        )
