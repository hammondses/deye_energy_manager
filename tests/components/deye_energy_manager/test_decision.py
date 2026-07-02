"""Tests for the Deye Energy Manager decision engine."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.deye_energy_manager.decision import active_slot, decide, tariff_window, thermal_shed_action, thermal_soak_action
from custom_components.deye_energy_manager.models import EnergyManagerInputs, EnergyManagerSettings, HeatLoadState

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
    settings = EnergyManagerSettings(thermal_control_enabled=True)
    assert not decide(base_inputs(now=dt(10), battery_soc=31, battery_power_w=-300), settings).heat_allowed
    assert decide(base_inputs(now=dt(10), battery_soc=31, battery_power_w=-6500), settings).heat_allowed
    assert decide(base_inputs(now=dt(10), battery_soc=91, battery_power_w=0), settings).heat_allowed
    assert decide(base_inputs(now=dt(10), battery_soc=85, battery_power_w=-2000, forecast_tomorrow_kwh=35), settings).heat_allowed


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


def test_pv_load_test_recommended_when_expected_pv_is_clipped() -> None:
    settings = EnergyManagerSettings(export_limited_mode_enabled=True)
    decision = decide(
        base_inputs(
            now=dt(11),
            battery_soc=78,
            battery_power_w=-1200,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=12,
            pv_power_now_w=1500,
            pv_power_in_30_minutes_w=5200,
            any_solar_owned_heat_load_on=False,
        ),
        settings,
    )

    assert decision.pv_load_test_recommended
    assert "test_one_pv_load" in decision.proposed_actions


def test_pv_load_test_requires_export_limited_mode_and_no_owned_load() -> None:
    clipped_inputs = base_inputs(
        now=dt(11),
        battery_soc=78,
        battery_power_w=-1200,
        forecast_tomorrow_kwh=35,
        forecast_remaining_today_kwh=12,
        pv_power_in_30_minutes_w=5200,
    )

    assert not decide(clipped_inputs).pv_load_test_recommended
    assert not decide(
        base_inputs(
            now=dt(11),
            battery_soc=78,
            battery_power_w=-1200,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=12,
            pv_power_in_30_minutes_w=5200,
            any_solar_owned_heat_load_on=True,
        ),
        EnergyManagerSettings(export_limited_mode_enabled=True),
    ).pv_load_test_recommended


def test_pv_load_test_waits_for_healthy_soc_and_expected_pv() -> None:
    settings = EnergyManagerSettings(export_limited_mode_enabled=True)
    assert not decide(
        base_inputs(
            now=dt(11),
            battery_soc=55,
            battery_power_w=-1200,
            forecast_remaining_today_kwh=12,
            forecast_tomorrow_kwh=35,
            pv_power_in_30_minutes_w=5200,
        ),
        settings,
    ).pv_load_test_recommended
    assert not decide(
        base_inputs(
            now=dt(11),
            battery_soc=78,
            battery_power_w=-1200,
            forecast_remaining_today_kwh=12,
            forecast_tomorrow_kwh=35,
            pv_power_in_30_minutes_w=2500,
        ),
        settings,
    ).pv_load_test_recommended


def test_heat_rotation_recommended_for_tapered_owned_load_and_colder_room() -> None:
    settings = EnergyManagerSettings(thermal_control_enabled=True, export_limited_mode_enabled=True)
    decision = decide(
        base_inputs(
            now=dt(11),
            battery_soc=82,
            battery_power_w=-1200,
            forecast_remaining_today_kwh=12,
            forecast_tomorrow_kwh=35,
            pv_power_in_30_minutes_w=5200,
            any_solar_owned_heat_load_on=True,
            heat_loads=[
                HeatLoadState(
                    name="Dining/living heat pump",
                    priority=1,
                    is_on=True,
                    solar_owned=True,
                    current_temp=26.4,
                    target_temp=27.0,
                    estimated_load_w=3000,
                ),
                HeatLoadState(
                    name="Office heat pump",
                    priority=3,
                    is_on=False,
                    solar_owned=False,
                    current_temp=23.0,
                    target_temp=27.0,
                    estimated_load_w=1800,
                ),
            ],
        ),
        settings,
    )

    assert decision.heat_rotation_recommended
    assert decision.heat_load_to_shed == "Dining/living heat pump"
    assert decision.heat_load_to_add == "Office heat pump"
    assert "rotate_heat_load" in decision.proposed_actions


def test_heat_rotation_requires_colder_add_candidate() -> None:
    settings = EnergyManagerSettings(thermal_control_enabled=True, export_limited_mode_enabled=True)
    decision = decide(
        base_inputs(
            now=dt(11),
            battery_soc=82,
            battery_power_w=-1200,
            forecast_remaining_today_kwh=12,
            forecast_tomorrow_kwh=35,
            pv_power_in_30_minutes_w=5200,
            any_solar_owned_heat_load_on=True,
            heat_loads=[
                HeatLoadState(
                    name="Dining/living heat pump",
                    priority=1,
                    is_on=True,
                    solar_owned=True,
                    current_temp=26.4,
                    target_temp=27.0,
                ),
                HeatLoadState(
                    name="Office heat pump",
                    priority=3,
                    is_on=False,
                    solar_owned=False,
                    current_temp=26.0,
                    target_temp=27.0,
                ),
            ],
        ),
        settings,
    )

    assert not decision.heat_rotation_recommended
    assert decision.heat_load_to_shed == "Dining/living heat pump"
    assert decision.heat_load_to_add is None


def test_blocked_heat_load_is_not_readded_during_manual_override_cooldown() -> None:
    settings = EnergyManagerSettings(export_limited_mode_enabled=True)
    decision = decide(
        base_inputs(
            now=dt(11),
            battery_soc=82,
            battery_power_w=-1200,
            forecast_remaining_today_kwh=12,
            forecast_tomorrow_kwh=35,
            pv_power_in_30_minutes_w=5200,
            any_solar_owned_heat_load_on=True,
            heat_loads=[
                HeatLoadState(
                    name="Dining/living heat pump",
                    priority=1,
                    is_on=True,
                    solar_owned=True,
                    current_temp=22.6,
                    target_temp=23.0,
                ),
                HeatLoadState(
                    name="Office heat pump",
                    priority=3,
                    is_on=False,
                    solar_owned=False,
                    current_temp=19.5,
                    target_temp=22.0,
                    blocked_until=dt(12),
                ),
            ],
        ),
        settings,
    )

    assert not decision.heat_rotation_recommended
    assert decision.heat_load_to_add is None


def test_emergency_shed_all_when_discharge_exceeds_threshold() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_power_w=4500,
            any_solar_owned_heat_load_on=True,
        )
    )

    assert decision.emergency_shed_all_required
    assert "emergency_shed_all_heat_loads" in decision.proposed_actions


def test_overnight_protection_projects_soc_to_0800() -> None:
    decision = decide(
        base_inputs(
            now=dt(23),
            battery_soc=50,
            battery_power_w=3000,
            forecast_tomorrow_kwh=35,
            any_solar_owned_heat_load_on=True,
        ),
        EnergyManagerSettings(battery_capacity_kwh=30),
    )

    assert decision.projected_soc_08 == 0
    assert decision.overnight_protection_required
    assert "overnight_shed_nonessential_heat" in decision.proposed_actions


def test_bedroom_heat_taper_recommended_overnight_for_owned_bedroom() -> None:
    decision = decide(
        base_inputs(
            now=dt(23),
            battery_soc=80,
            battery_power_w=0,
            any_solar_owned_heat_load_on=True,
            heat_loads=[
                HeatLoadState(
                    name="Bedroom heat pump",
                    priority=4,
                    is_on=True,
                    solar_owned=True,
                    current_temp=20,
                    target_temp=21,
                    load_type="heatpump",
                )
            ],
        )
    )

    assert decision.bedroom_heat_taper_recommended
    assert "taper_bedroom_heat" in decision.proposed_actions


def test_controls_block_when_manager_disabled() -> None:
    decision = decide(base_inputs(), EnergyManagerSettings(enabled=False))
    assert decision.control_blocked
    assert not decision.heat_allowed


def test_thermal_start_uses_thermal_min_soc_not_target_17_soc() -> None:
    decision = decide(
        base_inputs(
            now=dt(14),
            battery_soc=89,
            battery_power_w=-2500,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=18,
        ),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_start_min_soc=80),
    )

    assert decision.target_17_soc == 90
    assert decision.thermal_allowed
    assert "SOC 89.0 >= thermal_start_min_soc 80" in decision.thermal_action_reason


def test_forecast_override_allows_thermal_before_soc_threshold() -> None:
    decision = decide(
        base_inputs(
            now=dt(10),
            battery_soc=75,
            battery_power_w=-2500,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=12,
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            thermal_start_min_soc=80,
            battery_capacity_kwh=30,
            forecast_full_confidence_buffer_kwh=3,
        ),
    )

    assert decision.forecast_full_override_active
    assert decision.thermal_allowed
    assert "forecast_full_override active" in decision.thermal_action_reason


def test_keep_running_threshold_avoids_shed_while_charging() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=82,
            battery_power_w=-1800,
            any_solar_owned_heat_load_on=True,
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            thermal_start_min_soc=80,
            thermal_keep_running_min_charge_w=1500,
        ),
    )

    assert not decision.thermal_should_shed


def test_thermal_sheds_on_discharge_threshold() -> None:
    decision = decide(
        base_inputs(now=dt(12), battery_power_w=700, any_solar_owned_heat_load_on=True),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_shed_discharge_w=500),
    )

    assert decision.thermal_should_shed


def test_thermal_emergency_shed_threshold() -> None:
    decision = decide(
        base_inputs(now=dt(12), battery_power_w=2600, any_solar_owned_heat_load_on=True),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_emergency_shed_w=2500),
    )

    assert decision.thermal_should_emergency_shed
    assert decision.thermal_action == "emergency_shed_all"


def test_cooling_rotation_uses_cool_soak_target() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=85,
            battery_power_w=-2500,
            any_solar_owned_heat_load_on=True,
            heat_loads=[
                HeatLoadState(
                    name="Dining",
                    priority=1,
                    is_on=True,
                    solar_owned=True,
                    current_temp=18.5,
                    supports_cooling=True,
                ),
                HeatLoadState(
                    name="Office",
                    priority=3,
                    is_on=False,
                    solar_owned=False,
                    current_temp=21.0,
                    supports_cooling=True,
                ),
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_mode="cooling"),
    )

    assert decision.thermal_rotation_recommended
    assert decision.thermal_load_to_shed == "Dining"
    assert decision.thermal_load_to_add == "Office"


def test_power_sensor_marks_owned_load_as_tapering() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=85,
            battery_power_w=-2500,
            any_solar_owned_heat_load_on=True,
            heat_loads=[
                HeatLoadState(
                    name="Dining",
                    priority=1,
                    is_on=True,
                    solar_owned=True,
                    current_temp=24,
                    power_w=120,
                    taper_power_threshold_w=400,
                ),
                HeatLoadState(
                    name="Office",
                    priority=3,
                    is_on=False,
                    solar_owned=False,
                    current_temp=23,
                ),
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True),
    )

    assert decision.thermal_rotation_recommended
    assert decision.thermal_load_to_shed == "Dining"


def test_heating_mode_soak_actuation_plan() -> None:
    action = thermal_soak_action(
        EnergyManagerSettings(thermal_mode="heating", heat_soak_target_temp=27),
        HeatLoadState(name="Office", priority=3, supports_heating=True),
    )

    assert action == ("heat", 27)


def test_cooling_mode_soak_actuation_plan() -> None:
    action = thermal_soak_action(
        EnergyManagerSettings(thermal_mode="cooling", cool_soak_target_temp=18),
        HeatLoadState(name="Office", priority=3, supports_cooling=True),
    )

    assert action == ("cool", 18)


def test_heating_return_to_normal_actuation_plan() -> None:
    action = thermal_shed_action(
        EnergyManagerSettings(thermal_mode="heating", heat_normal_target_temp=21, return_to_normal_on_shed_enabled=True),
        HeatLoadState(name="Office", priority=3, load_type="heatpump"),
    )

    assert action == ("heat", 21)


def test_cooling_return_to_normal_actuation_plan() -> None:
    action = thermal_shed_action(
        EnergyManagerSettings(thermal_mode="cooling", cool_normal_target_temp=24, return_to_normal_on_shed_enabled=True),
        HeatLoadState(name="Office", priority=3, load_type="heatpump"),
    )

    assert action == ("cool", 24)


def test_underfloor_shed_turns_off() -> None:
    action = thermal_shed_action(
        EnergyManagerSettings(thermal_mode="heating", return_to_normal_on_shed_enabled=True),
        HeatLoadState(name="Underfloor", priority=2, load_type="underfloor"),
    )

    assert action == ("off", None)
