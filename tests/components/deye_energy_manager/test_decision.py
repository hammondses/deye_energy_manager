"""Tests for the Deye Energy Manager decision engine."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.deye_energy_manager.decision import active_slot, decide, tariff_window
from custom_components.deye_energy_manager.models import EnergyManagerInputs, EnergyManagerSettings

TZ = ZoneInfo("Pacific/Auckland")


def dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 1, hour, minute, tzinfo=TZ)


def base_inputs(**overrides: object) -> EnergyManagerInputs:
    values = {
        "now": dt(12),
        "battery_soc": 50.0,
        "battery_power_w": 0.0,
        "essential_power_w": 1000.0,
        "forecast_tomorrow_kwh": 20.0,
        "heat_available": True,
    }
    values.update(overrides)
    return EnergyManagerInputs(**values)


def test_forecast_tiers() -> None:
    cases = [
        (35, "excellent", 90, 0),
        (27, "good", 90, 0),
        (20, "medium", 85, 0),
        (12, "poor", 85, 65),
        (8, "dreadful", 85, 75),
        (4, "brutal", 85, 80),
    ]

    for forecast, mode, target_17, grid_target in cases:
        decision = decide(base_inputs(forecast_tomorrow_kwh=forecast))
        assert decision.forecast_mode == mode
        assert decision.target_17_soc == target_17
        assert decision.grid_charge_target_soc == grid_target


def test_time_slots_and_tariff_windows() -> None:
    cases = [
        (dt(22), "Prog6", "cheap_grid"),
        (dt(3), "Prog1", "cheap_grid"),
        (dt(5), "Prog2", "cheap_grid"),
        (dt(7, 30), "Prog3", "morning_solar_ramp"),
        (dt(14), "Prog4", "pre_peak_preserve"),
        (dt(18), "Prog5", "peak"),
    ]

    for now, slot, window in cases:
        assert active_slot(now) == slot
        assert tariff_window(now) == window


def test_heat_allowed_rules() -> None:
    assert not decide(base_inputs(now=dt(10), battery_soc=31, battery_power_w=-300)).heat_allowed
    assert decide(base_inputs(now=dt(10), battery_soc=31, battery_power_w=-6500)).heat_allowed
    assert decide(base_inputs(now=dt(10), battery_soc=91, battery_power_w=0)).heat_allowed
    assert not decide(base_inputs(now=dt(10), battery_soc=85, battery_power_w=-2000, forecast_tomorrow_kwh=35)).heat_allowed


def test_heat_shed_rules() -> None:
    assert decide(base_inputs(any_solar_owned_heat_load_on=True, battery_soc=91, battery_power_w=600)).heat_should_shed
    assert decide(base_inputs(any_solar_owned_heat_load_on=True, battery_soc=31, battery_power_w=-300)).heat_should_shed
    assert not decide(base_inputs(any_solar_owned_heat_load_on=True, battery_soc=91, battery_power_w=0)).heat_should_shed
    assert not decide(base_inputs(any_solar_owned_heat_load_on=False, battery_soc=31, battery_power_w=-300)).heat_should_shed


def test_grid_charge_rules() -> None:
    settings = EnergyManagerSettings(grid_charge_control_enabled=True)
    assert decide(
        base_inputs(now=dt(4), forecast_tomorrow_kwh=12, battery_soc=50, ev_latch_on=False),
        settings,
    ).grid_charge_required
    assert not decide(
        base_inputs(now=dt(4), forecast_tomorrow_kwh=12, battery_soc=50, ev_latch_on=True),
        settings,
    ).grid_charge_required
    assert not decide(base_inputs(now=dt(8), forecast_tomorrow_kwh=12, battery_soc=50), settings).grid_charge_required
    assert not decide(base_inputs(now=dt(4), forecast_tomorrow_kwh=35, battery_soc=50), settings).grid_charge_required


def test_ev_start_and_stop_rules() -> None:
    assert decide(
        base_inputs(now=dt(22), essential_power_w=6200, previous_essential_power_w=1000),
    ).ev_grid_mode_required
    assert decide(
        base_inputs(now=dt(22), ev_latch_on=True, essential_power_w=3200, previous_essential_power_w=3300),
    ).ev_grid_mode_required
    assert not decide(
        base_inputs(now=dt(22), ev_latch_on=True, essential_power_w=2000, previous_essential_power_w=8600),
    ).ev_grid_mode_required
    assert not decide(base_inputs(now=dt(22), ev_latch_on=True, porsche_soc=99)).ev_grid_mode_required
    assert not decide(base_inputs(now=dt(7), ev_latch_on=True)).ev_grid_mode_required
    assert not decide(
        base_inputs(now=dt(3), ev_latch_on=True, ev_hold_until=dt(3) - timedelta(minutes=1), essential_power_w=2400),
    ).ev_grid_mode_required


def test_controls_block_when_manager_disabled() -> None:
    decision = decide(base_inputs(), EnergyManagerSettings(enabled=False))
    assert decision.control_blocked
    assert not decision.heat_allowed

