"""Pure decision engine for Deye Energy Manager."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from .models import EnergyManagerDecision, EnergyManagerInputs, EnergyManagerSettings, ForecastTier

FORECAST_TIERS = [
    (32.0, ForecastTier("excellent", 35.0, 20.0, 75.0, 15.0, 90.0, 0.0)),
    (24.0, ForecastTier("good", 40.0, 25.0, 80.0, 15.0, 90.0, 0.0)),
    (16.0, ForecastTier("medium", 50.0, 35.0, 80.0, 20.0, 85.0, 0.0)),
    (10.0, ForecastTier("poor", 65.0, 50.0, 85.0, 25.0, 85.0, 65.0)),
    (6.0, ForecastTier("dreadful", 75.0, 60.0, 85.0, 30.0, 85.0, 75.0)),
    (float("-inf"), ForecastTier("brutal", 80.0, 65.0, 85.0, 30.0, 85.0, 80.0)),
]


def forecast_tier(forecast_tomorrow_kwh: float | None, settings: EnergyManagerSettings) -> ForecastTier:
    """Return the reserve policy tier for the forecast."""

    if forecast_tomorrow_kwh is None:
        forecast_tomorrow_kwh = 0.0
    adjusted = forecast_tomorrow_kwh - max(settings.forecast_safety_buffer_kwh, 0.0)
    for minimum, tier in FORECAST_TIERS:
        if adjusted >= minimum:
            grid_target = min(tier.grid_charge_target_soc, settings.max_grid_charge_target_soc)
            return ForecastTier(
                tier.mode,
                max(tier.overnight_floor, settings.min_soc_floor),
                max(tier.morning_floor, settings.min_soc_floor),
                max(tier.pre_peak_floor, settings.min_soc_floor),
                max(tier.peak_floor, settings.min_soc_floor),
                tier.target_17_soc,
                grid_target,
            )
    raise RuntimeError("unreachable forecast tier")


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def time_between(now: datetime, start: str, end: str) -> bool:
    """Return whether now is in a local half-open time range."""

    start_t = time.fromisoformat(start)
    end_t = time.fromisoformat(end)
    current = _minutes(now.time())
    start_m = _minutes(start_t)
    end_m = _minutes(end_t)
    if start_m <= end_m:
        return start_m <= current < end_m
    return current >= start_m or current < end_m


def active_slot(now: datetime) -> str:
    """Return the active Deye programme slot."""

    if time_between(now, "21:00", "02:00"):
        return "Prog6"
    if time_between(now, "02:00", "04:00"):
        return "Prog1"
    if time_between(now, "04:00", "06:55"):
        return "Prog2"
    if time_between(now, "06:55", "13:00"):
        return "Prog3"
    if time_between(now, "13:00", "17:00"):
        return "Prog4"
    return "Prog5"


def tariff_window(now: datetime) -> str:
    """Return the strategy tariff window."""

    if time_between(now, "21:00", "07:00"):
        return "cheap_grid"
    if time_between(now, "07:00", "13:00"):
        return "morning_solar_ramp"
    if time_between(now, "13:00", "17:00"):
        return "pre_peak_preserve"
    return "peak"


def current_reserve_soc(now: datetime, tier: ForecastTier) -> float:
    """Return reserve floor for the current time."""

    if time_between(now, "21:00", "06:55"):
        return tier.overnight_floor
    if time_between(now, "06:55", "13:00"):
        return tier.morning_floor
    if time_between(now, "13:00", "17:00"):
        return tier.pre_peak_floor
    return tier.peak_floor


def decide(inputs: EnergyManagerInputs, settings: EnergyManagerSettings | None = None) -> EnergyManagerDecision:
    """Calculate the current energy-management decision."""

    settings = settings or EnergyManagerSettings()
    tier = forecast_tier(inputs.forecast_tomorrow_kwh, settings)
    reserve_soc = current_reserve_soc(inputs.now, tier)
    battery_charge_w = max(-inputs.battery_power_w, 0.0)
    battery_discharge_w = max(inputs.battery_power_w, 0.0)
    cheap_window = time_between(inputs.now, "21:00", "07:00")
    control_blocked = not settings.enabled

    pre_peak_preserve_required = (
        time_between(inputs.now, "13:00", "17:00")
        and inputs.battery_soc < tier.target_17_soc
        and battery_charge_w < settings.heat_add_min_charge_w
    )

    battery_priority_satisfied = (
        inputs.battery_soc >= tier.target_17_soc
        or battery_charge_w >= settings.heat_add_min_charge_w
    )

    heat_allowed = (
        settings.enabled
        and inputs.heat_available
        and time_between(inputs.now, "08:00", "17:00")
        and inputs.cooldown_passed
        and battery_priority_satisfied
        and battery_discharge_w < 200.0
    )

    heat_should_shed = (
        inputs.any_solar_owned_heat_load_on
        and (
            battery_discharge_w >= settings.heat_shed_discharge_w
            or (battery_charge_w < settings.heat_add_min_charge_w and inputs.battery_soc < tier.target_17_soc)
            or pre_peak_preserve_required
        )
    )

    expected_pv_power_w = max(
        inputs.pv_power_now_w or 0.0,
        inputs.pv_power_in_30_minutes_w or 0.0,
        inputs.pv_power_in_1_hour_w or 0.0,
    )
    remaining_forecast_kwh = inputs.forecast_remaining_today_kwh
    if remaining_forecast_kwh is None:
        remaining_forecast_kwh = max((inputs.forecast_tomorrow_kwh or 0.0) / 3.0, 0.0)
    pv_load_test_recommended = (
        settings.enabled
        and settings.export_limited_mode_enabled
        and inputs.heat_available
        and time_between(inputs.now, "08:00", "16:30")
        and not inputs.any_solar_owned_heat_load_on
        and not pre_peak_preserve_required
        and inputs.battery_soc >= settings.pv_load_test_min_soc
        and inputs.battery_soc < tier.target_17_soc
        and battery_charge_w <= settings.pv_load_test_max_battery_charge_w
        and expected_pv_power_w >= settings.pv_load_test_min_expected_power_w
        and remaining_forecast_kwh >= settings.pv_load_test_min_remaining_forecast_kwh
        and battery_discharge_w < 200.0
    )

    essential_jump_w = None
    if inputs.previous_essential_power_w is not None:
        essential_jump_w = inputs.essential_power_w - inputs.previous_essential_power_w

    ev_start = (
        cheap_window
        and (
            (essential_jump_w is not None and essential_jump_w >= settings.ev_start_load_jump_w)
            or inputs.essential_power_w > 6500.0
        )
    )
    ev_stop = (
        inputs.manual_clear_ev_latch
        or not cheap_window
        or (inputs.porsche_soc is not None and inputs.porsche_soc >= 99.0)
        or (essential_jump_w is not None and essential_jump_w <= -settings.ev_stop_load_drop_w)
        or (
            inputs.ev_hold_until is not None
            and inputs.now >= inputs.ev_hold_until
            and inputs.essential_power_w < 2500.0
        )
    )
    ev_grid_mode_required = False if ev_stop else inputs.ev_latch_on or ev_start

    grid_charge_required = (
        settings.enabled
        and settings.grid_charge_control_enabled
        and time_between(inputs.now, "03:00", "07:00")
        and tier.grid_charge_target_soc > 0
        and inputs.battery_soc < tier.grid_charge_target_soc - 1.0
        and not ev_grid_mode_required
    )

    proposed_actions: list[str] = []
    reason_parts = []
    if control_blocked:
        reason_parts.append("manager disabled")
    reason_parts.append(f"forecast {tier.mode}")
    if heat_allowed:
        proposed_actions.append("add_one_heat_load")
        if battery_charge_w >= settings.heat_add_min_charge_w:
            reason_parts.append(f"heat_allowed=true: charge {battery_charge_w:.0f}W >= {settings.heat_add_min_charge_w:.0f}W")
        else:
            reason_parts.append(f"heat_allowed=true: SOC {inputs.battery_soc:.1f} >= target_17 {tier.target_17_soc:.0f}")
    else:
        reason_parts.append(
            "heat_allowed=false: "
            f"SOC {inputs.battery_soc:.1f} < target_17 {tier.target_17_soc:.0f} "
            f"and charge {battery_charge_w:.0f}W < {settings.heat_add_min_charge_w:.0f}W"
        )
    if heat_should_shed:
        proposed_actions.append("shed_one_heat_load")
        reason_parts.append("heat_should_shed=true")
    if pv_load_test_recommended:
        proposed_actions.append("test_one_pv_load")
        reason_parts.append(
            "pv_load_test_recommended=true: "
            f"expected PV {expected_pv_power_w:.0f}W >= {settings.pv_load_test_min_expected_power_w:.0f}W, "
            f"charge {battery_charge_w:.0f}W <= {settings.pv_load_test_max_battery_charge_w:.0f}W, "
            f"SOC {inputs.battery_soc:.0f}% >= {settings.pv_load_test_min_soc:.0f}%"
        )
    if grid_charge_required:
        proposed_actions.append("enable_grid_charge")
        reason_parts.append(
            f"grid_charge_required=true: forecast {tier.mode}, SOC {inputs.battery_soc:.0f} < target {tier.grid_charge_target_soc:.0f}, EV mode off"
        )
    if ev_grid_mode_required:
        proposed_actions.append("ev_grid_mode")
        reason_parts.append("ev_grid_mode_required=true")
    if pre_peak_preserve_required:
        reason_parts.append(
            f"pre_peak_preserve_required=true: SOC {inputs.battery_soc:.0f} < target_17 {tier.target_17_soc:.0f} "
            f"and charge {battery_charge_w:.0f}W < {settings.heat_add_min_charge_w:.0f}W"
        )

    ev_hold_until = inputs.ev_hold_until
    if ev_start and ev_hold_until is None:
        if inputs.porsche_charging_ends and inputs.porsche_charging_ends > inputs.now:
            ev_hold_until = inputs.porsche_charging_ends + timedelta(minutes=10)
        else:
            ev_hold_until = inputs.now + timedelta(hours=3)

    return EnergyManagerDecision(
        now=inputs.now,
        forecast_mode=tier.mode,
        active_slot=active_slot(inputs.now),
        tariff_window=tariff_window(inputs.now),
        target_17_soc=tier.target_17_soc,
        current_reserve_soc=reserve_soc,
        grid_charge_target_soc=tier.grid_charge_target_soc,
        battery_soc=inputs.battery_soc,
        battery_power_w=inputs.battery_power_w,
        battery_charge_w=battery_charge_w,
        battery_discharge_w=battery_discharge_w,
        battery_priority_satisfied=battery_priority_satisfied,
        heat_allowed=heat_allowed,
        heat_should_shed=heat_should_shed,
        pv_load_test_recommended=pv_load_test_recommended,
        grid_charge_required=grid_charge_required,
        ev_grid_mode_required=ev_grid_mode_required,
        pre_peak_preserve_required=pre_peak_preserve_required,
        control_blocked=control_blocked,
        reason="; ".join(reason_parts),
        proposed_actions=proposed_actions,
        forecast_today_kwh=inputs.forecast_today_kwh,
        forecast_remaining_today_kwh=inputs.forecast_remaining_today_kwh,
        forecast_tomorrow_kwh=inputs.forecast_tomorrow_kwh,
        pv_power_now_w=inputs.pv_power_now_w,
        ev_hold_until=ev_hold_until,
        forecast_data_valid=inputs.forecast_tomorrow_kwh is not None,
    )


def slot_capacity_targets(tier: ForecastTier) -> dict[str, float]:
    """Return Deye programme capacity targets for a tier."""

    return {
        "Prog6": tier.overnight_floor,
        "Prog1": tier.overnight_floor,
        "Prog2": tier.overnight_floor,
        "Prog3": tier.morning_floor,
        "Prog4": tier.pre_peak_floor,
        "Prog5": tier.peak_floor,
    }
