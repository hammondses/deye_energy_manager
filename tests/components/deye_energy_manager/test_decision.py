"""Tests for the Deye Energy Manager decision engine."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.deye_energy_manager import decision as decision_module
from custom_components.deye_energy_manager.const import DEFAULT_HEAT_LOADS
from custom_components.deye_energy_manager.decision import active_slot, build_deye_plan, cheap_grid_mirror_programs, decide, deye_capacity_percent, deye_plan_conflict_reason, deye_write_thrash_detected, disabled_programs, inverter_cooling_recommendation, program_ranges, tariff_window, thermal_load_diagnostic, thermal_load_diagnostics, thermal_shed_action, thermal_soak_action
from custom_components.deye_energy_manager.decision import resolve_soc_value, resolved_ev_power_w
from custom_components.deye_energy_manager.migration import migrate_options, migrate_porsche_entity_map
from custom_components.deye_energy_manager.models import DeyePlan, EnergyManagerInputs, EnergyManagerSettings, HeatLoadState
from custom_components.deye_energy_manager.repairs import repair_issue_definitions

TZ = ZoneInfo("Pacific/Auckland")


def dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 1, hour, minute, tzinfo=TZ)


def test_ev_power_falls_back_to_current_times_voltage() -> None:
    assert resolved_ev_power_w(None, 31.0, 240.0) == 7440.0
    assert resolved_ev_power_w(7100.0, 31.0, 240.0) == 7100.0
    assert resolved_ev_power_w(None, None, 240.0) is None


def test_missing_legacy_cayenne_entities_migrate_to_available_taycan_entities() -> None:
    entity_map = {
        "porsche_soc": "sensor.cayenne_e_hybrid_my24_state_of_charge",
        "porsche_charging_status": "sensor.cayenne_e_hybrid_my24_charging_status",
        "porsche_charging_ends": "sensor.cayenne_e_hybrid_my24_charging_ends",
        "porsche_charging_power": "sensor.cayenne_e_hybrid_my24_charging_power",
    }
    available = {
        "sensor.taycan_4s_state_of_charge",
        "sensor.taycan_4s_charging_status",
        "sensor.taycan_4s_charging_ends",
        "sensor.taycan_4s_charging_power",
    }

    migrated, changed = migrate_porsche_entity_map(entity_map, available)

    assert changed
    assert migrated["porsche_soc"] == "sensor.taycan_4s_state_of_charge"
    assert migrated["porsche_charging_status"] == "sensor.taycan_4s_charging_status"
    assert migrated["porsche_charging_ends"] == "sensor.taycan_4s_charging_ends"
    assert migrated["porsche_charging_power"] == "sensor.taycan_4s_charging_power"


def test_available_legacy_cayenne_entity_mapping_is_preserved() -> None:
    entity_map = {"porsche_soc": "sensor.cayenne_e_hybrid_my24_state_of_charge"}
    migrated, changed = migrate_porsche_entity_map(
        entity_map,
        {
            "sensor.cayenne_e_hybrid_my24_state_of_charge",
            "sensor.taycan_4s_state_of_charge",
        },
    )

    assert not changed
    assert migrated == entity_map


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


def test_inverter_cooling_curve_uses_highest_power_channel() -> None:
    recommendation = inverter_cooling_recommendation(
        base_inputs(
            battery_power_w=-6000,
            essential_power_w=2000,
            inverter_pv_power_w=10000,
            inverter_ac_power_w=3000,
            inverter_ac_temperature_c=43,
            cooling_temperature_valid=True,
            cooling_fan_percentage=40,
        ),
        EnergyManagerSettings(cooling_target_temp_c=43),
    )

    assert recommendation.throughput_w == 10000
    assert recommendation.baseline_pct == 50
    assert recommendation.temperature_trim_pct == 0
    assert recommendation.raw_required_pct == 50
    assert recommendation.recommended_pct == 45


def test_inverter_cooling_uses_feedback_steps_except_when_load_falls() -> None:
    settings = EnergyManagerSettings(cooling_target_temp_c=43)
    decrease = inverter_cooling_recommendation(
        base_inputs(
            essential_power_w=1000,
            inverter_ac_temperature_c=35,
            cooling_temperature_valid=True,
            cooling_fan_percentage=50,
        ),
        settings,
    )
    increase = inverter_cooling_recommendation(
        base_inputs(
            essential_power_w=1000,
            inverter_pv_power_w=10000,
            inverter_ac_temperature_c=43,
            cooling_temperature_valid=True,
            cooling_fan_percentage=10,
        ),
        settings,
    )
    stable = inverter_cooling_recommendation(
        base_inputs(
            inverter_pv_power_w=10000,
            inverter_ac_temperature_c=43,
            cooling_temperature_valid=True,
            cooling_fan_percentage=35,
            cooling_temperature_trend_c_per_min=0,
        ),
        settings,
    )
    rising = inverter_cooling_recommendation(
        base_inputs(
            inverter_pv_power_w=10000,
            inverter_ac_temperature_c=43,
            cooling_temperature_valid=True,
            cooling_fan_percentage=35,
            cooling_temperature_trend_c_per_min=0.2,
        ),
        settings,
    )
    steady_at_target = inverter_cooling_recommendation(
        base_inputs(
            essential_power_w=1000,
            inverter_ac_temperature_c=43,
            cooling_temperature_valid=True,
            cooling_fan_percentage=50,
            cooling_temperature_trend_c_per_min=0,
        ),
        settings,
    )
    load_fell = inverter_cooling_recommendation(
        base_inputs(
            essential_power_w=1000,
            inverter_ac_temperature_c=43,
            cooling_temperature_valid=True,
            cooling_fan_percentage=50,
            cooling_temperature_trend_c_per_min=0,
            cooling_load_change_w=-1000,
        ),
        settings,
    )
    sunny_dip = inverter_cooling_recommendation(
        base_inputs(
            inverter_pv_power_w=9000,
            inverter_ac_temperature_c=40,
            cooling_temperature_valid=True,
            cooling_fan_percentage=70,
            cooling_temperature_trend_c_per_min=0,
            cooling_load_change_w=-1000,
        ),
        settings,
    )

    assert decrease.raw_required_pct == 10
    assert decrease.recommended_pct == 45
    assert increase.raw_required_pct == 50
    assert increase.recommended_pct == 15
    assert stable.recommended_pct == 35
    assert rising.recommended_pct == 40
    assert steady_at_target.recommended_pct == 50
    assert load_fell.recommended_pct == 20
    assert sunny_dip.raw_required_pct == 35
    assert sunny_dip.recommended_pct == 65


def test_inverter_cooling_emergency_and_stale_temperature_are_safe() -> None:
    emergency = inverter_cooling_recommendation(
        base_inputs(
            inverter_ac_temperature_c=48,
            cooling_temperature_valid=True,
            cooling_fan_percentage=20,
        ),
        EnergyManagerSettings(),
    )
    stale = inverter_cooling_recommendation(
        base_inputs(
            essential_power_w=100,
            inverter_ac_temperature_c=30,
            cooling_temperature_valid=False,
            cooling_fan_percentage=20,
        ),
        EnergyManagerSettings(),
    )

    assert emergency.raw_required_pct == 100
    assert emergency.recommended_pct == 25
    assert stale.raw_required_pct == 50
    assert "failsafe" in stale.reason


def test_inverter_cooling_turns_off_only_when_cool_and_idle() -> None:
    recommendation = inverter_cooling_recommendation(
        base_inputs(
            essential_power_w=100,
            inverter_ac_power_w=100,
            inverter_ac_temperature_c=30,
            cooling_temperature_valid=True,
            cooling_fan_percentage=5,
        ),
        EnergyManagerSettings(),
    )

    assert recommendation.raw_required_pct == 0
    assert recommendation.recommended_pct == 0


def test_inverter_cooling_falling_temperature_unwinds_and_avoids_load_flap() -> None:
    settings = EnergyManagerSettings()
    unwinding = inverter_cooling_recommendation(
        base_inputs(
            inverter_pv_power_w=7000,
            inverter_ac_temperature_c=45,
            cooling_temperature_valid=True,
            cooling_fan_percentage=95,
            cooling_temperature_trend_c_per_min=-0.2,
        ),
        settings,
    )
    overnight = inverter_cooling_recommendation(
        base_inputs(
            inverter_pv_power_w=3000,
            inverter_ac_temperature_c=35,
            cooling_temperature_valid=True,
            cooling_fan_percentage=10,
            cooling_temperature_trend_c_per_min=-0.2,
            cooling_load_change_w=1000,
        ),
        settings,
    )

    assert unwinding.recommended_pct == 90
    assert overnight.raw_required_pct == 15
    assert overnight.recommended_pct == 10


def test_inverter_cooling_minimum_hunt_steps_down_only_after_stable_window() -> None:
    settings = EnergyManagerSettings(cooling_minimum_hunt_enabled=True)
    waiting = inverter_cooling_recommendation(
        base_inputs(
            inverter_pv_power_w=7000,
            inverter_ac_temperature_c=44,
            cooling_temperature_valid=True,
            cooling_fan_percentage=40,
            cooling_temperature_trend_c_per_min=0.0,
            cooling_hunt_step_ready=False,
        ),
        settings,
    )
    probing = inverter_cooling_recommendation(
        base_inputs(
            inverter_pv_power_w=7000,
            inverter_ac_temperature_c=44,
            cooling_temperature_valid=True,
            cooling_fan_percentage=40,
            cooling_temperature_trend_c_per_min=0.0,
            cooling_hunt_step_ready=True,
        ),
        settings,
    )

    assert waiting.recommended_pct == 40
    assert probing.recommended_pct == 35
    assert "minimum hunt" in probing.reason


def test_inverter_cooling_minimum_hunt_resets_stale_high_fan_when_cold() -> None:
    recommendation = inverter_cooling_recommendation(
        base_inputs(
            battery_power_w=3081,
            inverter_ac_temperature_c=19.15,
            cooling_temperature_valid=True,
            cooling_fan_percentage=70,
            cooling_temperature_trend_c_per_min=-0.05,
            cooling_hunt_step_ready=False,
        ),
        EnergyManagerSettings(cooling_minimum_hunt_enabled=True),
    )

    assert recommendation.raw_required_pct == 15
    assert recommendation.recommended_pct == 10
    assert recommendation.reason == "minimum hunt: far below target, use minimum active fan"


def test_inverter_cooling_minimum_hunt_recovers_on_rise_or_load_jump() -> None:
    settings = EnergyManagerSettings(cooling_minimum_hunt_enabled=True)
    rising = inverter_cooling_recommendation(
        base_inputs(
            inverter_pv_power_w=7000,
            inverter_ac_temperature_c=44,
            cooling_temperature_valid=True,
            cooling_fan_percentage=20,
            cooling_temperature_trend_c_per_min=0.2,
        ),
        settings,
    )
    load_jump = inverter_cooling_recommendation(
        base_inputs(
            inverter_pv_power_w=7000,
            inverter_ac_temperature_c=44,
            cooling_temperature_valid=True,
            cooling_fan_percentage=20,
            cooling_temperature_trend_c_per_min=-0.1,
            cooling_load_change_w=1000,
        ),
        settings,
    )

    assert rising.recommended_pct == 25
    assert load_jump.recommended_pct == 25


def test_cooling_protection_requires_sustained_hot_fan_failure() -> None:
    settings = EnergyManagerSettings(
        cooling_fan_failure_protection_enabled=True,
        cooling_fan_failure_temp_c=50,
        cooling_fan_failure_delay_min=5,
    )
    pending = decide(
        base_inputs(
            inverter_ac_temperature_c=51,
            cooling_temperature_valid=True,
            cooling_fan_healthy=False,
            cooling_protection_condition_minutes=4.9,
        ),
        settings,
    )
    tripped = decide(
        base_inputs(
            inverter_ac_temperature_c=51,
            cooling_temperature_valid=True,
            cooling_fan_healthy=False,
            cooling_protection_condition_minutes=5,
        ),
        settings,
    )
    cool_failure = decide(
        base_inputs(
            inverter_ac_temperature_c=49,
            cooling_temperature_valid=True,
            cooling_fan_healthy=False,
            cooling_protection_condition_minutes=20,
        ),
        settings,
    )

    assert not pending.cooling_inverter_protection_required
    assert tripped.cooling_inverter_protection_required
    assert tripped.cooling_inverter_protection_active
    assert not cool_failure.cooling_inverter_protection_required


def test_cooling_diagnostics_identify_regime_and_stable_samples() -> None:
    stable = decide(
        base_inputs(
            inverter_pv_power_w=6000,
            inverter_ac_power_w=5500,
            grid_power_w=-4000,
            export_power_w=4000,
            inverter_ac_temperature_c=42,
            cooling_temperature_valid=True,
            cooling_fan_percentage=10,
            cooling_temperature_trend_c_per_min=0.0,
        )
    )

    assert stable.cooling_load_regime == "pv_export"
    assert stable.cooling_calibration_state == "stable"


def test_time_slots_and_tariff_windows() -> None:
    cases = [
        (dt(20, 52), "Prog4", "peak"),
        (dt(20, 57), "Prog5", "peak"),
        (dt(22), "Prog6", "cheap_grid"),
        (dt(3), "Prog6", "cheap_grid"),
        (dt(5), "Prog6", "cheap_grid"),
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
    assert ranges[3]["start"] == "20:50"
    assert ranges[3]["end"] == "20:55"
    assert not ranges[3]["wraps_midnight"]
    assert ranges[5]["program"] == "Prog6"
    assert ranges[5]["start"] == "21:00"
    assert ranges[5]["end"] == "07:00"
    assert ranges[5]["wraps_midnight"]
    assert disabled_programs(EnergyManagerSettings()) == []
    assert active_slot(dt(8)) == "Prog1"
    assert active_slot(dt(14)) == "Prog2"
    assert active_slot(dt(18)) == "Prog3"
    assert active_slot(dt(23)) == "Prog6"
    assert active_slot(dt(3)) == "Prog6"
    assert cheap_grid_mirror_programs(EnergyManagerSettings(), "Prog6") == ()


def test_cheap_grid_plan_targets_prog6_owned_night_row() -> None:
    settings = EnergyManagerSettings(
        deye_control_enabled=True,
        grid_charge_control_enabled=True,
        ev_control_enabled=True,
        cheap_grid_charge_enabled=True,
    )

    decision = decide(base_inputs(now=dt(22), forecast_tomorrow_kwh=23, battery_soc=18), settings)
    plan = build_deye_plan(decision, settings)

    assert decision.active_slot == "Prog6"
    assert decision.grid_charge_required
    assert plan.capacity_targets == {"Prog6": 30}
    assert plan.charge_modes == {"Prog6": "Allow Grid"}
    assert plan.power_targets == {"Prog6": 12000}


def test_cheap_grid_plan_mirrors_legacy_duplicate_boundary_rows() -> None:
    settings = EnergyManagerSettings(
        deye_control_enabled=True,
        grid_charge_control_enabled=True,
        ev_control_enabled=True,
        cheap_grid_charge_enabled=True,
        deye_program_start_times=("07:00", "13:00", "17:00", "21:00", "07:00", "07:00"),
    )

    decision = decide(base_inputs(now=dt(22), forecast_tomorrow_kwh=23, battery_soc=18), settings)
    plan = build_deye_plan(decision, settings)

    assert decision.active_slot == "Prog4"
    assert cheap_grid_mirror_programs(settings, "Prog4") == ("Prog5", "Prog6")
    for slot in ("Prog4", "Prog5", "Prog6"):
        assert plan.capacity_targets[slot] == 30
        assert plan.charge_modes[slot] == "Allow Grid"
        assert plan.power_targets[slot] == 12000


def test_paid_time_plan_does_not_mirror_duplicate_boundary_rows() -> None:
    settings = EnergyManagerSettings(deye_control_enabled=True, grid_charge_control_enabled=True)

    decision = decide(base_inputs(now=dt(8), battery_soc=60), settings)
    plan = build_deye_plan(decision, settings)

    assert decision.active_slot == "Prog1"
    assert set(plan.capacity_targets) == {"Prog1"}
    assert set(plan.charge_modes) == {"Prog1"}


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
    assert decision.active_slot == "Prog6"
    assert decision.cheap_grid_preserve_required
    assert 30 <= decision.morning_target_soc <= 35
    assert decision.cheap_grid_mode == "preserve"
    assert not decision.grid_charge_required
    assert decision.active_reserve_target_soc >= decision.morning_target_soc
    assert "using grid for house load" in decision.cheap_grid_reason


def test_armed_bedroom_uses_reserve_only_and_suppresses_battery_topup() -> None:
    settings = EnergyManagerSettings(
        bedroom_night_heating_armed=True,
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
    )
    decision = decide(base_inputs(now=dt(22), battery_soc=10, forecast_tomorrow_kwh=20), settings)
    plan = build_deye_plan(decision, settings)

    assert decision.bedroom_night_heating_active
    assert not decision.bedroom_night_heating_should_disarm
    assert decision.cheap_grid_preserve_required
    assert not decision.cheap_grid_topup_required
    assert not decision.grid_charge_required
    assert plan.charge_modes[decision.active_slot] == "No Grid or Gen"
    assert not plan.grid_charge_enabled


def test_armed_bedroom_disarms_on_bad_morning_or_noon_cutoff() -> None:
    settings = EnergyManagerSettings(bedroom_night_heating_armed=True)

    bad_morning = decide(base_inputs(now=dt(9), battery_soc=20, forecast_tomorrow_kwh=20), settings)
    assert bad_morning.bedroom_night_heating_should_disarm
    assert "09:00 recovery unsafe" in bad_morning.bedroom_night_heating_reason

    good_morning = decide(base_inputs(now=dt(9), battery_soc=80, forecast_tomorrow_kwh=20), settings)
    assert good_morning.bedroom_night_heating_active

    paid_import = decide(
        base_inputs(now=dt(7, 30), battery_soc=80, paid_grid_import_w=600, forecast_tomorrow_kwh=20),
        settings,
    )
    assert paid_import.bedroom_night_heating_should_disarm
    assert "paid grid import" in paid_import.bedroom_night_heating_reason

    noon = decide(base_inputs(now=dt(12), battery_soc=80), settings)
    assert noon.bedroom_night_heating_should_disarm
    assert "12:00 cutoff" in noon.bedroom_night_heating_reason


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
    assert plan.charge_modes["Prog6"] == "Allow Grid"
    assert plan.capacity_targets["Prog6"] == decision.morning_target_soc
    assert "Prog1" not in plan.capacity_targets
    assert "Prog2" not in plan.capacity_targets
    assert "Prog3" not in plan.capacity_targets
    assert "Prog4" not in plan.capacity_targets
    assert "Prog5" not in plan.capacity_targets
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
    assert plan.charge_modes["Prog6"] == "No Grid or Gen"
    assert plan.capacity_targets["Prog6"] == decision.morning_target_soc
    assert "Prog1" not in plan.capacity_targets
    assert "Prog2" not in plan.capacity_targets
    assert "Prog3" not in plan.capacity_targets
    assert "Prog4" not in plan.capacity_targets
    assert "Prog5" not in plan.capacity_targets
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
    assert plan.capacity_targets["Prog6"] == decision.morning_start_soc_target
    assert plan.charge_modes["Prog6"] == "No Grid or Gen"
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

    assert plan.capacity_targets["Prog6"] == 51
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
    assert low_plan.capacity_targets["Prog6"] == low.morning_start_soc_target
    assert low_plan.charge_modes["Prog6"] == "Allow Grid"

    reached = decide(
        base_inputs(now=dt(22), battery_soc=low.morning_start_soc_target, forecast_tomorrow_kwh=23),
        settings,
    )
    reached_plan = build_deye_plan(reached, settings)

    assert reached.cheap_grid_mode == "preserve"
    assert not reached.grid_charge_required
    assert reached_plan.capacity_targets["Prog6"] == reached.morning_start_soc_target
    assert reached_plan.charge_modes["Prog6"] == "No Grid or Gen"


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
    assert plan.charge_modes["Prog6"] == "No Grid or Gen"
    assert plan.capacity_targets["Prog6"] != 75


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
        outputs.append(build_deye_plan(decision, settings).capacity_targets["Prog6"])

    assert outputs != [55, 75, 55, 75]
    assert len(set(outputs)) == 1


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


def test_ev_bypass_allows_cheap_grid_topup_below_morning_target() -> None:
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
    assert decision.cheap_grid_mode == "ev_bypass_top_up_to_morning_target"
    assert decision.cheap_grid_preserve_required
    assert decision.grid_charge_required
    assert decision.active_reserve_target_soc >= decision.morning_target_soc


def test_ev_bypass_preserves_above_soc_once_morning_target_reached() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        ev_control_enabled=True,
        ev_grid_bypass_enabled=True,
        cheap_grid_preserve_soc=30,
    )

    decision = decide(
        base_inputs(now=dt(22), forecast_tomorrow_kwh=23, battery_soc=50.5, essential_power_w=7200, previous_essential_power_w=1000),
        settings,
    )
    plan = build_deye_plan(decision, settings)

    assert decision.ev_grid_bypass_required
    assert decision.cheap_grid_mode == "ev_bypass_preserve"
    assert not decision.grid_charge_required
    assert decision.cheap_grid_preserve_target_soc > decision.battery_soc
    assert plan.capacity_targets["Prog6"] > int(decision.battery_soc)
    assert plan.charge_modes["Prog6"] == "No Grid or Gen"


def test_ev_bypass_pauses_topup_when_grid_capacity_is_saturated() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        ev_control_enabled=True,
        ev_grid_bypass_enabled=True,
        cheap_grid_preserve_soc=30,
        ev_restore_program_power_w=12000,
    )

    decision = decide(
        base_inputs(
            now=dt(22),
            forecast_tomorrow_kwh=23,
            battery_soc=23,
            battery_power_w=100,
            grid_power_w=11200,
            essential_power_w=9000,
            previous_essential_power_w=1000,
        ),
        settings,
    )
    plan = build_deye_plan(decision, settings)

    assert decision.ev_grid_bypass_required
    assert decision.cheap_grid_mode == "ev_bypass_preserve"
    assert not decision.grid_charge_required
    assert decision.cheap_grid_preserve_target_soc == 24
    assert plan.capacity_targets["Prog6"] == 24
    assert plan.charge_modes["Prog6"] == "No Grid or Gen"


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
    assert not decide(base_inputs(now=dt(22), ev_latch_on=True, porsche_soc=80), settings).ev_grid_mode_required
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


def test_charger_control_and_connector_status_are_authoritative() -> None:
    settings = EnergyManagerSettings(ev_control_enabled=True, ev_grid_bypass_enabled=True)
    charging = decide(
        base_inputs(
            now=dt(22),
            ev_charge_requested=True,
            ev_current_a=1.0,
            ev_connector_status="Charging",
            porsche_soc=50,
            porsche_charging_status="charging_completed",
        ),
        settings,
    )
    assert charging.ev_grid_bypass_required
    assert "connector status Charging" in charging.ev_decision_reason

    starting = decide(
        base_inputs(now=dt(22), ev_charge_requested=True, ev_current_a=0),
        settings,
    )
    assert starting.ev_grid_bypass_required

    paused = decide(
        base_inputs(now=dt(22), ev_latch_on=True, ev_charge_requested=True, ev_current_a=0, ev_low_since=dt(21, 59)),
        settings,
    )
    assert paused.ev_grid_bypass_required

    long_pause = decide(
        base_inputs(now=dt(22), ev_latch_on=True, ev_charge_requested=True, ev_current_a=0, ev_low_since=dt(21, 51)),
        settings,
    )
    assert long_pause.ev_grid_bypass_required

    suspended_by_ev = decide(
        base_inputs(
            now=dt(22),
            ev_latch_on=True,
            ev_charge_requested=True,
            ev_current_a=0,
            ev_connector_status="SuspendedEV",
        ),
        settings,
    )
    assert not suspended_by_ev.ev_grid_bypass_required
    assert suspended_by_ev.ev_expected_action == "ev_charger_stop"
    assert "SuspendedEV" in suspended_by_ev.ev_decision_reason

    suspended_by_evse = decide(
        base_inputs(
            now=dt(22),
            ev_latch_on=True,
            ev_charge_requested=True,
            ev_current_a=0,
            ev_connector_status="SuspendedEVSE",
            ev_low_since=dt(21, 59),
        ),
        settings,
    )
    assert suspended_by_evse.ev_grid_bypass_required

    morning_cutoff = decide(
        base_inputs(now=dt(7), ev_latch_on=True, ev_charge_requested=True, ev_current_a=16),
        settings,
    )
    assert not morning_cutoff.ev_grid_bypass_required
    assert morning_cutoff.ev_expected_action == "ev_charger_stop"

    solar_handoff = decide(
        base_inputs(now=dt(7), ev_latch_on=True, ev_charge_requested=True, ev_current_a=16),
        EnergyManagerSettings(
            ev_control_enabled=True,
            ev_grid_bypass_enabled=True,
            ev_solar_charging_enabled=True,
        ),
    )
    assert not solar_handoff.ev_grid_bypass_required
    assert solar_handoff.ev_expected_action == "ev_grid_bypass_restore"


def test_normal_ev_charging_has_hard_80_percent_soc_cutoff() -> None:
    settings = EnergyManagerSettings(
        ev_control_enabled=True,
        ev_grid_bypass_enabled=True,
        ev_solar_charging_enabled=True,
    )
    below_target = decide(
        base_inputs(
            now=dt(12),
            ev_charge_requested=True,
            ev_connector_status="Charging",
            porsche_soc=79,
        ),
        settings,
    )
    at_target = decide(
        base_inputs(
            now=dt(12),
            ev_charge_requested=True,
            ev_connector_status="Charging",
            porsche_soc=80,
        ),
        settings,
    )

    assert below_target.ev_active_target_soc == 80
    assert not below_target.ev_soc_cutoff_reached
    assert below_target.ev_expected_action != "ev_charger_stop"
    assert at_target.ev_active_target_soc == 80
    assert at_target.ev_soc_cutoff_reached
    assert at_target.ev_expected_action == "ev_charger_stop"
    assert not at_target.ev_solar_charge_allowed
    assert "normal SOC cutoff" in at_target.ev_decision_reason


def test_effective_local_soc_drives_existing_ev_cutoff() -> None:
    """The coordinator passes resolved local SOC through the existing Porsche field."""

    decision = decide(
        base_inputs(
            now=dt(12),
            ev_charge_requested=True,
            ev_connector_status="Charging",
            porsche_soc=80,
        ),
        EnergyManagerSettings(ev_control_enabled=True, ev_solar_charging_enabled=True),
    )

    assert decision.ev_soc_cutoff_reached
    assert decision.ev_expected_action == "ev_charger_stop"


def test_manual_ev_override_starts_and_stops_at_selected_soc() -> None:
    settings = EnergyManagerSettings(
        ev_control_enabled=True,
        ev_grid_bypass_enabled=True,
        ev_manual_target_soc=90,
    )
    starting = decide(
        base_inputs(
            now=dt(22),
            ev_manual_charging_override=True,
            ev_charge_requested=False,
            ev_connector_status="Preparing",
            porsche_soc=82,
        ),
        settings,
    )
    reached = decide(
        base_inputs(
            now=dt(23),
            ev_latch_on=True,
            ev_manual_charging_override=True,
            ev_charge_requested=True,
            ev_connector_status="Charging",
            porsche_soc=90,
        ),
        settings,
    )

    assert starting.ev_active_target_soc == 90
    assert starting.ev_expected_action == "ev_charger_start"
    assert starting.ev_grid_bypass_required
    assert not starting.ev_soc_cutoff_reached
    assert reached.ev_soc_cutoff_reached
    assert reached.ev_expected_action == "ev_charger_stop"
    assert not reached.ev_grid_bypass_required
    assert "manual SOC cutoff" in reached.ev_decision_reason


def test_manual_ev_override_supports_40_percent_target() -> None:
    settings = EnergyManagerSettings(
        ev_control_enabled=True,
        ev_grid_bypass_enabled=True,
        ev_manual_target_soc=40,
    )

    below_target = decide(
        base_inputs(
            now=dt(22),
            ev_manual_charging_override=True,
            ev_charge_requested=False,
            ev_connector_status="Preparing",
            porsche_soc=39,
        ),
        settings,
    )
    reached = decide(
        base_inputs(
            now=dt(22),
            ev_manual_charging_override=True,
            ev_charge_requested=True,
            ev_connector_status="Charging",
            porsche_soc=40,
        ),
        settings,
    )

    assert below_target.ev_active_target_soc == 40
    assert below_target.ev_expected_action == "ev_charger_start"
    assert not below_target.ev_soc_cutoff_reached
    assert reached.ev_active_target_soc == 40
    assert reached.ev_soc_cutoff_reached
    assert reached.ev_expected_action == "ev_charger_stop"


def test_manual_ev_override_owns_session_across_0700_and_requires_soc() -> None:
    settings = EnergyManagerSettings(
        ev_control_enabled=True,
        ev_grid_bypass_enabled=True,
        ev_solar_charging_enabled=True,
        ev_manual_target_soc=95,
    )
    after_cheap_window = decide(
        base_inputs(
            now=dt(7),
            ev_latch_on=True,
            ev_manual_charging_override=True,
            ev_charge_requested=True,
            ev_connector_status="Charging",
            porsche_soc=90,
        ),
        settings,
    )
    soc_unavailable = decide(
        base_inputs(
            now=dt(22),
            ev_manual_charging_override=True,
            ev_charge_requested=False,
            ev_connector_status="Preparing",
            porsche_soc=None,
        ),
        settings,
    )

    assert after_cheap_window.ev_expected_action != "ev_charger_stop"
    assert not after_cheap_window.ev_solar_charge_allowed
    assert soc_unavailable.ev_expected_action != "ev_charger_start"
    assert "SOC unavailable" in soc_unavailable.ev_decision_reason


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


def test_porsche_completed_status_releases_ev_latch() -> None:
    decision = decide(
        base_inputs(
            now=dt(3),
            ev_latch_on=True,
            ev_hold_until=dt(5),
            essential_power_w=3200,
            previous_essential_power_w=3300,
            porsche_charging_status="charging_completed",
        ),
        EnergyManagerSettings(ev_control_enabled=True, ev_grid_bypass_enabled=True),
    )

    assert not decision.ev_latch_active
    assert decision.ev_expected_action == "ev_grid_bypass_restore"


def test_grid_ct_drop_releases_ev_latch() -> None:
    decision = decide(
        base_inputs(
            now=dt(3),
            ev_latch_on=True,
            ev_hold_until=dt(5),
            essential_power_w=3200,
            previous_essential_power_w=3300,
            grid_power_w=1000,
            previous_grid_power_w=7600,
        ),
        EnergyManagerSettings(ev_control_enabled=True, ev_grid_bypass_enabled=True),
    )

    assert not decision.ev_latch_active
    assert decision.ev_expected_action == "ev_grid_bypass_restore"


def test_porsche_elapsed_charge_end_releases_ev_latch() -> None:
    decision = decide(
        base_inputs(
            now=dt(3),
            ev_latch_on=True,
            ev_hold_until=dt(5),
            essential_power_w=3200,
            previous_essential_power_w=3300,
            porsche_charging_status="unknown",
            porsche_charging_ends=dt(2, 59),
        ),
        EnergyManagerSettings(ev_control_enabled=True, ev_grid_bypass_enabled=True),
    )

    assert not decision.ev_latch_active
    assert decision.ev_expected_action == "ev_grid_bypass_restore"


def test_ev_latch_release_allows_cheap_grid_topup() -> None:
    settings = EnergyManagerSettings(
        cheap_grid_preserve_enabled=True,
        cheap_grid_charge_enabled=True,
        grid_charge_control_enabled=True,
        ev_control_enabled=True,
        ev_grid_bypass_enabled=True,
        cheap_grid_preserve_soc=30,
    )

    decision = decide(
        base_inputs(
            now=dt(3),
            forecast_tomorrow_kwh=23,
            battery_soc=19,
            ev_latch_on=True,
            ev_hold_until=dt(5),
            essential_power_w=3200,
            previous_essential_power_w=3300,
            porsche_charging_status="charging_completed",
        ),
        settings,
    )

    assert not decision.ev_grid_bypass_required
    assert not decision.ev_latch_active
    assert decision.cheap_grid_mode == "top_up_to_morning_target"
    assert decision.grid_charge_required


def test_ev_bypass_does_not_suppress_battery_grid_charge_below_morning_target() -> None:
    decision = decide(
        base_inputs(
            now=dt(4),
            forecast_tomorrow_kwh=12,
            battery_soc=20,
            ev_power_w=2000,
        ),
        EnergyManagerSettings(
            grid_charge_control_enabled=True,
            ev_control_enabled=True,
            ev_grid_bypass_enabled=True,
        ),
    )

    assert decision.ev_grid_bypass_required
    assert decision.grid_charge_required


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

    assert decision.active_slot == "Prog6"
    assert decision.ev_grid_bypass_required
    assert plan.power_targets == {"Prog6": 2000}


def test_ev_solar_charge_allowed_when_priority_prefers_ev() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=90,
            battery_power_w=-2000,
            pv_power_now_w=3000,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=22,
        ),
        EnergyManagerSettings(
            ev_control_enabled=True,
            ev_solar_charging_enabled=True,
            flexible_load_priority="ev_before_thermal",
        ),
    )

    assert decision.ev_solar_charge_allowed
    assert decision.ev_expected_action == "allow_solar_charge"


def test_ev_solar_charge_requires_daylight_arrival_and_no_battery_discharge() -> None:
    settings = EnergyManagerSettings(
        ev_control_enabled=True,
        ev_solar_charging_enabled=True,
        flexible_load_priority="ev_before_thermal",
        cheap_grid_preserve_soc=20,
        daily_battery_target_soc=80,
    )
    before_daytime = decide(
        base_inputs(
            now=dt(6, 59),
            battery_soc=90,
            battery_power_w=-2000,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=35,
        ),
        settings,
    )
    no_solar = decide(
        base_inputs(
            now=dt(7),
            battery_soc=20,
            battery_power_w=-109,
            pv_power_now_w=575,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=55,
        ),
        settings,
    )
    discharging = decide(
        base_inputs(
            now=dt(12),
            battery_soc=90,
            battery_power_w=4000,
            pv_power_now_w=6000,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=35,
        ),
        settings,
    )
    weak_pv = decide(
        base_inputs(
            now=dt(12),
            battery_soc=90,
            battery_power_w=-2000,
            pv_power_now_w=1700,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=35,
        ),
        settings,
    )

    assert not before_daytime.ev_solar_charge_allowed
    assert no_solar.morning_start_soc_target == 20
    assert no_solar.discretionary_energy_budget_kwh > 0
    assert not no_solar.solar_arrived
    assert not no_solar.ev_solar_charge_allowed
    assert discharging.solar_arrived
    assert not discharging.ev_solar_charge_allowed
    assert weak_pv.solar_arrived
    assert not weak_pv.ev_solar_charge_allowed
    assert "1800W startup minimum" in weak_pv.ev_decision_reason


def test_active_ev_session_latches_solar_through_cloud_power_deficit() -> None:
    settings = EnergyManagerSettings(
        ev_control_enabled=True,
        ev_solar_charging_enabled=True,
        flexible_load_priority="ev_before_thermal",
    )
    transient = decide(
        base_inputs(
            now=dt(12, 1),
            battery_soc=90,
            battery_power_w=1400,
            grid_power_w=700,
            paid_grid_import_w=0,
            pv_power_now_w=575,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=35,
            ev_charge_requested=True,
            ev_connector_status="Charging",
            ev_solar_arrived_latched=True,
        ),
        settings,
    )
    prolonged = decide(
        base_inputs(
            now=dt(12, 2),
            battery_soc=90,
            battery_power_w=1400,
            grid_power_w=700,
            paid_grid_import_w=0,
            pv_power_now_w=575,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=35,
            ev_charge_requested=True,
            ev_connector_status="Charging",
            ev_solar_arrived_latched=True,
        ),
        settings,
    )

    assert not transient.solar_arrived
    assert transient.ev_solar_charge_allowed
    assert prolonged.ev_solar_charge_allowed
    assert prolonged.ev_decision_reason == "EV charging confirmed: connector status Charging"


def test_ev_solar_charge_waits_for_derived_morning_battery_target() -> None:
    decision = decide(
        base_inputs(now=dt(8), battery_soc=20, forecast_tomorrow_kwh=35, forecast_remaining_today_kwh=35),
        EnergyManagerSettings(
            ev_control_enabled=True,
            ev_solar_charging_enabled=True,
            flexible_load_priority="ev_before_thermal",
        ),
    )

    assert decision.morning_start_soc_target >= 30
    assert not decision.ev_solar_charge_allowed


def test_daytime_solar_modulation_ignores_suspended_ev_transition() -> None:
    decision = decide(
        base_inputs(
            now=dt(12),
            battery_soc=90,
            battery_power_w=-2000,
            forecast_tomorrow_kwh=35,
            forecast_remaining_today_kwh=22,
            ev_charge_requested=True,
            ev_connector_status="SuspendedEV",
        ),
        EnergyManagerSettings(
            ev_control_enabled=True,
            ev_solar_charging_enabled=True,
            flexible_load_priority="ev_before_thermal",
        ),
    )

    assert decision.ev_solar_charge_allowed
    assert decision.ev_expected_action == "allow_solar_charge"


def test_curtailment_soak_starts_one_managed_load() -> None:
    settings = EnergyManagerSettings(
        thermal_control_enabled=True,
        export_limited_mode_enabled=True,
        pv_load_test_control_enabled=True,
    )
    decision = decide(
        base_inputs(
            now=dt(11),
            battery_soc=80,
            battery_power_w=-1200,
            pv_power_now_w=5200,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20)],
        ),
        settings,
    )

    assert decision.pv_load_test_recommended
    assert decision.thermal_allowed
    assert decision.thermal_load_to_add == "Office"
    assert decision.thermal_action == "add_one"
    assert decision.thermal_lease_reason == "curtailment_soak"
    assert decision.proposed_actions == ["add_one_curtailment_load"]


def test_curtailment_recommendation_does_not_actuate_without_control_gate() -> None:
    decision = decide(
        base_inputs(
            now=dt(11),
            battery_soc=80,
            battery_power_w=-1200,
            pv_power_now_w=5200,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20)],
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            export_limited_mode_enabled=True,
        ),
    )

    assert decision.pv_load_test_recommended
    assert not decision.thermal_allowed
    assert decision.thermal_load_to_add is None
    assert decision.thermal_action == "none"
    assert decision.proposed_actions == ["curtailment_soak_recommended"]


def test_live_export_and_future_forecast_do_not_trigger_curtailment_soak() -> None:
    settings = EnergyManagerSettings(
        thermal_control_enabled=True,
        export_limited_mode_enabled=True,
        pv_load_test_control_enabled=True,
    )
    exporting = decide(
        base_inputs(
            now=dt(11),
            battery_soc=80,
            battery_power_w=-1200,
            grid_power_w=-2200,
            export_power_w=2200,
            pv_power_now_w=5200,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20)],
        ),
        settings,
    )
    future_only = decide(
        base_inputs(
            now=dt(11),
            battery_soc=80,
            battery_power_w=-1200,
            pv_power_now_w=1000,
            pv_power_in_30_minutes_w=5200,
            heat_loads=[HeatLoadState(name="Office", priority=1, current_temp=20)],
        ),
        settings,
    )

    assert not exporting.thermal_allowed
    assert "preserving 2200W live export" in exporting.thermal_action_reason
    assert not future_only.thermal_allowed


def test_curtailment_cleanup_stops_only_manager_owned_load() -> None:
    decision = decide(
        base_inputs(
            now=dt(11),
            battery_soc=80,
            battery_power_w=500,
            pv_power_now_w=5200,
            any_solar_owned_heat_load_on=True,
            heat_loads=[
                HeatLoadState(
                    name="Office",
                    priority=1,
                    is_on=True,
                    solar_owned=True,
                    lease_reason="curtailment_soak",
                    current_temp=20,
                ),
                HeatLoadState(
                    name="Dining",
                    priority=2,
                    is_on=True,
                    owner="manual",
                    current_temp=20,
                ),
            ],
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            export_limited_mode_enabled=True,
            pv_load_test_control_enabled=True,
        ),
    )

    assert decision.thermal_should_shed
    assert not decision.thermal_should_emergency_shed
    assert decision.thermal_load_to_shed == "Office"
    assert decision.thermal_action == "shed_one"
    assert decision.proposed_actions == ["stop_curtailment_load"]


def test_curtailment_soak_skips_manual_override_candidate() -> None:
    decision = decide(
        base_inputs(
            now=dt(11),
            battery_soc=80,
            battery_power_w=-1200,
            pv_power_now_w=5200,
            heat_loads=[
                HeatLoadState(
                    name="Dining",
                    priority=1,
                    owner="manual",
                    manual_override_until=dt(12),
                    current_temp=18,
                ),
                HeatLoadState(name="Office", priority=2, current_temp=20),
            ],
        ),
        EnergyManagerSettings(
            thermal_control_enabled=True,
            export_limited_mode_enabled=True,
            pv_load_test_control_enabled=True,
        ),
    )

    assert decision.thermal_load_to_add == "Office"


def test_disabled_thermal_control_does_not_publish_shed_actions() -> None:
    decision = decide(
        base_inputs(
            now=dt(23),
            battery_power_w=5000,
            heat_loads=[
                HeatLoadState(
                    name="Office heat pump",
                    priority=1,
                    is_on=True,
                    hvac_mode="heat",
                    current_temp=22,
                    target_temp=27,
                )
            ],
        ),
        EnergyManagerSettings(thermal_control_enabled=False),
    )

    assert not decision.thermal_should_shed
    assert not decision.thermal_should_emergency_shed
    assert decision.thermal_action == "none"
    assert "shed_one_heat_load" not in decision.proposed_actions
    assert "emergency_shed_all_heat_loads" not in decision.proposed_actions


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


def test_grid_loss_notify_service_migrates_to_s26() -> None:
    options, changed = migrate_options({"grid_loss_notify_service": "notify.notify"})

    assert changed
    assert options["grid_loss_notify_service"] == "notify.mobile_app_s26u"


def test_grid_loss_integration_notification_migrates_off() -> None:
    options, changed = migrate_options({"grid_loss_notification_enabled": True})

    assert changed
    assert options["grid_loss_notification_enabled"] is False


def test_ev_fallback_hold_migrates_from_old_three_hour_default() -> None:
    options, changed = migrate_options({"ev_fallback_hold_minutes": 180.0})

    assert changed
    assert options["ev_fallback_hold_minutes"] == 15.0


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
