"""Tests for the Deye Energy Manager decision engine."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.deye_energy_manager import decision as decision_module
from custom_components.deye_energy_manager.const import DEFAULT_HEAT_LOADS
from custom_components.deye_energy_manager.decision import active_slot, build_deye_plan, decide, deye_capacity_percent, deye_plan_conflict_reason, deye_write_thrash_detected, disabled_programs, program_ranges, tariff_window, thermal_load_diagnostic, thermal_load_diagnostics, thermal_shed_action, thermal_soak_action
from custom_components.deye_energy_manager.decision import resolve_soc_value
from custom_components.deye_energy_manager.migration import migrate_options
from custom_components.deye_energy_manager.models import DeyePlan, EnergyManagerInputs, EnergyManagerSettings, HeatLoadState
from custom_components.deye_energy_manager.repairs import repair_issue_definitions

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
        (dt(22), "Prog4", "cheap_grid"),
        (dt(3), "Prog4", "cheap_grid"),
        (dt(5), "Prog4", "cheap_grid"),
        (dt(7, 30), "Prog1", "morning_solar_ramp"),
        (dt(14), "Prog2", "pre_peak_preserve"),
        (dt(18), "Prog3", "peak"),
    ]

    for now, slot, window in cases:
        assert active_slot(now) == slot
        assert tariff_window(now) == window


def test_program_ranges_follow_row_order_and_disable_zero_length_rows() -> None:
    ranges = program_ranges(EnergyManagerSettings())

    assert ranges[0]["program"] == "Prog1"
    assert ranges[0]["start"] == "07:00"
    assert ranges[0]["end"] == "13:00"
    assert ranges[3]["program"] == "Prog4"
    assert ranges[3]["start"] == "21:00"
    assert ranges[3]["end"] == "07:00"
    assert ranges[3]["wraps_midnight"]
    assert disabled_programs(EnergyManagerSettings()) == ["Prog5", "Prog6"]
    assert active_slot(dt(8)) == "Prog1"
    assert active_slot(dt(14)) == "Prog2"
    assert active_slot(dt(18)) == "Prog3"
    assert active_slot(dt(23)) == "Prog4"
    assert active_slot(dt(3)) == "Prog4"


def test_heat_allowed_rules() -> None:
    settings = EnergyManagerSettings(thermal_control_enabled=True)
    assert not decide(base_inputs(now=dt(10), battery_soc=31, battery_power_w=-300), settings).heat_allowed
    assert not decide(base_inputs(now=dt(10), battery_soc=31, battery_power_w=-6500), settings).heat_allowed
    assert decide(
        base_inputs(
            now=dt(10),
            battery_soc=91,
            battery_power_w=0,
            forecast_remaining_today_kwh=25,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20, estimated_load_w=1800)],
        ),
        settings,
    ).heat_allowed
    assert decide(
        base_inputs(
            now=dt(10),
            battery_soc=85,
            battery_power_w=-2000,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=25,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20, estimated_load_w=1800)],
        ),
        settings,
    ).heat_allowed


def test_heat_shed_rules() -> None:
    assert decide(base_inputs(any_solar_owned_heat_load_on=True, battery_soc=91, battery_power_w=600)).heat_should_shed
    assert decide(base_inputs(any_solar_owned_heat_load_on=True, battery_soc=31, battery_power_w=-300)).heat_should_shed
    assert not decide(base_inputs(any_solar_owned_heat_load_on=True, battery_soc=91, battery_power_w=0)).heat_should_shed
    assert not decide(base_inputs(any_solar_owned_heat_load_on=False, battery_soc=31, battery_power_w=-300)).heat_should_shed


def test_grid_charge_rules() -> None:
    settings = EnergyManagerSettings(grid_charge_control_enabled=True, cheap_grid_charge_enabled=True)
    assert decide(
        base_inputs(now=dt(4), forecast_tomorrow_kwh=12, battery_soc=35, ev_latch_on=False),
        settings,
    ).grid_charge_required
    assert not decide(
        base_inputs(now=dt(4), forecast_tomorrow_kwh=12, battery_soc=50, ev_latch_on=True),
        settings,
    ).grid_charge_required
    assert not decide(base_inputs(now=dt(8), forecast_tomorrow_kwh=12, battery_soc=50), settings).grid_charge_required
    assert not decide(base_inputs(now=dt(4), forecast_tomorrow_kwh=35, battery_soc=75), settings).grid_charge_required


def test_cheap_grid_preserve_is_separate_from_grid_charge() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=False,
        cheap_grid_preserve_soc=30,
        grid_charge_control_enabled=False,
    )

    decision = decide(
        base_inputs(now=dt(22), forecast_tomorrow_kwh=23, battery_soc=28, battery_power_w=4300),
        settings,
    )

    assert decision.tariff_window == "cheap_grid"
    assert decision.active_slot == "Prog4"
    assert decision.cheap_grid_preserve_required
    assert 30 <= decision.morning_target_soc <= 35
    assert decision.cheap_grid_mode == "preserve"
    assert not decision.grid_charge_required
    assert decision.active_reserve_target_soc >= decision.morning_target_soc
    assert "using grid for house load" in decision.cheap_grid_reason


def test_cheap_grid_topup_only_charges_to_morning_target() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        cheap_grid_preserve_soc=30,
        cheap_grid_charge_target_soc=60,
        max_grid_charge_target_soc=80,
    )

    decision = decide(base_inputs(now=dt(22), forecast_tomorrow_kwh=23, battery_soc=28), settings)

    assert decision.cheap_grid_preserve_required
    assert decision.cheap_grid_topup_required
    assert decision.grid_charge_required
    assert decision.cheap_grid_mode == "top_up_to_morning_target"
    assert 30 <= decision.morning_target_soc <= 35
    assert decision.grid_charge_target_soc == decision.morning_target_soc
    assert decision.grid_charge_target_soc < 60
    assert decision.expected_action == "cheap_grid_top_up_to_morning_target"

    plan = build_deye_plan(decision, settings)
    assert plan.mode == "top_up_to_morning_target"
    assert plan.charge_modes["Prog4"] == "Allow Grid"
    assert plan.capacity_targets["Prog4"] == decision.morning_target_soc
    assert "Prog1" not in plan.capacity_targets
    assert "Prog2" not in plan.capacity_targets
    assert "Prog3" not in plan.capacity_targets
    assert "Prog6" not in plan.capacity_targets
    assert plan.grid_charge_enabled is True


def test_cheap_grid_default_settings_do_not_target_sixty_for_medium_forecast() -> None:
    decision = decide(
        base_inputs(now=dt(22), forecast_tomorrow_kwh=23, battery_soc=23),
        EnergyManagerSettings(grid_charge_control_enabled=True),
    )

    assert decision.cheap_grid_mode == "top_up_to_morning_target"
    assert 30 <= decision.morning_target_soc <= 35
    assert decision.grid_charge_target_soc < 60
    assert decision.morning_start_soc_target == decision.morning_target_soc
    assert decision.evening_peak_soc_target >= 60
    assert decision.projected_4pm_soc >= decision.evening_peak_soc_target
    assert "4pm target" in decision.energy_plan_reason


def test_cheap_grid_high_soc_drains_to_morning_start_not_grid_charge() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        cheap_grid_preserve_soc=30,
    )

    decision = decide(base_inputs(now=dt(22), forecast_tomorrow_kwh=23, battery_soc=80), settings)

    assert 30 <= decision.morning_start_soc_target <= 35
    assert decision.cheap_grid_mode == "preserve"
    assert not decision.grid_charge_required
    assert decision.night_grid_topup_kwh_required == 0
    assert "7am target" in decision.energy_plan_reason


def test_cheap_grid_low_soc_tops_up_only_to_derived_morning_start() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        cheap_grid_preserve_soc=30,
        evening_peak_soc_target=75,
        max_grid_charge_target_soc=80,
    )

    decision = decide(base_inputs(now=dt(22), forecast_tomorrow_kwh=12, battery_soc=20), settings)

    assert decision.cheap_grid_mode == "top_up_to_morning_target"
    assert decision.grid_charge_required
    assert 40 <= decision.morning_start_soc_target <= 50
    assert decision.grid_charge_target_soc == decision.morning_start_soc_target
    assert decision.grid_charge_target_soc < decision.evening_peak_soc_target


def test_cheap_grid_at_morning_target_preserves_without_charging() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        cheap_grid_preserve_soc=30,
        cheap_grid_charge_target_soc=60,
    )

    decision = decide(base_inputs(now=dt(22), forecast_tomorrow_kwh=23, battery_soc=35), settings)

    assert decision.cheap_grid_preserve_required
    assert not decision.grid_charge_required
    assert decision.cheap_grid_mode == "preserve"
    assert decision.cheap_grid_preserve_target_soc == decision.morning_target_soc

    plan = build_deye_plan(decision, settings)
    assert plan.mode == "preserve"
    assert plan.charge_modes["Prog4"] == "No Grid or Gen"
    assert plan.capacity_targets["Prog4"] == decision.morning_target_soc
    assert "Prog1" not in plan.capacity_targets
    assert "Prog2" not in plan.capacity_targets
    assert "Prog3" not in plan.capacity_targets
    assert "Prog6" not in plan.capacity_targets
    assert plan.grid_charge_enabled is False


def test_cheap_grid_budget_uses_morning_target_not_daily_full_target() -> None:
    decision = decide(
        base_inputs(
            now=dt(22, 40),
            battery_soc=35,
            forecast_remaining_today_kwh=0,
            forecast_tomorrow_kwh=23,
        ),
        EnergyManagerSettings(daily_battery_target_soc=100, battery_capacity_kwh=30),
    )

    assert decision.energy_budget_target_name == "7am target"
    assert 30 <= decision.energy_budget_target_soc <= 35
    assert decision.battery_kwh_needed_to_target is not None
    assert decision.battery_kwh_needed_to_target < 0.2
    assert "to 7am target" in decision.energy_budget_reason
    assert "to 100%" not in decision.energy_budget_reason


def test_cheap_grid_dreadful_forecast_allows_heavy_charge() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        cheap_grid_preserve_soc=30,
        cheap_grid_charge_target_soc=60,
        max_grid_charge_target_soc=80,
    )

    decision = decide(base_inputs(now=dt(22), forecast_tomorrow_kwh=5, battery_soc=23), settings)

    assert decision.grid_charge_required
    assert decision.cheap_grid_mode == "heavy_grid_charge"
    assert 60 <= decision.grid_charge_target_soc <= 80


def test_cheap_grid_excellent_forecast_uses_lower_morning_target() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        cheap_grid_preserve_soc=30,
        cheap_grid_charge_target_soc=60,
    )

    decision = decide(base_inputs(now=dt(22), forecast_tomorrow_kwh=35, battery_soc=23), settings)

    assert decision.cheap_grid_mode == "top_up_to_morning_target"
    assert 25 <= decision.morning_target_soc <= 30
    assert decision.grid_charge_target_soc < 60


def test_cheap_grid_exits_at_7am() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        cheap_grid_preserve_soc=30,
    )

    decision = decide(base_inputs(now=dt(7), forecast_tomorrow_kwh=23, battery_soc=60), settings)

    assert decision.tariff_window != "cheap_grid"
    assert decision.cheap_grid_mode == "off"
    assert not decision.cheap_grid_preserve_required
    assert not decision.grid_charge_required

    plan = build_deye_plan(decision, settings)
    assert decision.active_slot == "Prog1"
    assert plan.charge_modes["Prog1"] == "No Grid or Gen"
    assert plan.capacity_targets["Prog1"] == decision.active_reserve_target_soc
    assert plan.capacity_targets["Prog1"] < 60
    assert plan.grid_charge_enabled is False


def test_paid_time_clamp_prevents_observed_0800_prog3_soc_pinning() -> None:
    settings = EnergyManagerSettings(deye_control_enabled=True, grid_charge_control_enabled=True)
    decision = decide(
        base_inputs(now=dt(8), battery_soc=60, forecast_tomorrow_kwh=8, grid_power_w=0),
        settings,
    )

    assert decision.active_slot == "Prog1"
    assert decision.current_reserve_soc == 60

    plan = build_deye_plan(decision, settings)

    assert plan.mode == "paid_time_discharge_enable"
    assert plan.capacity_targets["Prog1"] < 60
    assert plan.capacity_targets["Prog1"] == settings.min_soc_floor
    assert plan.charge_modes["Prog1"] == "No Grid or Gen"
    assert plan.grid_charge_enabled is False


def test_post_cheap_restore_prog3_below_soc_at_0700() -> None:
    settings = EnergyManagerSettings(deye_control_enabled=True, grid_charge_control_enabled=True)

    for soc in (35, 60):
        decision = decide(base_inputs(now=dt(7), battery_soc=soc, forecast_tomorrow_kwh=8), settings)
        plan = build_deye_plan(decision, settings)

        assert decision.active_slot == "Prog1"
        assert plan.mode == "paid_time_discharge_enable"
        assert plan.capacity_targets["Prog1"] < soc
        assert plan.capacity_targets["Prog1"] == settings.min_soc_floor
        assert plan.charge_modes["Prog1"] == "No Grid or Gen"
        assert plan.grid_charge_enabled is False
        assert "post-cheap restore" in plan.post_cheap_restore_reason


def test_cheap_grid_high_soc_preserves_without_grid_charge() -> None:
    settings = EnergyManagerSettings(
        grid_charge_control_enabled=True,
        cheap_grid_preserve_soc=25,
        evening_peak_soc_target=50,
        battery_capacity_kwh=30,
    )
    decision = decide(base_inputs(now=dt(22), battery_soc=70, forecast_tomorrow_kwh=35), settings)
    plan = build_deye_plan(decision, settings)

    assert decision.cheap_grid_mode == "preserve"
    assert not decision.grid_charge_required
    assert 25 <= decision.morning_start_soc_target <= 30
    assert plan.capacity_targets["Prog4"] == decision.morning_start_soc_target
    assert plan.charge_modes["Prog4"] == "No Grid or Gen"
    assert plan.grid_charge_enabled is False


def test_deye_plan_capacity_targets_are_whole_percent_values() -> None:
    settings = EnergyManagerSettings(grid_charge_control_enabled=True)
    decision = decide(base_inputs(now=dt(22), battery_soc=65, forecast_tomorrow_kwh=20), settings)
    decision.cheap_grid_preserve_required = True
    decision.grid_charge_required = False
    decision.cheap_grid_preserve_target_soc = 50.5242666666667
    decision.cheap_grid_mode = "preserve"
    decision.cheap_grid_reason = "preserve fractional regression"

    plan = build_deye_plan(decision, settings)

    assert plan.capacity_targets["Prog4"] == 51
    assert all(float(value).is_integer() for value in plan.capacity_targets.values())
    assert deye_capacity_percent(50.5242666666667) == 51


def test_cheap_grid_low_soc_charges_only_until_morning_target_then_preserves() -> None:
    settings = EnergyManagerSettings(
        grid_charge_control_enabled=True,
        cheap_grid_preserve_soc=30,
        cheap_grid_charge_target_soc=60,
    )
    low = decide(base_inputs(now=dt(22), battery_soc=18, forecast_tomorrow_kwh=23), settings)
    low_plan = build_deye_plan(low, settings)

    assert low.cheap_grid_mode == "top_up_to_morning_target"
    assert low.grid_charge_required
    assert low_plan.capacity_targets["Prog4"] == low.morning_start_soc_target
    assert low_plan.charge_modes["Prog4"] == "Allow Grid"

    reached = decide(
        base_inputs(now=dt(22), battery_soc=low.morning_start_soc_target, forecast_tomorrow_kwh=23),
        settings,
    )
    reached_plan = build_deye_plan(reached, settings)

    assert reached.cheap_grid_mode == "preserve"
    assert not reached.grid_charge_required
    assert reached_plan.capacity_targets["Prog4"] == reached.morning_start_soc_target
    assert reached_plan.charge_modes["Prog4"] == "No Grid or Gen"


def test_heavy_charge_latch_prevents_immediate_reentry_after_target_reached() -> None:
    settings = EnergyManagerSettings(
        grid_charge_control_enabled=True,
        cheap_grid_charge_target_soc=75,
        cheap_grid_recharge_hysteresis_soc=5,
        cheap_grid_target_increase_hysteresis_soc=3,
    )

    decision = decide(
        base_inputs(
            now=dt(22),
            battery_soc=72,
            forecast_tomorrow_kwh=5,
            cheap_grid_charge_blocked_target_soc=75,
        ),
        settings,
    )
    plan = build_deye_plan(decision, settings)

    assert decision.cheap_grid_mode == "preserve"
    assert not decision.grid_charge_required
    assert plan.charge_modes["Prog4"] == "No Grid or Gen"
    assert plan.capacity_targets["Prog4"] != 75


def test_cheap_grid_active_program_does_not_emit_55_75_flapping_after_latch() -> None:
    settings = EnergyManagerSettings(
        grid_charge_control_enabled=True,
        cheap_grid_preserve_soc=55,
        cheap_grid_charge_target_soc=75,
        cheap_grid_recharge_hysteresis_soc=5,
    )
    outputs = []
    for soc in (72, 73, 72, 73):
        decision = decide(
            base_inputs(
                now=dt(22),
                battery_soc=soc,
                forecast_tomorrow_kwh=5,
                cheap_grid_charge_blocked_target_soc=75,
            ),
            settings,
        )
        outputs.append(build_deye_plan(decision, settings).capacity_targets["Prog4"])

    assert outputs != [55, 75, 55, 75]
    assert len(set(outputs)) == 1


def test_thermal_shed_during_cheap_grid_does_not_change_deye_plan() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        thermal_control_enabled=True,
        cheap_grid_preserve_soc=30,
    )
    base = base_inputs(
        now=dt(4, 15),
        forecast_tomorrow_kwh=23,
        battery_soc=35,
        battery_power_w=900,
        any_solar_owned_heat_load_on=True,
    )

    decision = decide(base, settings)
    assert decision.thermal_should_shed
    assert decision.cheap_grid_mode == "preserve"

    plan = build_deye_plan(decision, settings)
    assert plan.mode == "preserve"
    assert not plan.emergency
    assert plan.charge_modes["Prog4"] == "No Grid or Gen"
    assert plan.capacity_targets["Prog4"] == decision.morning_target_soc
    assert "Prog1" not in plan.capacity_targets


def test_emergency_thermal_shed_does_not_mark_deye_plan_emergency() -> None:
    decision = decide(
        base_inputs(
            now=dt(22),
            battery_soc=35,
            battery_power_w=3000,
            any_solar_owned_heat_load_on=True,
        ),
        EnergyManagerSettings(
            deye_control_enabled=True,
            grid_charge_control_enabled=True,
            thermal_control_enabled=True,
            thermal_emergency_shed_w=2500,
        ),
    )

    assert decision.thermal_should_emergency_shed
    plan = build_deye_plan(decision, EnergyManagerSettings())
    assert not plan.emergency
    assert "emergency thermal shed active" in plan.reason


def test_deye_plan_conflict_detection_blocks_same_entity_different_values() -> None:
    plan = DeyePlan(
        mode="test",
        reason="test",
        capacity_targets={"Prog1": 55},
        power_targets={"Prog1": 12000},
    )

    reason = deye_plan_conflict_reason(
        plan,
        {"Prog1": "number.deye_prog1"},
        {},
        {"Prog1": "number.deye_prog1"},
    )

    assert reason is not None
    assert "same-cycle conflict" in reason


def test_deye_write_thrash_detector_flags_repeated_alternation() -> None:
    now = dt(4, 20)
    attempts = [
        (now - timedelta(minutes=9, seconds=-index), "number.deye_prog6_capacity", value)
        for index, value in enumerate([55, 75, 55, 75, 55, 75, 55])
    ]

    assert deye_write_thrash_detected(attempts, "number.deye_prog6_capacity", now)


def test_ev_bypass_does_not_clear_cheap_grid_preserve_target() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        ev_control_enabled=True,
        ev_grid_bypass_enabled=True,
        cheap_grid_preserve_soc=30,
        cheap_grid_charge_target_soc=60,
    )

    decision = decide(
        base_inputs(now=dt(22), forecast_tomorrow_kwh=23, battery_soc=28, essential_power_w=6200, previous_essential_power_w=1000),
        settings,
    )

    assert decision.ev_grid_bypass_required
    assert decision.cheap_grid_mode == "ev_bypass"
    assert decision.cheap_grid_preserve_required
    assert not decision.grid_charge_required
    assert decision.active_reserve_target_soc >= decision.morning_target_soc


def test_ev_bypass_suspends_battery_grid_topup_until_ev_stops() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        ev_control_enabled=True,
        ev_grid_bypass_enabled=True,
        cheap_grid_preserve_soc=30,
    )

    with_ev = decide(
        base_inputs(now=dt(22), forecast_tomorrow_kwh=23, battery_soc=23, essential_power_w=7200, previous_essential_power_w=1000),
        settings,
    )
    after_ev = decide(
        base_inputs(now=dt(22), forecast_tomorrow_kwh=23, battery_soc=23, essential_power_w=1000, previous_essential_power_w=7200, ev_latch_on=True),
        settings,
    )

    assert with_ev.ev_grid_bypass_required
    assert with_ev.cheap_grid_mode == "ev_bypass"
    assert not with_ev.grid_charge_required
    assert with_ev.active_reserve_target_soc >= with_ev.morning_target_soc
    assert not after_ev.ev_grid_bypass_required
    assert after_ev.cheap_grid_mode == "top_up_to_morning_target"
    assert after_ev.grid_charge_required


def test_ev_start_and_stop_rules() -> None:
    settings = EnergyManagerSettings(ev_control_enabled=True, ev_grid_bypass_enabled=True)
    assert decide(
        base_inputs(now=dt(22), essential_power_w=6200, previous_essential_power_w=1000),
        settings,
    ).ev_grid_mode_required
    assert decide(
        base_inputs(now=dt(22), ev_latch_on=True, essential_power_w=3200, previous_essential_power_w=3300),
        settings,
    ).ev_grid_mode_required
    assert not decide(
        base_inputs(now=dt(22), ev_latch_on=True, essential_power_w=2000, previous_essential_power_w=8600),
        settings,
    ).ev_grid_mode_required
    assert not decide(base_inputs(now=dt(22), ev_latch_on=True, porsche_soc=99), settings).ev_grid_mode_required
    assert not decide(base_inputs(now=dt(7), ev_latch_on=True), settings).ev_grid_mode_required
    assert not decide(
        base_inputs(now=dt(3), ev_latch_on=True, ev_hold_until=dt(3) - timedelta(minutes=1), essential_power_w=2400),
        settings,
    ).ev_grid_mode_required


def test_ev_power_sensor_detects_charging() -> None:
    decision = decide(
        base_inputs(now=dt(22), ev_power_w=1500),
        EnergyManagerSettings(ev_control_enabled=True, ev_grid_bypass_enabled=True),
    )

    assert decision.ev_charging_detected
    assert decision.ev_grid_bypass_required
    assert decision.ev_expected_action == "ev_grid_bypass_start"


def test_ev_power_sensor_stop_restores_latch() -> None:
    decision = decide(
        base_inputs(now=dt(22), ev_latch_on=True, ev_power_w=100, ev_low_since=dt(21, 55)),
        EnergyManagerSettings(ev_control_enabled=True, ev_grid_bypass_enabled=True),
    )

    assert not decision.ev_latch_active
    assert decision.ev_expected_action == "ev_grid_bypass_restore"


def test_inferred_ev_latch_restores_after_sustained_low_house_load() -> None:
    decision = decide(
        base_inputs(
            now=dt(22),
            ev_latch_on=True,
            ev_hold_until=dt(23),
            ev_power_w=None,
            essential_power_w=1800,
            previous_essential_power_w=1900,
        ),
        EnergyManagerSettings(ev_control_enabled=True, ev_grid_bypass_enabled=True),
    )

    assert not decision.ev_latch_active
    assert not decision.ev_grid_bypass_required
    assert decision.ev_expected_action == "ev_grid_bypass_restore"
    assert decision.ev_decision_reason == "EV stop condition active"


def test_inferred_ev_latch_holds_while_house_load_still_elevated() -> None:
    decision = decide(
        base_inputs(
            now=dt(22),
            ev_latch_on=True,
            ev_hold_until=dt(23),
            ev_power_w=None,
            essential_power_w=3200,
            previous_essential_power_w=3300,
        ),
        EnergyManagerSettings(ev_control_enabled=True, ev_grid_bypass_enabled=True),
    )

    assert decision.ev_latch_active
    assert decision.ev_grid_bypass_required
    assert decision.ev_expected_action == "ev_grid_bypass_hold"
    assert decision.ev_decision_reason == "EV bypass latch holding from previous detection"


def test_porsche_stale_status_does_not_hold_after_expiry_and_low_load() -> None:
    decision = decide(
        base_inputs(
            now=dt(3),
            ev_latch_on=True,
            ev_hold_until=dt(2, 50),
            essential_power_w=1200,
            ev_power_w=0,
            porsche_charging_status="charging",
        ),
        EnergyManagerSettings(ev_control_enabled=True, ev_grid_bypass_enabled=True),
    )

    assert not decision.ev_latch_active
    assert decision.ev_expected_action == "ev_grid_bypass_restore"


def test_ev_bypass_suppresses_battery_grid_charge() -> None:
    decision = decide(
        base_inputs(
            now=dt(4),
            forecast_tomorrow_kwh=12,
            battery_soc=50,
            ev_power_w=2000,
        ),
        EnergyManagerSettings(
            grid_charge_control_enabled=True,
            ev_control_enabled=True,
            ev_grid_bypass_enabled=True,
        ),
    )

    assert decision.ev_grid_bypass_required
    assert not decision.grid_charge_required


def test_ev_bypass_uses_limited_program_power_not_zero() -> None:
    settings = EnergyManagerSettings(
        grid_charge_control_enabled=True,
        ev_control_enabled=True,
        ev_grid_bypass_enabled=True,
        ev_bypass_program_power_w=2000,
    )
    decision = decide(
        base_inputs(
            now=dt(4),
            forecast_tomorrow_kwh=12,
            battery_soc=50,
            ev_power_w=2000,
        ),
        settings,
    )
    plan = build_deye_plan(decision, settings)

    assert decision.active_slot == "Prog4"
    assert decision.ev_grid_bypass_required
    assert plan.power_targets == {"Prog4": 2000}


def test_ev_solar_charge_allowed_when_priority_prefers_ev() -> None:
    decision = decide(
        base_inputs(now=dt(12), battery_soc=90, forecast_tomorrow_kwh=35, forecast_remaining_today_kwh=22),
        EnergyManagerSettings(
            ev_control_enabled=True,
            ev_solar_charging_enabled=True,
            flexible_load_priority="ev_before_thermal",
        ),
    )

    assert decision.ev_solar_charge_allowed
    assert decision.ev_expected_action == "allow_solar_charge"


def test_pv_load_test_recommendation_is_retired_when_expected_pv_is_high() -> None:
    settings = EnergyManagerSettings(export_limited_mode_enabled=True)
    decision = decide(
        base_inputs(
            now=dt(11),
            battery_soc=78,
            battery_power_w=-1200,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=22,
            pv_power_now_w=1500,
            pv_power_in_30_minutes_w=5200,
            any_solar_owned_heat_load_on=False,
        ),
        settings,
    )

    assert not decision.pv_load_test_recommended
    assert "test_one_pv_load" not in decision.proposed_actions


def test_live_export_allows_thermal_soak_with_low_forecast_budget() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=45,
            grid_power_w=-2200,
            export_power_w=2200,
            forecast_remaining_today_kwh=0,
            forecast_tomorrow_kwh=15,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            daily_battery_target_soc=100,
            thermal_start_min_soc=80,
            thermal_export_start_w=1000,
            thermal_export_import_tolerance_w=300,
        ),
    )

    assert decision.export_power_w == 2200
    assert decision.grid_import_w == 0
    assert decision.export_soak_available
    assert decision.solar_soak_allowed
    assert decision.thermal_allowed
    assert decision.thermal_load_to_add == "Office"
    assert decision.thermal_action == "add_one"
    assert "add_one_heat_load" in decision.proposed_actions
    assert "export soak available" in decision.thermal_action_reason


def test_live_export_must_fit_candidate_load_before_thermal_soak_starts() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=45,
            grid_power_w=-1200,
            export_power_w=1200,
            forecast_remaining_today_kwh=0,
            forecast_tomorrow_kwh=15,
            heat_loads=[HeatLoadState(name="Dining", priority=1, current_temp=20, estimated_load_w=3000)],
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            daily_battery_target_soc=100,
            thermal_start_min_soc=80,
            thermal_export_start_w=1000,
            thermal_export_import_tolerance_w=300,
        ),
    )

    assert decision.export_soak_available
    assert decision.solar_soak_allowed
    assert decision.thermal_allowed
    assert decision.thermal_load_to_add is None
    assert decision.thermal_action == "hold"


def test_no_live_export_keeps_old_budget_block_for_solar_soak() -> None:
    clipped_inputs = base_inputs(
        now=dt(11),
        battery_soc=78,
        battery_power_w=-1200,
        forecast_tomorrow_kwh=35,
        forecast_remaining_today_kwh=12,
        pv_power_in_30_minutes_w=5200,
    )

    assert not decide(clipped_inputs).pv_load_test_recommended
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=45,
            forecast_remaining_today_kwh=0,
            forecast_tomorrow_kwh=15,
            pv_power_in_30_minutes_w=5200,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, daily_battery_target_soc=100),
    )

    assert not decision.export_soak_available
    assert not decision.solar_soak_allowed
    assert not decision.thermal_allowed


def test_paid_grid_avoidance_blocks_export_soak() -> None:
    decision = decide(
        base_inputs(
            now=dt(18),
            battery_soc=31,
            grid_power_w=-2200,
            export_power_w=2200,
            paid_grid_import_w=800,
            forecast_remaining_today_kwh=30,
            forecast_tomorrow_kwh=35,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_export_start_w=1000),
    )

    assert decision.paid_grid_avoidance_required
    assert decision.export_soak_available
    assert not decision.solar_soak_allowed
    assert not decision.thermal_allowed


def test_battery_discharge_blocks_export_soak() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=95,
            battery_power_w=700,
            grid_power_w=-2200,
            export_power_w=2200,
            forecast_remaining_today_kwh=30,
            forecast_tomorrow_kwh=35,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_shed_discharge_w=500, thermal_export_start_w=1000),
    )

    assert decision.thermal_should_shed
    assert decision.export_soak_available
    assert not decision.solar_soak_allowed
    assert not decision.thermal_allowed


def test_heat_rotation_recommended_for_tapered_owned_load_and_colder_room() -> None:
    settings = EnergyManagerSettings(thermal_control_enabled=True, export_limited_mode_enabled=True)
    decision = decide(
        base_inputs(
            now=dt(11),
                battery_soc=82,
                battery_power_w=-1200,
                forecast_remaining_today_kwh=25,
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
    assert decision.thermal_action == "none"


def test_thermal_control_disabled_blocks_comfort_and_underfloor_actions() -> None:
    decision = decide(
        base_inputs(
            now=dt(18),
            battery_soc=80,
            grid_power_w=0,
            heat_loads=[
                HeatLoadState(name="Bedroom", priority=1, current_temp=16, supports_heating=True),
                HeatLoadState(
                    name="Bathroom underfloor",
                    priority=2,
                    current_temp=7,
                    load_type="floor_underfloor",
                    comfort_min_temp=9,
                    comfort_target_temp=12,
                    supports_heating=True,
                ),
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=False, underfloor_schedule_enabled=True),
    )

    assert not decision.comfort_heat_allowed
    assert not decision.underfloor_comfort_allowed
    assert decision.thermal_action == "none"


def test_thermal_start_uses_thermal_min_soc_not_target_17_soc() -> None:
    decision = decide(
        base_inputs(
            now=dt(14),
            battery_soc=89,
            battery_power_w=-2500,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=18,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_start_min_soc=80),
    )

    assert decision.target_17_soc == 90
    assert decision.thermal_allowed
    assert "budget" in decision.thermal_action_reason


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
    assert not decision.thermal_allowed
    assert decision.thermal_policy_state == "battery_priority"
    assert "budget" in decision.thermal_action_reason


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


def test_discharge_with_owned_load_sheds() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_power_w=700,
            any_solar_owned_heat_load_on=True,
            heat_loads=[
                HeatLoadState(
                    name="Dining",
                    priority=1,
                    is_on=True,
                    solar_owned=True,
                    current_temp=27,
                    target_temp=27,
                    hvac_mode="heat",
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_shed_discharge_w=500),
    )

    assert decision.thermal_should_shed


def test_discharge_without_owned_load_explains_unowned_shedding_disabled() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_power_w=1079,
            any_solar_owned_heat_load_on=False,
            heat_loads=[
                HeatLoadState(
                    name="Dining",
                    priority=1,
                    is_on=True,
                    solar_owned=False,
                    current_temp=25,
                    target_temp=27,
                    hvac_mode="heat",
                    fan_mode="high",
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_shed_discharge_w=500),
    )

    assert decision.thermal_should_shed
    assert decision.thermal_load_to_normalise is None
    assert decision.expected_action == "shed_blocked_no_owned_loads"
    assert "no owned thermal loads to shed" in decision.reason
    assert "unowned shedding disabled" in decision.reason


def test_discharge_with_unowned_shedding_enabled_selects_soak_like_load() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_power_w=1079,
            any_solar_owned_heat_load_on=False,
            heat_loads=[
                HeatLoadState(
                    name="Dining",
                    priority=1,
                    is_on=True,
                    solar_owned=False,
                    current_temp=25,
                    target_temp=27,
                    hvac_mode="heat",
                    fan_mode="high",
                )
            ],
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            thermal_shed_discharge_w=500,
            shed_unowned_managed_loads_on_battery_discharge=True,
        ),
    )

    assert decision.thermal_should_shed
    assert decision.thermal_load_to_normalise == "Dining"
    assert "normalising unowned managed load due to battery discharge" in decision.reason


def test_unowned_shedding_does_not_select_non_soak_like_managed_load() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_power_w=1079,
            any_solar_owned_heat_load_on=False,
            heat_loads=[
                HeatLoadState(
                    name="Office",
                    priority=1,
                    is_on=True,
                    solar_owned=False,
                    current_temp=21,
                    target_temp=21,
                    hvac_mode="heat",
                    fan_mode="low",
                )
            ],
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            thermal_shed_discharge_w=500,
            shed_unowned_managed_loads_on_battery_discharge=True,
        ),
    )

    assert decision.thermal_should_shed
    assert decision.thermal_load_to_normalise is None
    assert decision.expected_action == "shed_blocked_no_owned_loads"


def test_thermal_emergency_shed_threshold() -> None:
    decision = decide(
        base_inputs(now=dt(12), battery_power_w=2600, any_solar_owned_heat_load_on=True),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_emergency_shed_w=2500),
    )

    assert decision.thermal_should_emergency_shed
    assert decision.thermal_action == "emergency_shed_all"


def test_high_discharge_sets_shed_and_emergency_without_owned_loads() -> None:
    decision = decide(
        base_inputs(now=dt(12), battery_power_w=4204, any_solar_owned_heat_load_on=False),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            thermal_shed_discharge_w=500,
            thermal_emergency_shed_w=2500,
            emergency_shed_discharge_w=4000,
        ),
    )

    assert decision.thermal_should_shed
    assert decision.thermal_should_emergency_shed
    assert decision.thermal_action == "emergency_shed_all"
    assert decision.expected_action == "thermal_emergency_shed_all"
    assert "thermal_should_shed=true: battery discharging 4204W >= shed threshold 500W" in decision.reason
    assert "battery charge 0W, forecast_full_override" not in decision.reason


def test_cooling_rotation_uses_cool_soak_target() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
                battery_soc=85,
                battery_power_w=-2500,
                forecast_remaining_today_kwh=25,
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
                forecast_remaining_today_kwh=25,
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

    assert action == ("heat", 27, "high")


def test_cooling_mode_soak_actuation_plan() -> None:
    action = thermal_soak_action(
        EnergyManagerSettings(thermal_mode="cooling", cool_soak_target_temp=18),
        HeatLoadState(name="Office", priority=3, supports_cooling=True),
    )

    assert action == ("cool", 18, "high")


def test_heating_return_to_normal_actuation_plan() -> None:
    action = thermal_shed_action(
        EnergyManagerSettings(thermal_mode="heating", heat_normal_target_temp=21, return_to_normal_on_shed_enabled=True),
        HeatLoadState(name="Office", priority=3, load_type="heatpump"),
    )

    assert action == ("heat", 21, "low")


def test_cooling_return_to_normal_actuation_plan() -> None:
    action = thermal_shed_action(
        EnergyManagerSettings(thermal_mode="cooling", cool_normal_target_temp=24, return_to_normal_on_shed_enabled=True),
        HeatLoadState(name="Office", priority=3, load_type="heatpump"),
    )

    assert action == ("cool", 24, "low")


def test_underfloor_shed_turns_off() -> None:
    action = thermal_shed_action(
        EnergyManagerSettings(thermal_mode="heating", return_to_normal_on_shed_enabled=True),
        HeatLoadState(name="Underfloor", priority=2, load_type="underfloor"),
    )

    assert action == ("off", None, None)


def test_cooldown_prevents_short_cycle_add() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=85,
            battery_power_w=-3000,
            heat_loads=[
                HeatLoadState(
                    name="Office",
                    priority=1,
                    is_on=False,
                    solar_owned=False,
                    current_temp=20,
                    last_shed_at=dt(11, 55),
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, min_thermal_rest_minutes=10),
    )

    assert decision.thermal_load_to_add is None


def test_emergency_shed_bypasses_run_cooldown() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_power_w=3000,
            any_solar_owned_heat_load_on=True,
            heat_loads=[
                HeatLoadState(
                    name="Office",
                    priority=1,
                    is_on=True,
                    solar_owned=True,
                    current_temp=20,
                    last_added_at=dt(11, 55),
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_emergency_shed_w=2500, min_thermal_run_minutes=20),
    )

    assert decision.thermal_should_emergency_shed
    assert decision.thermal_action == "emergency_shed_all"


def test_per_load_diagnostic_explains_cooldown() -> None:
    inputs = base_inputs(
        now=dt(12),
        heat_loads=[
            HeatLoadState(
                name="Office",
                priority=1,
                is_on=False,
                solar_owned=False,
                current_temp=20,
                last_shed_at=dt(11, 55),
            )
        ],
    )
    settings = EnergyManagerSettings(min_thermal_rest_minutes=10)
    diagnostic = thermal_load_diagnostic(inputs.heat_loads[0], settings, inputs)

    assert diagnostic.state == "cooldown"
    assert diagnostic.attributes["blocked_by_cooldown"]
    assert "min rest" in str(diagnostic.attributes["blocked_reason"])


def test_auto_mode_chooses_heating_from_outdoor_temp() -> None:
    decision = decide(
        base_inputs(now=dt(12), outdoor_temperature=9.5),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_mode="auto"),
    )

    assert decision.effective_thermal_mode == "heating"
    assert "outdoor temp 9.5 <= heating threshold" in decision.auto_mode_reason


def test_auto_mode_chooses_cooling_from_outdoor_temp() -> None:
    decision = decide(
        base_inputs(now=dt(12), outdoor_temperature=27),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_mode="auto"),
    )

    assert decision.effective_thermal_mode == "cooling"
    assert "outdoor temp 27.0 >= cooling threshold" in decision.auto_mode_reason


def test_auto_mode_southern_hemisphere_month_fallback() -> None:
    decision = decide(
        base_inputs(now=dt(12).replace(month=7), outdoor_temperature=None),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_mode="auto"),
    )

    assert decision.effective_thermal_mode == "heating"
    assert "Southern Hemisphere heating season" in decision.auto_mode_reason


def test_repair_issue_for_missing_climate() -> None:
    issues = repair_issue_definitions(
        EnergyManagerSettings(),
        {},
        [
            {
                "name": "Office",
                "enabled": True,
                "climate_entity": "climate.office_heatpump",
                "ownership_entity": "input_boolean.solar_owns_office_heatpump",
            }
        ],
        lambda entity_id: entity_id == "input_boolean.solar_owns_office_heatpump",
    )

    assert "climate_entity_unavailable" in issues


def test_repair_issue_for_retired_script_mode() -> None:
    issues = repair_issue_definitions(
        EnergyManagerSettings(thermal_actuation_mode="scripts"),
        {},
        [],
        lambda _entity_id: False,
    )

    assert "scripts_retired" in issues


def test_repair_issue_for_invalid_ev_power_sensor() -> None:
    issues = repair_issue_definitions(
        EnergyManagerSettings(),
        {"ev_power": "sensor.ev_power"},
        [],
        lambda _entity_id: False,
    )

    assert "ev_power_invalid" in issues


def test_per_load_diagnostic_uses_stable_slug() -> None:
    inputs = base_inputs(
        heat_loads=[
            HeatLoadState(
                name="Dining/living heat pump",
                priority=1,
                slug="dining",
                climate_entity="climate.diningheatpump_mqtt_hvac",
                ownership_entity="input_boolean.solar_owns_dining_heatpump",
            )
        ]
    )
    diagnostic = thermal_load_diagnostic(inputs.heat_loads[0], EnergyManagerSettings(), inputs)

    assert diagnostic.slug == "dining"
    assert diagnostic.attributes["load_slug"] == "dining"
    assert diagnostic.attributes["climate_entity"] == "climate.diningheatpump_mqtt_hvac"


def test_unsupported_fan_mode_is_reported_in_diagnostic() -> None:
    inputs = base_inputs(
        heat_loads=[
            HeatLoadState(
                name="Office",
                priority=1,
                current_temp=20,
                supported_fan_modes=("auto", "quiet"),
            )
        ]
    )
    decision = decide(
        inputs,
        EnergyManagerSettings(thermal_control_enabled=True, heat_soak_fan_mode="high"),
    )
    diagnostic = thermal_load_diagnostic(inputs.heat_loads[0], EnergyManagerSettings(heat_soak_fan_mode="high"), inputs, decision)

    assert diagnostic.attributes["desired_soak_fan_mode"] == "high"
    assert not diagnostic.attributes["fan_mode_supported"]
    assert "not in supported" in str(diagnostic.attributes["fan_mode_blocked_reason"])


def test_unowned_shed_candidate_is_reported_in_diagnostic() -> None:
    inputs = base_inputs(
        heat_loads=[
            HeatLoadState(
                name="Dining",
                priority=1,
                is_on=True,
                solar_owned=False,
                current_temp=25,
                target_temp=27,
                hvac_mode="heat",
                fan_mode="high",
            )
        ]
    )
    diagnostic = thermal_load_diagnostic(inputs.heat_loads[0], EnergyManagerSettings(), inputs)

    assert diagnostic.attributes["owned_by_manager"] is False
    assert diagnostic.attributes["unowned_shed_candidate"] is True
    assert diagnostic.attributes["unowned_shed_reason"]


def test_missing_fan_modes_do_not_error_and_are_reported() -> None:
    inputs = base_inputs(heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20)])
    diagnostic = thermal_load_diagnostic(inputs.heat_loads[0], EnergyManagerSettings(), inputs)

    assert diagnostic.attributes["supported_fan_modes"] == []
    assert not diagnostic.attributes["fan_mode_supported"]
    assert diagnostic.attributes["fan_mode_blocked_reason"] == "climate does not expose fan_modes"


def test_load_diagnostics_keys_for_default_loads() -> None:
    loads = [
        HeatLoadState(
            name=str(load["name"]),
            priority=int(load["priority"]),
            slug=str(load["slug"]),
            climate_entity=str(load["climate_entity"]),
            ownership_entity=str(load["ownership_entity"]),
        )
        for load in DEFAULT_HEAT_LOADS
    ]
    inputs = base_inputs(heat_loads=loads)
    decision = decide(inputs, EnergyManagerSettings())
    diagnostics = thermal_load_diagnostics(inputs, EnergyManagerSettings(), decision)

    assert {"dining", "bedroom", "office", "hallway", "underfloor"} <= set(diagnostics)


def test_load_diagnostics_fail_safe_does_not_crash(monkeypatch) -> None:
    inputs = base_inputs(heat_loads=[HeatLoadState(name="Dining", priority=1, slug="dining")])
    decision = decide(inputs, EnergyManagerSettings())

    def broken_diagnostic(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(decision_module, "thermal_load_diagnostic", broken_diagnostic)
    diagnostics = decision_module.thermal_load_diagnostics(inputs, EnergyManagerSettings(), decision)

    assert diagnostics["dining"].state == "unavailable"
    assert diagnostics["dining"].attributes["blocked_reason"] == "diagnostic_error"


def test_soc_resolver_uses_live_numeric_soc() -> None:
    soc, source, age = resolve_soc_value("100", 80, dt(11, 55), dt(12), 360)

    assert soc == 100
    assert source == "live"
    assert age == 0


def test_soc_resolver_uses_fresh_last_known_good() -> None:
    soc, source, age = resolve_soc_value("unknown", 100, dt(11, 52), dt(12), 360)

    assert soc == 100
    assert source == "last_known_good"
    assert age == 8


def test_budget_calculates_with_restored_last_known_good_soc() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=88.25,
            raw_soc="unknown",
            soc_source="last_known_good",
            soc_age_minutes=12,
            last_good_soc=88.25,
            last_good_soc_updated=dt(11, 48),
            forecast_remaining_today_kwh=18,
            forecast_tomorrow_kwh=35,
        ),
        EnergyManagerSettings(thermal_control_enabled=True),
    )

    assert decision.soc_source == "last_known_good"
    assert decision.battery_kwh_needed_to_target is not None
    assert decision.discretionary_energy_budget_kwh is not None
    assert "SOC last-known-good: 88%, age 12m" in decision.reason
    assert decision.last_good_soc == 88.25


def test_stale_restored_soc_keeps_budget_unavailable() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=None,
            raw_soc="unknown",
            soc_source="unavailable",
            soc_age_minutes=420,
            last_good_soc=88.25,
            last_good_soc_updated=dt(5),
            forecast_remaining_today_kwh=18,
        ),
        EnergyManagerSettings(),
    )

    assert decision.battery_kwh_needed_to_target is None
    assert decision.discretionary_energy_budget_kwh is None
    assert "SOC unavailable" in decision.reason


def test_soc_resolver_rejects_stale_last_known_good() -> None:
    soc, source, age = resolve_soc_value("unknown", 100, dt(5), dt(12), 360)

    assert soc is None
    assert source == "unavailable"
    assert age == 420


def test_unknown_soc_never_becomes_zero() -> None:
    soc, source, _age = resolve_soc_value("unknown", None, None, dt(12), 360)

    assert soc is None
    assert source == "unavailable"


def test_underfloor_policy_uses_restored_soc_when_raw_soc_unknown() -> None:
    decision = decide(
        base_inputs(
            now=dt(18),
            battery_soc=60,
            raw_soc="unknown",
            soc_source="last_known_good",
            soc_age_minutes=10,
            last_good_soc=60,
            last_good_soc_updated=dt(17, 50),
            forecast_remaining_today_kwh=10,
            heat_loads=[
                HeatLoadState(
                    name="Bathroom underfloor",
                    priority=1,
                    current_temp=8,
                    load_type="floor_underfloor",
                    comfort_min_temp=9,
                    comfort_target_temp=12,
                    allow_solar_soak=False,
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, underfloor_min_soc=40),
    )

    assert decision.underfloor_comfort_allowed
    assert decision.thermal_target_temperature == 12


def test_discharge_sheds_with_soc_unavailable() -> None:
    decision = decide(
        base_inputs(battery_soc=None, battery_power_w=700, any_solar_owned_heat_load_on=True),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_shed_discharge_w=500),
    )

    assert decision.thermal_should_shed
    assert "SOC unavailable" in decision.reason


def test_charge_rate_allows_thermal_with_soc_unavailable() -> None:
    decision = decide(
        base_inputs(now=dt(10), battery_soc=None, battery_power_w=-6500),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_start_min_charge_w=6000),
    )

    assert not decision.thermal_allowed
    assert decision.discretionary_energy_budget_kwh is None
    assert decision.battery_soc is None


def test_legacy_heat_script_options_map_to_advisory_settings() -> None:
    options, changed = migrate_options(
        {
            "heat_control_enabled": True,
            "thermal_control_enabled": False,
            "heat_mode": "auto_scripts",
            "thermal_actuation_mode": "advisory",
        }
    )

    assert changed
    assert options["thermal_control_enabled"]
    assert options["heat_mode"] == "advisory"
    assert options["thermal_actuation_mode"] == "advisory"


def test_morning_low_soc_strong_forecast_keeps_battery_priority() -> None:
    decision = decide(
        base_inputs(
            now=dt(9),
            battery_soc=54,
            battery_power_w=-4900,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=19,
            pv_power_now_w=7400,
        ),
        EnergyManagerSettings(thermal_control_enabled=True),
    )

    assert decision.forecast_full_override_active
    assert not decision.thermal_allowed
    assert decision.thermal_policy_state == "battery_priority"
    assert "battery_priority" in decision.battery_priority_reason


def test_morning_preheat_is_separate_from_solar_soak() -> None:
    decision = decide(
        base_inputs(
            now=dt(8),
            battery_soc=45,
            battery_power_w=0,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=25,
            heat_loads=[
                HeatLoadState(
                    name="Bedroom heat pump",
                    priority=1,
                    is_on=False,
                    current_temp=16,
                    supports_heating=True,
                    estimated_load_w=1800,
                ),
                HeatLoadState(name="Office heat pump", priority=2, current_temp=16, supports_heating=True),
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True),
    )

    assert decision.morning_preheat_allowed
    assert decision.thermal_action == "morning_preheat"
    assert decision.thermal_load_to_add == "Bedroom heat pump"
    assert decision.thermal_target_temperature == 21.0
    assert decision.thermal_target_fan_mode == "low"
    assert decision.thermal_lease_reason == "morning_preheat"


def test_morning_preheat_blocked_by_soc_floor() -> None:
    decision = decide(
        base_inputs(
            now=dt(8),
            battery_soc=25,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=25,
            heat_loads=[HeatLoadState(name="Bedroom heat pump", priority=1, current_temp=16, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True),
    )

    assert not decision.morning_preheat_allowed
    assert "SOC 25" in decision.morning_preheat_reason


def test_paid_grid_avoidance_lowers_active_reserve_to_use_battery() -> None:
    decision = decide(
        base_inputs(
            now=dt(7, 30),
            battery_soc=35,
            battery_power_w=300,
            grid_power_w=800,
            pv_power_now_w=100,
            forecast_tomorrow_kwh=35,
        ),
        EnergyManagerSettings(),
    )

    assert decision.paid_grid_avoidance_required
    assert decision.forecast_drain_blocked
    assert decision.paid_time_floor_soc == 12
    assert decision.active_reserve_target_soc == 12
    assert decision.expected_action == "paid_grid_avoidance"
    assert "lowering active reserve" in decision.paid_time_reserve_reason


def test_paid_grid_avoidance_uses_grace_filtered_import() -> None:
    decision = decide(
        base_inputs(
            now=dt(7, 30),
            battery_soc=35,
            battery_power_w=300,
            grid_power_w=800,
            paid_grid_import_w=0,
            pv_power_now_w=100,
            forecast_tomorrow_kwh=35,
        ),
        EnergyManagerSettings(),
    )

    assert not decision.paid_grid_avoidance_required
    assert decision.paid_grid_import_w == 0


def test_paid_grid_avoidance_triggers_after_import_grace() -> None:
    decision = decide(
        base_inputs(
            now=dt(7, 30),
            battery_soc=35,
            battery_power_w=300,
            grid_power_w=800,
            paid_grid_import_w=800,
            pv_power_now_w=100,
            forecast_tomorrow_kwh=35,
        ),
        EnergyManagerSettings(),
    )

    assert decision.paid_grid_avoidance_required
    assert decision.paid_grid_import_w == 800


def test_paid_grid_avoidance_does_not_preserve_when_soc_near_floor() -> None:
    decision = decide(
        base_inputs(
            now=dt(18),
            battery_soc=12.5,
            battery_power_w=0,
            grid_power_w=800,
            pv_power_now_w=0,
            forecast_tomorrow_kwh=35,
        ),
        EnergyManagerSettings(),
    )

    assert not decision.paid_grid_avoidance_required
    assert decision.active_reserve_target_soc == 12
    assert "unavoidable" in decision.paid_time_reserve_reason


def test_paid_grid_avoidance_relaxes_after_solar_arrives() -> None:
    decision = decide(
        base_inputs(
            now=dt(9),
            battery_soc=55,
            battery_power_w=-2500,
            grid_power_w=0,
            pv_power_now_w=5000,
            forecast_tomorrow_kwh=35,
        ),
        EnergyManagerSettings(),
    )

    assert decision.solar_arrived
    assert not decision.paid_grid_avoidance_required


def test_unowned_emergency_shed_candidate_ignores_never_emergency_shed_load() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_power_w=3000,
            any_solar_owned_heat_load_on=False,
            heat_loads=[
                HeatLoadState(
                    name="Dining",
                    priority=1,
                    is_on=True,
                    hvac_mode="heat",
                    target_temp=27,
                    never_emergency_shed=True,
                ),
                HeatLoadState(
                    name="Office",
                    priority=2,
                    is_on=True,
                    hvac_mode="heat",
                    target_temp=27,
                ),
            ],
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            thermal_shed_discharge_w=500,
            thermal_emergency_shed_w=2500,
            shed_unowned_managed_loads_on_battery_discharge=True,
        ),
    )

    assert decision.thermal_should_emergency_shed
    assert decision.thermal_load_to_normalise == "Office"


def test_energy_budget_blocks_soak_when_battery_target_not_reachable() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=80,
            forecast_remaining_today_kwh=5,
            forecast_tomorrow_kwh=35,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=23, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, daily_battery_target_soc=100, battery_capacity_kwh=30),
    )

    assert decision.battery_kwh_needed_to_target and decision.battery_kwh_needed_to_target > 6
    assert decision.discretionary_energy_budget_kwh < 0
    assert not decision.battery_target_reachable_today
    assert not decision.thermal_allowed
    assert decision.thermal_policy_state == "battery_priority"


def test_energy_budget_allows_one_load_when_surplus_is_real() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=80,
            forecast_remaining_today_kwh=22,
            forecast_tomorrow_kwh=35,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=23, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, daily_battery_target_soc=100, battery_capacity_kwh=30),
    )

    assert decision.discretionary_energy_budget_kwh > 0
    assert decision.battery_target_reachable_today
    assert decision.thermal_allowed
    assert decision.thermal_load_to_add == "Office"


def test_positive_budget_still_requires_thermal_start_gate() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=50,
            battery_power_w=0,
            forecast_remaining_today_kwh=30,
            forecast_tomorrow_kwh=20,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=23, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            daily_battery_target_soc=80,
            thermal_start_min_soc=80,
            thermal_start_min_charge_w=6000,
        ),
    )

    assert decision.discretionary_energy_budget_kwh is not None
    assert decision.discretionary_energy_budget_kwh > 0
    assert not decision.thermal_allowed
    assert decision.thermal_action == "none"
    assert "thermal_start_min_soc" in decision.thermal_action_reason


def test_charge_rate_can_satisfy_thermal_start_gate_when_budget_fits() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=50,
            battery_power_w=-7000,
            forecast_remaining_today_kwh=30,
            forecast_tomorrow_kwh=20,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=23, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            daily_battery_target_soc=80,
            thermal_start_min_soc=80,
            thermal_start_min_charge_w=6000,
        ),
    )

    assert decision.thermal_allowed
    assert decision.thermal_action == "add_one"


def test_budget_positive_but_too_small_for_candidate_load_blocks_add() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=95,
            forecast_remaining_today_kwh=15,
            forecast_tomorrow_kwh=35,
            heat_loads=[HeatLoadState(name="Dining", priority=1, current_temp=23, estimated_load_w=6000)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, daily_battery_target_soc=100, battery_capacity_kwh=30),
    )

    assert decision.discretionary_energy_budget_kwh > 0
    assert decision.thermal_load_to_add is None
    assert not decision.thermal_allowed


def test_underfloor_floor_slab_uses_per_load_comfort_threshold() -> None:
    comfortable = decide(
        base_inputs(
            now=dt(8),
            battery_soc=80,
            forecast_remaining_today_kwh=20,
            heat_loads=[
                HeatLoadState(
                    name="Bathroom underfloor",
                    priority=1,
                    current_temp=11.5,
                    load_type="underfloor",
                    comfort_sensor_type="floor_slab",
                    comfort_min_temp=9,
                    comfort_target_temp=12,
                    normal_target_temp=12,
                    allow_solar_soak=False,
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True),
    )
    cold = decide(
        base_inputs(
            now=dt(8),
            battery_soc=80,
            forecast_remaining_today_kwh=20,
            heat_loads=[
                HeatLoadState(
                    name="Bathroom underfloor",
                    priority=1,
                    current_temp=7,
                    load_type="underfloor",
                    comfort_sensor_type="floor_slab",
                    comfort_min_temp=9,
                    comfort_target_temp=12,
                    normal_target_temp=12,
                    allow_solar_soak=False,
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True),
    )

    assert not comfortable.comfort_heat_allowed
    assert not cold.comfort_heat_allowed
    assert cold.underfloor_comfort_allowed
    assert cold.thermal_target_temperature == 12
    assert cold.thermal_lease_reason == "scheduled_underfloor_comfort"


def test_underfloor_evening_schedule_heats_to_12c() -> None:
    decision = decide(
        base_inputs(
            now=dt(18),
            battery_soc=60,
            grid_power_w=0,
            forecast_remaining_today_kwh=20,
            heat_loads=[
                HeatLoadState(
                    name="Bathroom underfloor",
                    priority=1,
                    current_temp=8,
                    load_type="floor_underfloor",
                    comfort_sensor_type="floor_slab",
                    comfort_min_temp=9,
                    comfort_target_temp=12,
                    normal_target_temp=12,
                    allow_solar_soak=False,
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True),
    )

    assert decision.underfloor_comfort_allowed
    assert decision.thermal_action == "underfloor_comfort"
    assert decision.thermal_target_temperature == 12
    assert "evening schedule active" in decision.underfloor_reason


def test_underfloor_outside_schedule_is_blocked() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=60,
            forecast_remaining_today_kwh=20,
            heat_loads=[
                HeatLoadState(
                    name="Bathroom underfloor",
                    priority=1,
                    current_temp=8,
                    load_type="floor_underfloor",
                    comfort_min_temp=9,
                    comfort_target_temp=12,
                    allow_solar_soak=False,
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True),
    )

    assert not decision.underfloor_comfort_allowed
    assert "outside comfort window" in decision.underfloor_reason


def test_underfloor_paid_grid_avoidance_blocks_unless_allowed() -> None:
    base = base_inputs(
        now=dt(18),
        battery_soc=31,
        grid_power_w=800,
        battery_power_w=500,
        forecast_remaining_today_kwh=1,
        heat_loads=[
            HeatLoadState(
                name="Bathroom underfloor",
                priority=1,
                current_temp=8,
                load_type="floor_underfloor",
                comfort_min_temp=9,
                comfort_target_temp=12,
                allow_solar_soak=False,
            )
        ],
    )
    blocked = decide(base, EnergyManagerSettings(thermal_control_enabled=True, underfloor_min_soc=30))
    allowed = decide(
        base,
        EnergyManagerSettings(
            thermal_control_enabled=True,
            underfloor_min_soc=30,
            underfloor_allow_paid_grid=True,
            underfloor_max_grid_import_w=1000,
        ),
    )

    assert blocked.paid_grid_avoidance_required
    assert not blocked.underfloor_comfort_allowed
    assert "paid grid avoidance active" in blocked.underfloor_reason
    assert allowed.underfloor_comfort_allowed


def test_underfloor_require_home_blocks_when_occupancy_is_away() -> None:
    decision = decide(
        base_inputs(
            now=dt(18),
            battery_soc=60,
            grid_power_w=0,
            home_occupied=False,
            forecast_remaining_today_kwh=20,
            heat_loads=[
                HeatLoadState(
                    name="Bathroom underfloor",
                    priority=1,
                    current_temp=8,
                    load_type="floor_underfloor",
                    comfort_min_temp=9,
                    comfort_target_temp=12,
                    allow_solar_soak=False,
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, underfloor_require_home=True),
    )

    assert not decision.underfloor_comfort_allowed
    assert "nobody home" in decision.underfloor_reason


def test_underfloor_require_home_allows_schedule_when_occupancy_unconfigured() -> None:
    decision = decide(
        base_inputs(
            now=dt(18),
            battery_soc=60,
            grid_power_w=0,
            home_occupied=None,
            forecast_remaining_today_kwh=20,
            heat_loads=[
                HeatLoadState(
                    name="Bathroom underfloor",
                    priority=1,
                    current_temp=8,
                    load_type="floor_underfloor",
                    comfort_min_temp=9,
                    comfort_target_temp=12,
                    allow_solar_soak=False,
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, underfloor_require_home=True),
    )

    assert decision.underfloor_comfort_allowed


def test_underfloor_soc_floor_blocks_schedule() -> None:
    decision = decide(
        base_inputs(
            now=dt(18),
            battery_soc=32,
            forecast_remaining_today_kwh=20,
            heat_loads=[
                HeatLoadState(
                    name="Bathroom underfloor",
                    priority=1,
                    current_temp=8,
                    load_type="floor_underfloor",
                    comfort_min_temp=9,
                    comfort_target_temp=12,
                    allow_solar_soak=False,
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, underfloor_min_soc=40),
    )

    assert not decision.underfloor_comfort_allowed
    assert "SOC 32" in decision.underfloor_reason


def test_underfloor_preheat_uses_budget_before_evening_window() -> None:
    decision = decide(
        base_inputs(
            now=dt(15),
            battery_soc=95,
            forecast_remaining_today_kwh=20,
            heat_loads=[
                HeatLoadState(
                    name="Bathroom underfloor",
                    priority=1,
                    current_temp=8,
                    estimated_load_w=800,
                    load_type="floor_underfloor",
                    comfort_min_temp=9,
                    comfort_target_temp=12,
                    allow_solar_soak=False,
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=True),
    )

    assert decision.underfloor_comfort_allowed
    assert decision.underfloor_current_window == "evening_preheat"
    assert decision.thermal_target_temperature == 12


def test_negative_budget_blocks_solar_soak_allowed() -> None:
    decision = decide(
        base_inputs(
            now=dt(15),
            battery_soc=91,
            forecast_remaining_today_kwh=1.82,
            forecast_tomorrow_kwh=35,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, daily_battery_target_soc=100, battery_capacity_kwh=30),
    )

    assert decision.discretionary_energy_budget_kwh < 0
    assert not decision.battery_target_reachable_today
    assert not decision.solar_soak_allowed
    assert not decision.full_send_soak_allowed
    assert not decision.thermal_allowed
    assert decision.thermal_policy_state == "battery_priority"
    assert "thermal_allowed=true" not in decision.thermal_action_reason


def test_budget_too_small_for_smallest_load_blocks_solar_soak_allowed() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=95,
            forecast_remaining_today_kwh=15,
            forecast_tomorrow_kwh=35,
            heat_loads=[HeatLoadState(name="Dining", priority=1, current_temp=23, estimated_load_w=6000)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, daily_battery_target_soc=100, battery_capacity_kwh=30),
    )

    assert decision.discretionary_energy_budget_kwh > 0
    assert decision.thermal_load_to_add is None
    assert not decision.solar_soak_allowed
    assert not decision.thermal_allowed


def test_paid_grid_avoidance_blocks_solar_soak_even_with_positive_budget() -> None:
    decision = decide(
        base_inputs(
            now=dt(18),
            battery_soc=31,
            grid_power_w=800,
            forecast_remaining_today_kwh=30,
            forecast_tomorrow_kwh=35,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True),
    )

    assert decision.paid_grid_avoidance_required
    assert not decision.solar_soak_allowed
    assert not decision.thermal_allowed


def test_battery_discharge_shed_overrides_positive_budget() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=95,
            battery_power_w=700,
            forecast_remaining_today_kwh=30,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20, estimated_load_w=1800)],
        ),
        EnergyManagerSettings(thermal_control_enabled=True, thermal_shed_discharge_w=500),
    )

    assert decision.thermal_should_shed
    assert not decision.solar_soak_allowed
    assert not decision.thermal_allowed


def test_underfloor_diagnostic_uses_underfloor_thresholds_not_room_air_defaults() -> None:
    inputs = base_inputs(
        now=dt(15),
        battery_soc=91,
        forecast_remaining_today_kwh=1.82,
        heat_loads=[
            HeatLoadState(
                name="Bathroom underfloor",
                priority=1,
                current_temp=11.5,
                target_temp=12,
                load_type="floor_underfloor",
                comfort_sensor_type="floor_slab",
                allow_solar_soak=False,
            )
        ],
    )
    settings = EnergyManagerSettings(thermal_control_enabled=True)
    decision = decide(inputs, settings)
    diagnostic = thermal_load_diagnostic(inputs.heat_loads[0], settings, inputs, decision)

    assert diagnostic.attributes["comfort_sensor_type"] == "floor_slab"
    assert diagnostic.attributes["comfort_min_temp"] == 9.0
    assert diagnostic.attributes["comfort_target_temp"] == 12.0
    assert diagnostic.attributes["normal_target_temperature"] == 12.0
    assert diagnostic.attributes["needs_soak"] is False
    assert diagnostic.state in {"satisfied", "idle"}


def test_overnight_dining_comfort_uses_spare_soc_headroom() -> None:
    dining = HeatLoadState(
        name="Dining/living heat pump",
        slug="dining",
        priority=1,
        current_temp=17.0,
        estimated_load_w=1200,
        load_type="room_heat_pump",
    )

    decision = decide(
        base_inputs(now=dt(23), battery_soc=80, forecast_tomorrow_kwh=35, heat_loads=[dining]),
        EnergyManagerSettings(thermal_control_enabled=True, overnight_dining_comfort_enabled=True, battery_capacity_kwh=30),
    )

    assert decision.morning_start_soc_target == 30
    assert decision.overnight_dining_comfort_allowed
    assert decision.thermal_action == "overnight_dining_comfort"
    assert decision.thermal_load_to_add == "Dining/living heat pump"
    assert decision.thermal_lease_reason == "overnight_dining_comfort"
    assert decision.thermal_target_temperature == 20
    assert decision.projected_soc_07_with_overnight_dining >= decision.morning_start_soc_target + 8


def test_overnight_dining_comfort_blocks_when_7am_target_at_risk() -> None:
    dining = HeatLoadState(
        name="Dining/living heat pump",
        slug="dining",
        priority=1,
        current_temp=17.0,
        estimated_load_w=1200,
        load_type="room_heat_pump",
    )

    decision = decide(
        base_inputs(now=dt(23), battery_soc=45, forecast_tomorrow_kwh=35, heat_loads=[dining]),
        EnergyManagerSettings(thermal_control_enabled=True, overnight_dining_comfort_enabled=True, battery_capacity_kwh=30),
    )

    assert not decision.overnight_dining_comfort_allowed
    assert "projected 07:00 SOC" in decision.overnight_dining_comfort_reason
    assert decision.thermal_action == "none"
    assert decision.thermal_load_to_add is None
    assert not decision.comfort_heat_allowed


def test_overnight_dining_comfort_running_can_drain_until_7am_margin() -> None:
    dining = HeatLoadState(
        name="Dining/living heat pump",
        slug="dining",
        priority=1,
        current_temp=18.0,
        estimated_load_w=1200,
        load_type="room_heat_pump",
        is_on=True,
        solar_owned=True,
        lease_reason="overnight_dining_comfort",
    )
    settings = EnergyManagerSettings(
        thermal_control_enabled=True,
        overnight_dining_comfort_enabled=True,
        battery_capacity_kwh=30,
        thermal_shed_discharge_w=500,
    )

    safe = decide(
        base_inputs(
            now=dt(23),
            battery_soc=80,
            battery_power_w=1200,
            essential_power_w=2200,
            forecast_tomorrow_kwh=35,
            any_solar_owned_heat_load_on=True,
            heat_loads=[dining],
        ),
        settings,
    )
    unsafe = decide(
        base_inputs(
            now=dt(23),
            battery_soc=45,
            battery_power_w=1200,
            essential_power_w=2200,
            forecast_tomorrow_kwh=35,
            any_solar_owned_heat_load_on=True,
            heat_loads=[dining],
        ),
        settings,
    )

    assert not safe.thermal_should_shed
    assert not safe.overnight_protection_required
    assert unsafe.overnight_protection_required
    assert unsafe.thermal_should_shed
    assert unsafe.thermal_load_to_shed == "Dining/living heat pump"
    assert unsafe.thermal_load_to_normalise == "Dining/living heat pump"


def test_overnight_dining_comfort_is_opt_in() -> None:
    dining = HeatLoadState(
        name="Dining/living heat pump",
        slug="dining",
        priority=1,
        current_temp=17.0,
        estimated_load_w=1200,
        load_type="room_heat_pump",
    )

    decision = decide(
        base_inputs(now=dt(23), battery_soc=80, forecast_tomorrow_kwh=35, heat_loads=[dining]),
        EnergyManagerSettings(thermal_control_enabled=True, battery_capacity_kwh=30),
    )

    assert not decision.overnight_dining_comfort_allowed
    assert decision.overnight_dining_comfort_reason == "overnight_dining_blocked: disabled"
    assert decision.thermal_action == "none"
