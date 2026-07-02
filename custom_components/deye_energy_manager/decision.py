"""Pure decision engine for Deye Energy Manager."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from .models import EnergyManagerDecision, EnergyManagerInputs, EnergyManagerSettings, ForecastTier, HeatLoadState

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


def hours_until_time(now: datetime, target: str) -> float:
    """Return local hours until the next occurrence of a target time."""

    target_time = time.fromisoformat(target)
    target_dt = now.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
    if target_dt <= now:
        target_dt += timedelta(days=1)
    return (target_dt - now).total_seconds() / 3600.0


def projected_soc_at_08(inputs: EnergyManagerInputs, settings: EnergyManagerSettings) -> float | None:
    """Project SOC at 08:00 from current discharge rate."""

    if not time_between(inputs.now, "21:00", "08:00"):
        return None
    battery_discharge_w = max(inputs.battery_power_w, 0.0)
    if battery_discharge_w <= 0 or settings.battery_capacity_kwh <= 0:
        return inputs.battery_soc
    discharge_kwh = battery_discharge_w * hours_until_time(inputs.now, "08:00") / 1000.0
    return max(inputs.battery_soc - (discharge_kwh / settings.battery_capacity_kwh * 100.0), 0.0)


def effective_thermal_mode(settings: EnergyManagerSettings) -> str:
    """Return the concrete thermal mode. Auto defaults to heating for now."""

    if settings.thermal_mode == "auto":
        return "heating"
    return settings.thermal_mode


def thermal_targets(settings: EnergyManagerSettings) -> tuple[float, float]:
    """Return soak and normal target temperatures for the active thermal mode."""

    if effective_thermal_mode(settings) == "cooling":
        return settings.cool_soak_target_temp, settings.cool_normal_target_temp
    return settings.heat_soak_target_temp, settings.heat_normal_target_temp


def thermal_hvac_mode(settings: EnergyManagerSettings) -> str:
    """Return Home Assistant climate HVAC mode for the active thermal mode."""

    return "cool" if effective_thermal_mode(settings) == "cooling" else "heat"


def thermal_soak_action(settings: EnergyManagerSettings, load: HeatLoadState) -> tuple[str, float] | None:
    """Return direct climate action for soaking one load."""

    mode = effective_thermal_mode(settings)
    if not load_supports_mode(load, mode):
        return None
    soak_target, _normal_target = thermal_targets(settings)
    return thermal_hvac_mode(settings), soak_target


def thermal_shed_action(settings: EnergyManagerSettings, load: HeatLoadState) -> tuple[str, float | None]:
    """Return direct climate action for shedding/normalising one load."""

    if not settings.return_to_normal_on_shed_enabled or load.load_type == "underfloor":
        return "off", None
    _soak_target, normal_target = thermal_targets(settings)
    return thermal_hvac_mode(settings), normal_target


def load_supports_mode(load: HeatLoadState, mode: str) -> bool:
    """Return whether a managed load can be used for the thermal mode."""

    if not load.enabled:
        return False
    if mode == "cooling":
        return load.supports_cooling
    return load.supports_heating


def load_is_active(load: HeatLoadState, mode: str) -> bool:
    """Return whether a thermal load is actually working, using power/action when available."""

    if load.power_w is not None:
        return load.power_w >= load.active_power_threshold_w
    if load.hvac_action:
        return (mode == "heating" and load.hvac_action == "heating") or (mode == "cooling" and load.hvac_action == "cooling")
    return load.is_on


def load_is_satisfied(load: HeatLoadState, settings: EnergyManagerSettings) -> bool:
    """Return whether a thermal load is close to the soak target or tapering."""

    mode = effective_thermal_mode(settings)
    soak_target, _normal_target = thermal_targets(settings)
    if load.power_w is not None and load.solar_owned and load.is_on and load.power_w <= load.taper_power_threshold_w:
        return True
    if load.current_temp is None:
        return False
    if mode == "cooling":
        return load.current_temp <= soak_target + settings.room_satisfied_delta_c
    return load.current_temp >= soak_target - settings.room_satisfied_delta_c


def load_needs_soak(load: HeatLoadState, settings: EnergyManagerSettings) -> bool:
    """Return whether a load still has useful thermal storage headroom."""

    mode = effective_thermal_mode(settings)
    soak_target, _normal_target = thermal_targets(settings)
    if load.blocked_until is not None or not load_supports_mode(load, mode):
        return False
    if load.current_temp is None:
        return not load.solar_owned and not load.is_on
    if mode == "cooling":
        return load.current_temp > soak_target + settings.room_resume_delta_c
    return load.current_temp < soak_target - settings.room_resume_delta_c


def satisfied_heat_loads(loads: list[HeatLoadState], settings: EnergyManagerSettings) -> list[HeatLoadState]:
    """Return solar-owned thermal loads close enough to soak target or tapering."""

    return [
        load
        for load in loads
        if load.solar_owned
        and load.is_on
        and load_is_satisfied(load, settings)
    ]


def needy_heat_loads(loads: list[HeatLoadState], settings: EnergyManagerSettings) -> list[HeatLoadState]:
    """Return off loads still materially away from soak target."""

    return [
        load
        for load in loads
        if load.blocked_until is None
        and not load.solar_owned
        and not load.is_on
        and load_needs_soak(load, settings)
    ]


def forecast_full_override_active(
    inputs: EnergyManagerInputs,
    settings: EnergyManagerSettings,
    tier: ForecastTier,
) -> bool:
    """Return whether forecast is strong enough to start thermal storage early."""

    remaining = inputs.forecast_remaining_today_kwh
    if remaining is None:
        return False
    required_kwh = max(tier.target_17_soc - inputs.battery_soc, 0.0) / 100.0 * settings.battery_capacity_kwh
    return (
        settings.forecast_full_override_enabled
        and tier.mode in {"excellent", "good"}
        and remaining >= required_kwh + settings.forecast_full_confidence_buffer_kwh
    )


def decide(inputs: EnergyManagerInputs, settings: EnergyManagerSettings | None = None) -> EnergyManagerDecision:
    """Calculate the current energy-management decision."""

    settings = settings or EnergyManagerSettings()
    tier = forecast_tier(inputs.forecast_tomorrow_kwh, settings)
    reserve_soc = current_reserve_soc(inputs.now, tier)
    battery_charge_w = max(-inputs.battery_power_w, 0.0)
    battery_discharge_w = max(inputs.battery_power_w, 0.0)
    cheap_window = time_between(inputs.now, "21:00", "07:00")
    control_blocked = not settings.enabled
    thermal_mode = effective_thermal_mode(settings)
    thermal_control_enabled = settings.thermal_control_enabled or settings.heat_control_enabled
    thermal_start_min_soc = settings.thermal_start_min_soc
    thermal_start_min_charge_w = settings.thermal_start_min_charge_w
    thermal_shed_discharge_w = settings.thermal_shed_discharge_w
    forecast_override = forecast_full_override_active(inputs, settings, tier)
    expected_pv_power_w = max(
        inputs.pv_power_now_w or 0.0,
        inputs.pv_power_in_30_minutes_w or 0.0,
        inputs.pv_power_in_1_hour_w or 0.0,
    )
    remaining_forecast_kwh = inputs.forecast_remaining_today_kwh
    if remaining_forecast_kwh is None:
        remaining_forecast_kwh = max((inputs.forecast_tomorrow_kwh or 0.0) / 3.0, 0.0)

    pre_peak_preserve_required = (
        time_between(inputs.now, "13:00", "17:00")
        and inputs.battery_soc < tier.target_17_soc
        and battery_charge_w < settings.heat_add_min_charge_w
    )

    battery_priority_satisfied = (
        inputs.battery_soc >= tier.target_17_soc
        or battery_charge_w >= settings.heat_add_min_charge_w
    )

    thermal_time_allowed = time_between(inputs.now, "08:00", "17:00") or (
        tier.mode in {"excellent", "good"}
        and time_between(inputs.now, "07:00", "17:00")
        and (forecast_override or expected_pv_power_w >= settings.thermal_keep_running_min_charge_w)
    )
    thermal_allowed = (
        settings.enabled
        and thermal_control_enabled
        and thermal_mode != "off"
        and inputs.heat_available
        and thermal_time_allowed
        and inputs.cooldown_passed
        and (
            inputs.battery_soc >= thermal_start_min_soc
            or battery_charge_w >= thermal_start_min_charge_w
            or forecast_override
        )
        and battery_discharge_w < thermal_shed_discharge_w
    )

    projected_soc = projected_soc_at_08(inputs, settings)
    overnight_protection_required = (
        settings.enabled
        and inputs.any_solar_owned_heat_load_on
        and projected_soc is not None
        and projected_soc < tier.morning_floor
    )
    bedroom_heat_taper_recommended = (
        settings.enabled
        and time_between(inputs.now, "21:00", "08:00")
        and any(load.solar_owned and load.is_on and "bedroom" in f"{load.name} {load.load_type}".lower() for load in inputs.heat_loads)
    )

    thermal_should_shed = (
        inputs.any_solar_owned_heat_load_on
        and (
            battery_discharge_w >= thermal_shed_discharge_w
            or (
                not forecast_override
                and inputs.battery_soc < thermal_start_min_soc
                and battery_charge_w < settings.thermal_keep_running_min_charge_w
            )
            or (
                pre_peak_preserve_required
                and not forecast_override
                and inputs.battery_soc < thermal_start_min_soc
            )
            or overnight_protection_required
        )
    )

    thermal_should_emergency_shed = (
        settings.enabled
        and inputs.any_solar_owned_heat_load_on
        and battery_discharge_w >= settings.thermal_emergency_shed_w
    )
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

    shed_candidates = sorted(satisfied_heat_loads(inputs.heat_loads, settings), key=lambda load: load.priority, reverse=True)
    add_candidates = sorted(needy_heat_loads(inputs.heat_loads, settings), key=lambda load: load.priority)
    thermal_load_to_shed = shed_candidates[0].name if shed_candidates else None
    thermal_load_to_add = add_candidates[0].name if add_candidates else None
    thermal_rotation_recommended = (
        thermal_allowed
        and settings.thermal_rotation_enabled
        and inputs.heat_available
        and thermal_load_to_shed is not None
        and thermal_load_to_add is not None
    )
    thermal_load_to_normalise = thermal_load_to_shed if thermal_should_shed else None
    solar_owned_count = sum(1 for load in inputs.heat_loads if load.solar_owned)
    active_thermal_loads = [load.name for load in inputs.heat_loads if load.solar_owned and load_is_active(load, thermal_mode)]
    thermal_should_return_to_normal = thermal_should_shed and settings.return_to_normal_on_shed_enabled

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

    thermal_action = "none"
    if thermal_should_emergency_shed:
        thermal_action = "emergency_shed_all"
    elif thermal_rotation_recommended:
        thermal_action = "rotate"
    elif thermal_should_shed:
        thermal_action = "return_to_normal" if settings.return_to_normal_on_shed_enabled else "shed_one"
    elif thermal_allowed and thermal_load_to_add:
        thermal_action = "add_one"
    elif thermal_allowed:
        thermal_action = "hold"

    proposed_actions: list[str] = []
    reason_parts = []
    thermal_reason_parts: list[str] = []
    if control_blocked:
        reason_parts.append("manager disabled")
    reason_parts.append(f"forecast {tier.mode}")
    if thermal_allowed:
        reason = "thermal_allowed=true"
        if inputs.battery_soc >= thermal_start_min_soc:
            reason += f": SOC {inputs.battery_soc:.1f} >= thermal_start_min_soc {thermal_start_min_soc:.0f}"
        elif forecast_override:
            required_kwh = max(tier.target_17_soc - inputs.battery_soc, 0.0) / 100.0 * settings.battery_capacity_kwh
            reason += (
                f": forecast_full_override active; remaining {remaining_forecast_kwh:.1f}kWh > "
                f"required {required_kwh:.1f}kWh + buffer {settings.forecast_full_confidence_buffer_kwh:.0f}kWh"
            )
        else:
            reason += f": battery charge {battery_charge_w:.0f}W >= start threshold {thermal_start_min_charge_w:.0f}W"
        reason_parts.append(reason)
        thermal_reason_parts.append(reason)
    else:
        if thermal_mode == "off":
            reason = "thermal_allowed=false: thermal mode off"
        elif not thermal_control_enabled:
            reason = "thermal_allowed=false: thermal control disabled"
        elif battery_discharge_w >= thermal_shed_discharge_w:
            reason = f"thermal_allowed=false: battery discharging {battery_discharge_w:.0f}W >= shed threshold {thermal_shed_discharge_w:.0f}W"
        else:
            reason = (
                "thermal_allowed=false: "
                f"SOC {inputs.battery_soc:.1f} < thermal_start_min_soc {thermal_start_min_soc:.0f}, "
                f"charge {battery_charge_w:.0f}W < {thermal_start_min_charge_w:.0f}W, "
                f"forecast_full_override={forecast_override}"
            )
        reason_parts.append(reason)
        thermal_reason_parts.append(reason)
    if thermal_allowed and thermal_load_to_add:
        proposed_actions.append("add_one_heat_load")
    if thermal_should_shed:
        proposed_actions.append("shed_one_heat_load")
        shed_reason = f"thermal_should_shed=true: battery discharging {battery_discharge_w:.0f}W >= shed threshold {thermal_shed_discharge_w:.0f}W" if battery_discharge_w >= thermal_shed_discharge_w else "thermal_should_shed=true"
        reason_parts.append(shed_reason)
        thermal_reason_parts.append(shed_reason)
    else:
        reason_parts.append(f"thermal_should_shed=false: battery charge {battery_charge_w:.0f}W, forecast_full_override={forecast_override}")
    if thermal_should_emergency_shed:
        proposed_actions.append("emergency_shed_all_heat_loads")
        reason_parts.append(
            f"thermal_should_emergency_shed=true: discharge {battery_discharge_w:.0f}W >= {settings.thermal_emergency_shed_w:.0f}W"
        )
    if overnight_protection_required:
        proposed_actions.append("overnight_shed_nonessential_heat")
        reason_parts.append(
            f"overnight_protection_required=true: projected SOC 08:00 {projected_soc:.1f}% < morning target {tier.morning_floor:.0f}%"
        )
    if bedroom_heat_taper_recommended:
        proposed_actions.append("taper_bedroom_heat")
        reason_parts.append(f"bedroom_heat_taper_recommended=true: target {settings.overnight_bedroom_taper_target_temp:.1f}C")
    if pv_load_test_recommended:
        proposed_actions.append("test_one_pv_load")
        reason_parts.append(
            "pv_load_test_recommended=true: "
            f"expected PV {expected_pv_power_w:.0f}W >= {settings.pv_load_test_min_expected_power_w:.0f}W, "
            f"charge {battery_charge_w:.0f}W <= {settings.pv_load_test_max_battery_charge_w:.0f}W, "
            f"SOC {inputs.battery_soc:.0f}% >= {settings.pv_load_test_min_soc:.0f}%"
        )
    if thermal_rotation_recommended:
        proposed_actions.append("rotate_heat_load")
        proposed_actions.append("rotate_thermal_load")
        reason_parts.append(
            f"rotation_recommended=true: {thermal_load_to_shed} satisfied/tapering, {thermal_load_to_add} needs {thermal_mode}"
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
        heat_allowed=thermal_allowed,
        heat_should_shed=thermal_should_shed,
        thermal_allowed=thermal_allowed,
        thermal_should_shed=thermal_should_shed,
        thermal_should_emergency_shed=thermal_should_emergency_shed,
        forecast_full_override_active=forecast_override,
        thermal_rotation_recommended=thermal_rotation_recommended,
        thermal_should_return_to_normal=thermal_should_return_to_normal,
        thermal_action=thermal_action,
        thermal_action_reason="; ".join(thermal_reason_parts),
        thermal_load_to_add=thermal_load_to_add,
        thermal_load_to_shed=thermal_load_to_shed,
        thermal_load_to_normalise=thermal_load_to_normalise,
        solar_owned_thermal_load_count=solar_owned_count,
        active_thermal_loads=active_thermal_loads,
        pv_load_test_recommended=pv_load_test_recommended,
        heat_rotation_recommended=thermal_rotation_recommended,
        heat_load_to_shed=thermal_load_to_shed,
        heat_load_to_add=thermal_load_to_add,
        emergency_shed_all_required=thermal_should_emergency_shed,
        overnight_protection_required=overnight_protection_required,
        bedroom_heat_taper_recommended=bedroom_heat_taper_recommended,
        projected_soc_08=projected_soc,
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
