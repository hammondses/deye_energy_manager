"""Pure decision engine for Deye Energy Manager."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from .models import EnergyManagerDecision, EnergyManagerInputs, EnergyManagerSettings, ForecastTier, HeatLoadState, ThermalLoadDiagnostic

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


def time_from_hour(value: float) -> str:
    """Return HH:MM from decimal hour, accepting 24 as midnight."""

    value = value % 24.0
    hour = int(value)
    minute = int(round((value - hour) * 60))
    if minute >= 60:
        hour = (hour + 1) % 24
        minute = 0
    return f"{hour:02d}:{minute:02d}"


def is_underfloor_load(load: HeatLoadState | dict[str, object]) -> bool:
    """Return whether a load is an underfloor slab load."""

    raw = load.load_type if isinstance(load, HeatLoadState) else str(load.get("type", ""))
    return str(raw).lower() in {"underfloor", "floor_underfloor"}


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


def solar_phase(now: datetime) -> str:
    """Return the flexible-load phase for the day."""

    if time_between(now, "21:00", "06:55"):
        return "cheap_grid_night"
    if time_between(now, "06:55", "11:30"):
        return "morning_battery_priority"
    if time_between(now, "11:30", "14:30"):
        return "midday_balance"
    if time_between(now, "14:30", "17:00"):
        return "afternoon_soak"
    return "evening_preserve"


def paid_time_floor_soc(now: datetime, settings: EnergyManagerSettings) -> float:
    """Return the paid-time minimum reserve floor for the current phase."""

    phase = solar_phase(now)
    if phase == "morning_battery_priority":
        return settings.morning_paid_time_min_reserve_soc
    if phase == "evening_preserve":
        return settings.evening_paid_time_min_reserve_soc
    if phase in {"midday_balance", "afternoon_soak"}:
        return settings.paid_time_min_reserve_soc
    return settings.min_soc_floor


def solar_arrived(
    inputs: EnergyManagerInputs,
    settings: EnergyManagerSettings,
    battery_charge_w: float,
) -> tuple[bool, str]:
    """Return whether real solar has arrived, not just forecast solar."""

    pv_now = inputs.pv_power_now_w or 0.0
    grid_import_w = max(inputs.grid_power_w, 0.0)
    pv_surplus_w = pv_now - inputs.essential_power_w
    if battery_charge_w >= settings.solar_arrived_charge_threshold_w:
        return True, f"battery charging {battery_charge_w:.0f}W >= {settings.solar_arrived_charge_threshold_w:.0f}W"
    if pv_surplus_w >= settings.solar_arrived_pv_surplus_threshold_w:
        return True, f"PV surplus {pv_surplus_w:.0f}W >= {settings.solar_arrived_pv_surplus_threshold_w:.0f}W"
    if grid_import_w <= settings.paid_grid_import_threshold_w and battery_charge_w > 0:
        return True, f"grid import {grid_import_w:.0f}W low and battery charging"
    return False, "PV has not arrived strongly enough"


def paid_grid_avoidance_state(
    inputs: EnergyManagerInputs,
    settings: EnergyManagerSettings,
    reserve_soc: float,
    battery_charge_w: float,
) -> tuple[bool, str, float, float, bool, str, bool]:
    """Return paid-grid avoidance requirement and reserve target details."""

    floor = paid_time_floor_soc(inputs.now, settings)
    arrived, arrived_reason = solar_arrived(inputs, settings, battery_charge_w)
    paid_import_w = max(inputs.grid_power_w, 0.0)
    cheap_window = time_between(inputs.now, "21:00", "07:00")
    forecast_drain_blocked = False
    required = False
    reason = "paid grid avoidance not required"
    if settings.paid_time_grid_avoidance_enabled and not cheap_window:
        near_floor = inputs.battery_soc is not None and inputs.battery_soc <= floor + 2.0
        importing = paid_import_w >= settings.paid_grid_import_threshold_w
        morning_before_solar = solar_phase(inputs.now) == "morning_battery_priority" and not arrived
        forecast_drain_blocked = not arrived and (morning_before_solar or reserve_soc < floor)
        required = near_floor and (importing or morning_before_solar)
        if required:
            reason = (
                f"paid_grid_avoidance_required: SOC {inputs.battery_soc:.0f}% near floor {floor:.0f}%, paid time, "
                f"{'solar not arrived' if not arrived else arrived_reason}"
            ) if inputs.battery_soc is not None else "paid_grid_avoidance_required: SOC unavailable during paid time"
        elif arrived:
            reason = f"paid grid avoidance not required: solar arrived: {arrived_reason}"
    target = max(reserve_soc, floor) if required or forecast_drain_blocked else reserve_soc
    return required, reason, floor, target, arrived, arrived_reason, forecast_drain_blocked


def hours_until_time(now: datetime, target: str) -> float:
    """Return local hours until the next occurrence of a target time."""

    target_time = time.fromisoformat(target)
    target_dt = now.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
    if target_dt <= now:
        target_dt += timedelta(days=1)
    return (target_dt - now).total_seconds() / 3600.0


def hours_until_solar_end(now: datetime) -> float:
    """Return local daylight-budget hours remaining until 17:00."""

    if not time_between(now, "06:55", "17:00"):
        return 0.0
    end = now.replace(hour=17, minute=0, second=0, microsecond=0)
    return max((end - now).total_seconds() / 3600.0, 0.0)


def load_energy_cost_kwh(load: HeatLoadState, settings: EnergyManagerSettings) -> float:
    """Return minimum energy budget needed to start a discretionary load."""

    return (load.estimated_load_w / 1000.0) * max(settings.min_thermal_run_minutes / 60.0, 0.25)


def load_comfort_min_temp(load: HeatLoadState, settings: EnergyManagerSettings) -> float:
    """Return per-load comfort minimum."""

    if is_underfloor_load(load):
        return load.comfort_min_temp if load.comfort_min_temp is not None else settings.underfloor_comfort_min_temp
    return load.comfort_min_temp if load.comfort_min_temp is not None else settings.comfort_min_room_temp


def load_comfort_target_temp(load: HeatLoadState | None, settings: EnergyManagerSettings) -> float:
    """Return per-load comfort target."""

    if load is not None and is_underfloor_load(load):
        return load.comfort_target_temp if load.comfort_target_temp is not None else settings.underfloor_comfort_target_temp
    return load.comfort_target_temp if load is not None and load.comfort_target_temp is not None else settings.heat_comfort_target_temp


def load_normal_target_temp(load: HeatLoadState, settings: EnergyManagerSettings) -> float:
    """Return per-load normal target."""

    if is_underfloor_load(load):
        return load.normal_target_temp if load.normal_target_temp is not None else settings.underfloor_comfort_target_temp
    return load.normal_target_temp if load.normal_target_temp is not None else settings.heat_normal_target_temp


def underfloor_window_state(now: datetime, settings: EnergyManagerSettings) -> tuple[bool, bool, str]:
    """Return active/preheat status and window name for underfloor comfort."""

    morning_start = settings.underfloor_morning_start_hour
    evening_start = settings.underfloor_evening_start_hour
    preheat_h = settings.underfloor_preheat_minutes / 60.0
    morning_preheat = (morning_start - preheat_h) % 24
    evening_preheat = (evening_start - preheat_h) % 24
    if time_between(now, time_from_hour(morning_start), time_from_hour(settings.underfloor_morning_end_hour)):
        return True, False, "morning"
    if time_between(now, time_from_hour(evening_start), time_from_hour(settings.underfloor_evening_end_hour)):
        return True, False, "evening"
    if time_between(now, time_from_hour(morning_preheat), time_from_hour(morning_start)):
        return False, True, "morning_preheat"
    if time_between(now, time_from_hour(evening_preheat), time_from_hour(evening_start)):
        return False, True, "evening_preheat"
    return False, False, "outside"


def underfloor_comfort_decision(
    inputs: EnergyManagerInputs,
    settings: EnergyManagerSettings,
    paid_grid_avoidance_required: bool,
    discretionary_budget_kwh: float | None,
) -> tuple[bool, str, str, str | None, str]:
    """Return scheduled underfloor comfort decision details."""

    underfloor_loads = [load for load in inputs.heat_loads if load.enabled and is_underfloor_load(load)]
    if not underfloor_loads:
        return False, "unavailable", "underfloor_unavailable: no configured underfloor load", None, "outside"
    load = sorted(underfloor_loads, key=lambda item: item.priority)[0]
    active, preheat, window = underfloor_window_state(inputs.now, settings)
    temp = load.current_temp
    min_temp = load.comfort_min_temp if load.comfort_min_temp is not None else settings.underfloor_comfort_min_temp
    target_temp = load.comfort_target_temp if load.comfort_target_temp is not None else settings.underfloor_comfort_target_temp
    if not settings.underfloor_schedule_enabled:
        return False, "disabled", "underfloor_blocked: schedule disabled", None, window
    if temp is None:
        return False, "unavailable", "underfloor_blocked: floor temperature unavailable", None, window
    if paid_grid_avoidance_required and not settings.underfloor_allow_paid_grid:
        return False, "blocked", "underfloor_blocked: paid grid avoidance active", None, window
    if inputs.battery_soc is None or inputs.battery_soc < settings.underfloor_min_soc:
        return False, "blocked", f"underfloor_blocked: SOC {inputs.battery_soc if inputs.battery_soc is not None else 'unavailable'} < {settings.underfloor_min_soc:.0f}%", None, window
    if max(inputs.grid_power_w, 0.0) > settings.underfloor_max_grid_import_w:
        return False, "blocked", f"underfloor_blocked: grid import {max(inputs.grid_power_w, 0.0):.0f}W > {settings.underfloor_max_grid_import_w:.0f}W", None, window
    if active:
        if temp >= target_temp:
            return False, "hold", f"underfloor_comfort_hold: floor {temp:.1f}C near target {target_temp:.1f}C", None, window
        if temp < min_temp:
            return True, "scheduled_underfloor_comfort", f"underfloor_comfort_allowed: {window} schedule active, floor {temp:.1f}C < {min_temp:.1f}C, target {target_temp:.1f}C", load.name, window
        return False, "hold", f"underfloor_comfort_hold: floor {temp:.1f}C above minimum {min_temp:.1f}C", None, window
    if preheat:
        if temp < target_temp and discretionary_budget_kwh is not None and discretionary_budget_kwh >= load_energy_cost_kwh(load, settings):
            return True, "scheduled_underfloor_comfort", f"underfloor_comfort_allowed: {window} and budget {discretionary_budget_kwh:.1f}kWh, floor {temp:.1f}C < target {target_temp:.1f}C", load.name, window
        return False, "blocked", "underfloor_blocked: preheat window but discretionary budget insufficient", None, window
    return False, "blocked", "underfloor_blocked: outside comfort window", None, window


def resolve_soc_value(
    raw_soc: str | None,
    fallback_soc: float | None,
    fallback_updated: datetime | None,
    now: datetime,
    max_age_minutes: float,
) -> tuple[float | None, str, float | None]:
    """Resolve live/fallback SOC without converting unknown values to zero."""

    try:
        if raw_soc not in {None, "unknown", "unavailable", ""}:
            return float(raw_soc), "live", 0.0
    except (TypeError, ValueError):
        pass

    if fallback_soc is not None and fallback_updated is not None:
        age_minutes = max((now - fallback_updated).total_seconds() / 60.0, 0.0)
        if age_minutes <= max_age_minutes:
            return fallback_soc, "last_known_good", age_minutes
        return None, "unavailable", age_minutes

    return None, "unavailable", None


def projected_soc_at_08(inputs: EnergyManagerInputs, settings: EnergyManagerSettings) -> float | None:
    """Project SOC at 08:00 from current discharge rate."""

    if inputs.battery_soc is None:
        return None
    if not time_between(inputs.now, "21:00", "08:00"):
        return None
    battery_discharge_w = max(inputs.battery_power_w, 0.0)
    if battery_discharge_w <= 0 or settings.battery_capacity_kwh <= 0:
        return inputs.battery_soc
    discharge_kwh = battery_discharge_w * hours_until_time(inputs.now, "08:00") / 1000.0
    return max(inputs.battery_soc - (discharge_kwh / settings.battery_capacity_kwh * 100.0), 0.0)


def effective_thermal_mode(
    settings: EnergyManagerSettings,
    now: datetime | None = None,
    outdoor_temperature: float | None = None,
) -> str:
    """Return the concrete thermal mode."""

    if settings.thermal_mode == "auto":
        if outdoor_temperature is not None:
            if outdoor_temperature <= settings.auto_heating_below_temp:
                return "heating"
            if outdoor_temperature >= settings.auto_cooling_above_temp:
                return "cooling"
            return "off"
        if settings.auto_mode_month_fallback_enabled and now is not None:
            if now.month in {4, 5, 6, 7, 8, 9, 10, 3, 11}:
                return "heating"
            if now.month in {12, 1, 2}:
                return "cooling"
        return "heating"
    return settings.thermal_mode


def auto_mode_reason(settings: EnergyManagerSettings, now: datetime, outdoor_temperature: float | None) -> str:
    """Explain thermal auto-mode selection."""

    if settings.thermal_mode != "auto":
        return f"thermal mode fixed: {settings.thermal_mode}"
    if outdoor_temperature is not None:
        if outdoor_temperature <= settings.auto_heating_below_temp:
            return f"outdoor temp {outdoor_temperature:.1f} <= heating threshold {settings.auto_heating_below_temp:.1f}"
        if outdoor_temperature >= settings.auto_cooling_above_temp:
            return f"outdoor temp {outdoor_temperature:.1f} >= cooling threshold {settings.auto_cooling_above_temp:.1f}"
        return f"outdoor temp {outdoor_temperature:.1f} between thresholds; thermal idle"
    if settings.auto_mode_month_fallback_enabled:
        if now.month in {4, 5, 6, 7, 8, 9, 10, 3, 11}:
            return f"month fallback: month {now.month} in Southern Hemisphere heating season"
        if now.month in {12, 1, 2}:
            return f"month fallback: month {now.month} in Southern Hemisphere cooling season"
    return "auto fallback: heating"


def thermal_targets(settings: EnergyManagerSettings, mode: str | None = None) -> tuple[float, float]:
    """Return soak and normal target temperatures for the active thermal mode."""

    if (mode or effective_thermal_mode(settings)) == "cooling":
        return settings.cool_soak_target_temp, settings.cool_normal_target_temp
    return settings.heat_soak_target_temp, settings.heat_normal_target_temp


def thermal_hvac_mode(settings: EnergyManagerSettings, mode: str | None = None) -> str:
    """Return Home Assistant climate HVAC mode for the active thermal mode."""

    return "cool" if (mode or effective_thermal_mode(settings)) == "cooling" else "heat"


def thermal_fan_modes(settings: EnergyManagerSettings, mode: str | None = None) -> tuple[str, str]:
    """Return soak and normal fan modes for the active thermal mode."""

    if (mode or effective_thermal_mode(settings)) == "cooling":
        return settings.cool_soak_fan_mode, settings.cool_normal_fan_mode
    return settings.heat_soak_fan_mode, settings.heat_normal_fan_mode


def fan_mode_supported(load: HeatLoadState, fan_mode: str | None) -> bool:
    """Return whether a climate load supports a desired fan mode."""

    return bool(fan_mode and load.supported_fan_modes and fan_mode in load.supported_fan_modes)


def fan_mode_blocked_reason(load: HeatLoadState, fan_mode: str | None) -> str | None:
    """Return a diagnostic reason when a fan mode cannot be applied."""

    if not fan_mode:
        return "no fan mode selected"
    if not load.supported_fan_modes:
        return "climate does not expose fan_modes"
    if fan_mode not in load.supported_fan_modes:
        return f"fan mode {fan_mode} not in supported fan_modes"
    return None


def thermal_soak_action(settings: EnergyManagerSettings, load: HeatLoadState) -> tuple[str, float, str] | None:
    """Return direct climate action for soaking one load."""

    mode = effective_thermal_mode(settings)
    if not load_supports_mode(load, mode):
        return None
    soak_target, _normal_target = thermal_targets(settings)
    soak_fan_mode, _normal_fan_mode = thermal_fan_modes(settings, mode)
    return thermal_hvac_mode(settings, mode), soak_target, soak_fan_mode


def thermal_shed_action(settings: EnergyManagerSettings, load: HeatLoadState) -> tuple[str, float | None, str | None]:
    """Return direct climate action for shedding/normalising one load."""

    if not settings.return_to_normal_on_shed_enabled or is_underfloor_load(load):
        return "off", None, None
    _soak_target, normal_target = thermal_targets(settings)
    _soak_fan_mode, normal_fan_mode = thermal_fan_modes(settings)
    return thermal_hvac_mode(settings), normal_target, normal_fan_mode


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


def load_is_satisfied(load: HeatLoadState, settings: EnergyManagerSettings, mode: str | None = None) -> bool:
    """Return whether a thermal load is close to the soak target or tapering."""

    if is_underfloor_load(load) and not load.allow_solar_soak:
        return load.current_temp is not None and load.current_temp >= load_comfort_min_temp(load, settings)
    mode = mode or effective_thermal_mode(settings)
    soak_target, _normal_target = thermal_targets(settings, mode)
    if load.power_w is not None and load.solar_owned and load.is_on and load.power_w <= load.taper_power_threshold_w:
        return True
    if load.current_temp is None:
        return False
    if mode == "cooling":
        return load.current_temp <= soak_target + settings.room_satisfied_delta_c
    return load.current_temp >= soak_target - settings.room_satisfied_delta_c


def load_needs_soak(load: HeatLoadState, settings: EnergyManagerSettings, mode: str | None = None) -> bool:
    """Return whether a load still has useful thermal storage headroom."""

    if is_underfloor_load(load) and not load.allow_solar_soak:
        return False
    mode = mode or effective_thermal_mode(settings)
    soak_target, _normal_target = thermal_targets(settings, mode)
    if load.blocked_until is not None or not load_supports_mode(load, mode):
        return False
    if load.current_temp is None:
        return not load.solar_owned and not load.is_on
    if mode == "cooling":
        return load.current_temp > soak_target + settings.room_resume_delta_c
    return load.current_temp < soak_target - settings.room_resume_delta_c


def satisfied_heat_loads(loads: list[HeatLoadState], settings: EnergyManagerSettings, mode: str | None = None) -> list[HeatLoadState]:
    """Return solar-owned thermal loads close enough to soak target or tapering."""

    return [
        load
        for load in loads
        if load.solar_owned
        and load.is_on
        and load_is_satisfied(load, settings, mode)
    ]


def needy_heat_loads(loads: list[HeatLoadState], settings: EnergyManagerSettings, mode: str | None = None) -> list[HeatLoadState]:
    """Return off loads still materially away from soak target."""

    return [
        load
        for load in loads
        if load.blocked_until is None
        and load.owner not in {"manual", "external"}
        and load.manual_override_until is None
        and load.allow_solar_soak
        and not load.solar_owned
        and not load.is_on
        and load_needs_soak(load, settings, mode)
    ]


def comfort_heat_candidates(loads: list[HeatLoadState], settings: EnergyManagerSettings) -> list[HeatLoadState]:
    """Return loads cold enough for comfort heating."""

    return [
        load
        for load in loads
        if load.enabled
        and load.supports_heating
        and not is_underfloor_load(load)
        and load.blocked_until is None
        and load.owner not in {"manual", "external"}
        and load.manual_override_until is None
        and load.current_temp is not None
        and load.current_temp < load_comfort_min_temp(load, settings)
    ]


def morning_preheat_candidates(loads: list[HeatLoadState], settings: EnergyManagerSettings) -> list[HeatLoadState]:
    """Return bedroom loads cold enough for morning preheat."""

    return [
        load
        for load in loads
        if load.enabled
        and load.supports_heating
        and "bedroom" in f"{load.name} {load.slug or ''} {load.climate_entity or ''}".lower()
        and load.owner not in {"manual", "external"}
        and load.manual_override_until is None
        and load.current_temp is not None
        and load.current_temp < settings.morning_preheat_min_room_temp
    ]


def unowned_shed_reason(load: HeatLoadState, settings: EnergyManagerSettings, mode: str | None = None) -> str | None:
    """Return why an unowned configured load looks like a solar-soak load."""

    mode = mode or effective_thermal_mode(settings)
    if load.solar_owned or not load.enabled or not load.allow_unowned_battery_shed or is_underfloor_load(load) or not load_supports_mode(load, mode):
        return None
    soak_fan_mode, _normal_fan_mode = thermal_fan_modes(settings, mode)
    fan_high_modes = {soak_fan_mode, "high", "max", "maximum", "powerful", "turbo"}
    fan_matches = bool(load.fan_mode and load.fan_mode.lower() in {str(item).lower() for item in fan_high_modes if item})
    active_evidence = (
        load.hvac_action in {"heating", "cooling"}
        or (load.power_w is not None and load.power_w >= load.active_power_threshold_w)
    )
    tolerance = settings.room_satisfied_delta_c
    if mode == "cooling":
        if load.hvac_mode != "cool":
            return None
        if load.target_temp is not None and load.target_temp <= settings.cool_soak_target_temp + tolerance:
            return "cool target at soak setpoint"
        if fan_matches:
            return "cool fan mode looks like soak"
        if active_evidence:
            return "active cooling managed load"
        return None
    if load.hvac_mode != "heat":
        return None
    if load.target_temp is not None and load.target_temp >= settings.heat_soak_target_temp - tolerance:
        return "heat target at soak setpoint"
    if fan_matches:
        return "heat fan mode looks like soak"
    if active_evidence:
        return "active heating managed load"
    if (
        load.current_temp is not None
        and load.target_temp is not None
        and load.current_temp > settings.heat_normal_target_temp
        and load.target_temp > settings.heat_normal_target_temp
    ):
        return "room and target above normal heat target"
    return None


def unowned_shed_candidates(loads: list[HeatLoadState], settings: EnergyManagerSettings, mode: str | None = None) -> list[HeatLoadState]:
    """Return unowned managed loads safe to normalise when the battery is discharging."""

    return [load for load in loads if unowned_shed_reason(load, settings, mode)]


def minutes_since(now: datetime, value: datetime | None) -> float | None:
    if value is None:
        return None
    return (now - value).total_seconds() / 60.0


def cooldown_block_reason(load: HeatLoadState, settings: EnergyManagerSettings, now: datetime, for_action: str) -> str | None:
    """Return cooldown block reason for add/shed/rotate."""

    if for_action == "add":
        elapsed = minutes_since(now, load.last_shed_at)
        if elapsed is not None and elapsed < settings.min_thermal_rest_minutes:
            return f"blocked_by_cooldown: shed {elapsed:.0f}m ago, min rest {settings.min_thermal_rest_minutes:.0f}m"
    if for_action == "shed":
        elapsed = minutes_since(now, load.last_added_at)
        if elapsed is not None and elapsed < settings.min_thermal_run_minutes:
            return f"blocked_by_cooldown: added {elapsed:.0f}m ago, min run {settings.min_thermal_run_minutes:.0f}m"
    if for_action == "rotate":
        elapsed = minutes_since(now, load.last_rotated_at)
        if elapsed is not None and elapsed < settings.thermal_rotation_cooldown_minutes:
            return f"rotation blocked: rotated {elapsed:.0f}m ago, cooldown {settings.thermal_rotation_cooldown_minutes:.0f}m"
    return None


def thermal_load_diagnostic(
    load: HeatLoadState,
    settings: EnergyManagerSettings,
    inputs: EnergyManagerInputs,
    decision: EnergyManagerDecision | None = None,
) -> ThermalLoadDiagnostic:
    """Build a diagnostic status object for one thermal load."""

    mode = effective_thermal_mode(settings, inputs.now, inputs.outdoor_temperature)
    soak_target, normal_target = thermal_targets(settings, mode)
    if is_underfloor_load(load) and not load.allow_solar_soak:
        soak_target = load_comfort_target_temp(load, settings)
        normal_target = load_normal_target_temp(load, settings)
    blocked_by_mode = not load_supports_mode(load, mode)
    blocked_reason = None
    blocked_by_cooldown = False
    if load.blocked_until and load.blocked_until > inputs.now:
        blocked_reason = "manual_override"
    elif reason := cooldown_block_reason(load, settings, inputs.now, "add"):
        blocked_reason = reason
        blocked_by_cooldown = True
    elif blocked_by_mode:
        blocked_reason = "unsupported_mode"

    needs = load_needs_soak(load, settings, mode)
    satisfied = load_is_satisfied(load, settings, mode)
    active = load_is_active(load, mode)
    soak_fan_mode, normal_fan_mode = thermal_fan_modes(settings, mode)
    unowned_reason = unowned_shed_reason(load, settings, mode)
    tapering = bool(load.power_w is not None and load.is_on and load.power_w <= load.taper_power_threshold_w)
    if blocked_reason == "manual_override":
        state = "manual_override"
    elif blocked_by_cooldown:
        state = "cooldown"
    elif blocked_by_mode:
        state = "unsupported_mode"
    elif not load.enabled:
        state = "blocked"
    elif load.hvac_mode is None and load.current_temp is None:
        state = "unavailable"
    elif tapering:
        state = "tapering"
    elif satisfied:
        state = "satisfied"
    elif load.solar_owned and active:
        state = "soaking"
    elif needs:
        state = "needs_soak"
    else:
        state = "idle"

    chosen_add = decision is not None and decision.thermal_load_to_add == load.name
    chosen_shed = decision is not None and decision.thermal_load_to_shed == load.name
    attrs: dict[str, object | None] = {
        "load_slug": load.slug or slugify(load.name),
        "load_name": load.name,
        "climate_entity": load.climate_entity,
        "ownership_entity": load.ownership_entity,
        "enabled": load.enabled,
        "priority": load.priority,
        "thermal_mode": mode,
        "supports_heating": load.supports_heating,
        "supports_cooling": load.supports_cooling,
        "current_temperature": load.current_temp,
        "target_temperature": load.target_temp,
        "soak_target_temperature": soak_target,
        "normal_target_temperature": normal_target,
        "hvac_mode": load.hvac_mode,
        "hvac_action": load.hvac_action,
        "current_fan_mode": load.fan_mode,
        "supported_fan_modes": list(load.supported_fan_modes),
        "desired_soak_fan_mode": soak_fan_mode,
        "desired_normal_fan_mode": normal_fan_mode,
        "fan_mode_supported": fan_mode_supported(load, soak_fan_mode) or fan_mode_supported(load, normal_fan_mode),
        "fan_mode_action": "set_fan_mode" if chosen_add or chosen_shed else "none",
        "fan_mode_blocked_reason": fan_mode_blocked_reason(load, soak_fan_mode if chosen_add else normal_fan_mode if chosen_shed else soak_fan_mode),
        "power_sensor": load.power_sensor,
        "power_w": load.power_w,
        "estimated_load_w": load.estimated_load_w,
        "estimated_min_run_energy_kwh": load_energy_cost_kwh(load, settings),
        "allow_solar_soak": load.allow_solar_soak,
        "comfort_sensor_type": load.comfort_sensor_type,
        "comfort_min_temp": load_comfort_min_temp(load, settings),
        "comfort_target_temp": load_comfort_target_temp(load, settings),
        "normal_target_temp": load.normal_target_temp,
        "underfloor_policy_state": decision.underfloor_policy_state if decision and is_underfloor_load(load) else None,
        "underfloor_reason": decision.underfloor_reason if decision and is_underfloor_load(load) else None,
        "underfloor_current_window": decision.underfloor_current_window if decision and is_underfloor_load(load) else None,
        "active_state": "active" if active else "idle",
        "owned_by_manager": load.solar_owned,
        "owner": load.owner,
        "lease_reason": load.lease_reason,
        "lease_until": load.lease_until.isoformat() if load.lease_until else None,
        "manual_override": bool(load.manual_override_until and load.manual_override_until > inputs.now),
        "manual_override_until": load.manual_override_until.isoformat() if load.manual_override_until else None,
        "pending_confirmation": bool(load.pending_confirmation_until and load.pending_confirmation_until > inputs.now),
        "pending_confirmation_until": load.pending_confirmation_until.isoformat() if load.pending_confirmation_until else None,
        "desired_hvac_mode": load.desired_hvac_mode,
        "desired_temperature": load.desired_temperature,
        "desired_fan_mode": load.desired_fan_mode,
        "normal_temperature": load.normal_temperature,
        "normal_fan_mode": load.normal_fan_mode,
        "external_change_detected": load.external_change_detected,
        "shed_candidate": chosen_shed,
        "allow_unowned_battery_shed": load.allow_unowned_battery_shed,
        "never_emergency_shed": load.never_emergency_shed,
        "unowned_shed_candidate": bool(unowned_reason),
        "unowned_shed_reason": unowned_reason,
        "needs_soak": needs,
        "satisfied": satisfied,
        "tapering": tapering,
        "blocked_by_manual_override": blocked_reason == "manual_override",
        "blocked_by_cooldown": blocked_by_cooldown,
        "blocked_by_mode": blocked_by_mode,
        "blocked_reason": blocked_reason,
        "last_added_at": load.last_added_at.isoformat() if load.last_added_at else None,
        "last_shed_at": load.last_shed_at.isoformat() if load.last_shed_at else None,
        "last_rotated_at": load.last_rotated_at.isoformat() if load.last_rotated_at else None,
        "last_action": load.last_action,
        "last_action_reason": load.last_action_reason,
        "chosen_for_add": chosen_add,
        "chosen_for_shed": chosen_shed,
        "chosen_for_rotation": bool(decision and decision.thermal_rotation_recommended and (chosen_add or chosen_shed)),
        "not_chosen_reason": None if chosen_add or chosen_shed else blocked_reason or ("does_not_need_soak" if not needs and not satisfied else "lower_priority_or_no_action"),
    }
    return ThermalLoadDiagnostic(slug=load.slug or slugify(load.name), state=state, attributes=attrs)


def thermal_load_diagnostics(
    inputs: EnergyManagerInputs,
    settings: EnergyManagerSettings,
    decision: EnergyManagerDecision,
) -> dict[str, ThermalLoadDiagnostic]:
    """Build all per-load diagnostics without allowing one failure to break decisions."""

    diagnostics: dict[str, ThermalLoadDiagnostic] = {}
    for load in inputs.heat_loads:
        slug = load.slug or slugify(load.name)
        try:
            diagnostic = thermal_load_diagnostic(load, settings, inputs, decision)
        except Exception as err:
            diagnostic = ThermalLoadDiagnostic(
                slug=slug,
                state="unavailable",
                attributes={
                    "load_slug": slug,
                    "load_name": load.name,
                    "climate_entity": load.climate_entity,
                    "ownership_entity": load.ownership_entity,
                    "blocked_reason": "diagnostic_error",
                    "diagnostic_error": str(err),
                },
            )
        diagnostics[diagnostic.slug] = diagnostic
    return diagnostics


def slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_").replace("__", "_")


def forecast_full_override_active(
    inputs: EnergyManagerInputs,
    settings: EnergyManagerSettings,
    tier: ForecastTier,
) -> bool:
    """Return whether forecast is strong enough to start thermal storage early."""

    remaining = inputs.forecast_remaining_today_kwh
    if remaining is None or inputs.battery_soc is None:
        return False
    required_kwh = max(tier.target_17_soc - inputs.battery_soc, 0.0) / 100.0 * settings.battery_capacity_kwh
    return (
        settings.forecast_full_override_enabled
        and tier.mode in {"excellent", "good"}
        and remaining >= required_kwh + settings.forecast_full_confidence_buffer_kwh
    )


def ev_decision(
    inputs: EnergyManagerInputs,
    settings: EnergyManagerSettings,
    cheap_window: bool,
    battery_priority_satisfied: bool,
    forecast_override: bool,
) -> tuple[bool, bool, bool, bool, str, str, float | None, datetime | None]:
    """Return EV detection, bypass, solar permission, latch, reason, action, power, hold."""

    essential_jump_w = None
    if inputs.previous_essential_power_w is not None:
        essential_jump_w = inputs.essential_power_w - inputs.previous_essential_power_w

    power_detected = inputs.ev_power_w is not None and inputs.ev_power_w > settings.ev_active_load_threshold_w
    jump_detected = essential_jump_w is not None and essential_jump_w >= settings.ev_start_load_jump_w
    high_load_detected = inputs.ev_power_w is None and cheap_window and inputs.essential_power_w > 6500.0
    porsche_status_detected = (inputs.porsche_charging_status or "").lower() == "charging"
    ev_charging_detected = power_detected or jump_detected or high_load_detected or (
        porsche_status_detected and inputs.ev_latch_on
    )

    low_power_stopped = (
        inputs.ev_power_w is not None
        and inputs.ev_power_w < settings.ev_stopped_load_threshold_w
        and inputs.ev_low_since is not None
        and (inputs.now - inputs.ev_low_since) >= timedelta(minutes=2)
    )
    load_drop_stopped = essential_jump_w is not None and essential_jump_w <= -settings.ev_stop_load_drop_w
    soc_stopped = inputs.porsche_soc is not None and inputs.porsche_soc >= 99.0
    hold_expired_low = (
        inputs.ev_hold_until is not None
        and inputs.now >= inputs.ev_hold_until
        and inputs.essential_power_w < 2500.0
        and (inputs.ev_power_w is None or inputs.ev_power_w < settings.ev_active_load_threshold_w)
    )
    failsafe_0700 = inputs.ev_latch_on and not cheap_window
    ev_stop = inputs.manual_clear_ev_latch or low_power_stopped or load_drop_stopped or soc_stopped or hold_expired_low or failsafe_0700

    ev_grid_bypass_required = (
        settings.enabled
        and settings.ev_control_enabled
        and settings.ev_grid_bypass_enabled
        and settings.ev_cheap_grid_charging_enabled
        and cheap_window
        and not ev_stop
        and (inputs.ev_latch_on or ev_charging_detected)
    )
    ev_latch_active = ev_grid_bypass_required

    hold_until = inputs.ev_hold_until
    if ev_grid_bypass_required and hold_until is None:
        if inputs.porsche_charging_ends and inputs.porsche_charging_ends > inputs.now:
            hold_until = inputs.porsche_charging_ends + timedelta(minutes=settings.ev_hold_extra_minutes)
        else:
            hold_until = inputs.now + timedelta(minutes=settings.ev_fallback_hold_minutes)
    if ev_stop:
        hold_until = None
        ev_latch_active = False

    ev_solar_charge_allowed = (
        settings.enabled
        and settings.ev_control_enabled
        and settings.ev_solar_charging_enabled
        and battery_priority_satisfied
        and forecast_override
        and settings.flexible_load_priority in {"ev_before_thermal", "battery_first"}
    )

    action = "none"
    if ev_stop and inputs.ev_latch_on:
        action = "ev_grid_bypass_restore"
    elif ev_grid_bypass_required and not inputs.ev_latch_on:
        action = "ev_grid_bypass_start"
    elif ev_grid_bypass_required:
        action = "ev_grid_bypass_hold"
    elif ev_solar_charge_allowed:
        action = "allow_solar_charge"

    if power_detected:
        reason = f"EV charging detected: EV power {inputs.ev_power_w:.0f}W > {settings.ev_active_load_threshold_w:.0f}W"
    elif jump_detected:
        reason = f"EV charging inferred: essential load jump {essential_jump_w:.0f}W >= {settings.ev_start_load_jump_w:.0f}W"
    elif high_load_detected:
        reason = f"EV charging inferred: essential load {inputs.essential_power_w:.0f}W high in cheap window"
    elif ev_stop:
        reason = "EV stop condition active"
    elif ev_solar_charge_allowed:
        reason = "EV solar charge allowed: battery priority satisfied and forecast override active"
    else:
        reason = "EV idle"

    return (
        ev_charging_detected,
        ev_grid_bypass_required,
        ev_solar_charge_allowed,
        ev_latch_active,
        reason,
        action,
        inputs.ev_power_w,
        hold_until,
    )


def decide(inputs: EnergyManagerInputs, settings: EnergyManagerSettings | None = None) -> EnergyManagerDecision:
    """Calculate the current energy-management decision."""

    settings = settings or EnergyManagerSettings()
    tier = forecast_tier(inputs.forecast_tomorrow_kwh, settings)
    reserve_soc = current_reserve_soc(inputs.now, tier)
    battery_charge_w = max(-inputs.battery_power_w, 0.0)
    battery_discharge_w = max(inputs.battery_power_w, 0.0)
    soc_known = inputs.battery_soc is not None
    soc = inputs.battery_soc
    cheap_window = time_between(inputs.now, "21:00", "07:00")
    control_blocked = not settings.enabled
    thermal_mode = effective_thermal_mode(settings, inputs.now, inputs.outdoor_temperature)
    auto_reason = auto_mode_reason(settings, inputs.now, inputs.outdoor_temperature)
    thermal_control_enabled = settings.thermal_control_enabled or settings.heat_control_enabled
    thermal_start_min_soc = settings.thermal_start_min_soc
    thermal_start_min_charge_w = settings.thermal_start_min_charge_w
    thermal_shed_discharge_w = settings.thermal_shed_discharge_w
    phase = solar_phase(inputs.now)
    forecast_override = forecast_full_override_active(inputs, settings, tier)
    expected_pv_power_w = max(
        inputs.pv_power_now_w or 0.0,
        inputs.pv_power_in_30_minutes_w or 0.0,
        inputs.pv_power_in_1_hour_w or 0.0,
    )
    remaining_forecast_kwh = inputs.forecast_remaining_today_kwh
    if remaining_forecast_kwh is None:
        remaining_forecast_kwh = max((inputs.forecast_tomorrow_kwh or 0.0) / 3.0, 0.0)
    base_load_w = inputs.base_load_estimate_w if inputs.base_load_estimate_w is not None else settings.base_load_estimate_w
    solar_hours_remaining = hours_until_solar_end(inputs.now)
    expected_house_load_kwh = base_load_w * solar_hours_remaining / 1000.0 + settings.house_load_forecast_buffer_kwh
    battery_kwh_needed = None
    if soc_known:
        efficiency = max(min(settings.battery_charge_efficiency, 1.0), 0.5)
        battery_kwh_needed = (
            settings.battery_capacity_kwh
            * max(settings.daily_battery_target_soc - (soc or 0.0), 0.0)
            / 100.0
            / efficiency
        )
    committed_flexible_kwh = sum(
        load_energy_cost_kwh(load, settings)
        for load in inputs.heat_loads
        if load.solar_owned or load.lease_reason in {"solar_soak", "morning_preheat", "comfort_heat"}
    )
    safety_buffer_kwh = settings.forecast_safety_buffer_kwh + settings.solar_soak_required_battery_margin_kwh
    if settings.paid_time_grid_avoidance_enabled:
        safety_buffer_kwh += settings.paid_grid_avoidance_buffer_kwh
    discretionary_budget_kwh = None
    if battery_kwh_needed is not None:
        discretionary_budget_kwh = (
            remaining_forecast_kwh
            - battery_kwh_needed
            - expected_house_load_kwh
            - safety_buffer_kwh
            - committed_flexible_kwh
        )
    battery_target_reachable = (
        discretionary_budget_kwh is not None
        and remaining_forecast_kwh >= battery_kwh_needed + expected_house_load_kwh + safety_buffer_kwh
    )
    discretionary_budget_positive = discretionary_budget_kwh is not None and discretionary_budget_kwh > 0
    if discretionary_budget_kwh is None:
        energy_budget_reason = "energy budget unavailable: SOC unavailable"
    else:
        energy_budget_reason = (
            f"budget {discretionary_budget_kwh:.1f}kWh = forecast {remaining_forecast_kwh:.1f}kWh "
            f"- battery need {battery_kwh_needed:.1f}kWh to {settings.daily_battery_target_soc:.0f}% "
            f"- house load {expected_house_load_kwh:.1f}kWh - buffer {safety_buffer_kwh:.1f}kWh "
            f"- committed flexible {committed_flexible_kwh:.1f}kWh"
        )

    (
        paid_grid_avoidance_required,
        paid_time_reserve_reason,
        paid_floor,
        active_reserve_target_soc,
        solar_has_arrived,
        solar_arrived_reason,
        forecast_drain_blocked,
    ) = paid_grid_avoidance_state(inputs, settings, reserve_soc, battery_charge_w)
    if paid_grid_avoidance_required and discretionary_budget_kwh is not None:
        discretionary_budget_kwh = min(discretionary_budget_kwh, -settings.paid_grid_avoidance_buffer_kwh)
        discretionary_budget_positive = False
        battery_target_reachable = False
        energy_budget_reason = f"budget blocked by paid grid avoidance; {energy_budget_reason}"
    (
        underfloor_comfort_allowed,
        underfloor_policy_state,
        underfloor_reason,
        underfloor_load_to_add,
        underfloor_current_window,
    ) = underfloor_comfort_decision(inputs, settings, paid_grid_avoidance_required, discretionary_budget_kwh)

    pre_peak_preserve_required = (
        time_between(inputs.now, "13:00", "17:00")
        and soc_known
        and soc < tier.target_17_soc
        and battery_charge_w < settings.heat_add_min_charge_w
    )

    battery_priority_satisfied = battery_target_reachable or (soc_known and soc >= settings.daily_battery_target_soc)
    curtailment_likely = (
        (soc_known and soc >= settings.full_soak_min_soc)
        or (
            battery_charge_w <= settings.pv_load_test_max_battery_charge_w
            and expected_pv_power_w - inputs.essential_power_w >= settings.solar_arrived_pv_surplus_threshold_w
        )
    )
    passive_warming_likely = (
        settings.passive_warming_guard_enabled
        and bool(inputs.heat_loads)
        and not inputs.any_solar_owned_heat_load_on
        and phase in {"morning_battery_priority", "midday_balance"}
        and expected_pv_power_w >= settings.pv_load_test_min_expected_power_w
        and soc_known
        and soc < settings.full_soak_min_soc
        and all(
            load.current_temp is None or load.current_temp >= settings.heat_comfort_target_temp
            for load in inputs.heat_loads
            if load.enabled and load.supports_heating
        )
    )
    passive_warming_reason = (
        f"passive warming likely: expected PV {expected_pv_power_w:.0f}W and rooms at/above comfort while SOC {soc:.0f}% < {settings.full_soak_min_soc:.0f}%"
        if passive_warming_likely and soc_known
        else "passive warming not limiting"
    )

    potential_soak_costs = [
        load_energy_cost_kwh(load, settings) + settings.solar_soak_required_battery_margin_kwh
        for load in needy_heat_loads(inputs.heat_loads, settings, thermal_mode)
        if cooldown_block_reason(load, settings, inputs.now, "add") is None
    ]
    smallest_soak_load_cost_kwh = min(potential_soak_costs) if potential_soak_costs else None
    discretionary_budget_fits_soak_load = (
        discretionary_budget_kwh is not None
        and discretionary_budget_kwh > 0
        and smallest_soak_load_cost_kwh is not None
        and discretionary_budget_kwh >= smallest_soak_load_cost_kwh
    )
    forecast_soak_allowed = battery_target_reachable and discretionary_budget_fits_soak_load
    solar_soak_allowed = (
        not paid_grid_avoidance_required
        and not passive_warming_likely
        and battery_discharge_w < thermal_shed_discharge_w
        and forecast_soak_allowed
    )
    full_send_soak_allowed = (
        not paid_grid_avoidance_required
        and not passive_warming_likely
        and battery_target_reachable
        and discretionary_budget_kwh is not None
        and (
            discretionary_budget_kwh >= 8.0
            or (soc_known and soc >= settings.full_soak_min_soc)
            or (phase == "afternoon_soak" and discretionary_budget_kwh >= 3.0)
        )
    )

    comfort_candidates = sorted(comfort_heat_candidates(inputs.heat_loads, settings), key=lambda load: load.priority)
    comfort_heat_allowed = thermal_mode == "heating" and bool(comfort_candidates) and not paid_grid_avoidance_required

    preheat_window = time_between(
        inputs.now,
        f"{int(settings.morning_preheat_start_hour):02d}:{int((settings.morning_preheat_start_hour % 1) * 60):02d}",
        f"{int(settings.morning_preheat_end_hour):02d}:{int((settings.morning_preheat_end_hour % 1) * 60):02d}",
    )
    preheat_candidates = sorted(morning_preheat_candidates(inputs.heat_loads, settings), key=lambda load: load.priority)
    preheat_energy_kwh = (preheat_candidates[0].estimated_load_w / 1000.0 * max(settings.morning_preheat_end_hour - settings.morning_preheat_start_hour, 1.0)) if preheat_candidates else 0.0
    required_battery_energy_kwh = max(tier.target_17_soc - (soc or 0.0), 0.0) / 100.0 * settings.battery_capacity_kwh if soc_known else settings.battery_capacity_kwh
    morning_preheat_allowed = (
        settings.enabled
        and settings.morning_preheat_enabled
        and thermal_control_enabled
        and preheat_window
        and bool(preheat_candidates)
        and soc_known
        and soc >= settings.morning_preheat_min_soc
        and max(inputs.grid_power_w, 0.0) <= settings.morning_preheat_max_grid_import_w
        and remaining_forecast_kwh >= required_battery_energy_kwh + preheat_energy_kwh + settings.morning_preheat_forecast_buffer_kwh
        and battery_discharge_w < thermal_shed_discharge_w
    )
    if not preheat_window:
        morning_preheat_reason = "morning_preheat_blocked: outside preheat window"
    elif not preheat_candidates:
        morning_preheat_reason = "morning_preheat_blocked: bedroom already comfortable"
    elif not soc_known or soc < settings.morning_preheat_min_soc:
        morning_preheat_reason = f"morning_preheat_blocked: SOC {soc if soc is not None else 'unavailable'} < {settings.morning_preheat_min_soc:.0f}%"
    elif max(inputs.grid_power_w, 0.0) > settings.morning_preheat_max_grid_import_w:
        morning_preheat_reason = f"morning_preheat_blocked: grid import {max(inputs.grid_power_w, 0.0):.0f}W > {settings.morning_preheat_max_grid_import_w:.0f}W"
    elif remaining_forecast_kwh < required_battery_energy_kwh + preheat_energy_kwh + settings.morning_preheat_forecast_buffer_kwh:
        morning_preheat_reason = "morning_preheat_blocked: forecast recovery insufficient"
    else:
        morning_preheat_reason = f"morning_preheat_allowed: {preheat_candidates[0].name} {preheat_candidates[0].current_temp:.1f}C < {settings.morning_preheat_min_room_temp:.1f}C, SOC {soc:.0f}%, forecast recovery OK"

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
        and solar_soak_allowed
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
    unowned_candidates = sorted(
        unowned_shed_candidates(inputs.heat_loads, settings, thermal_mode),
        key=lambda load: load.priority,
        reverse=True,
    )
    unowned_shed_allowed = (
        settings.shed_unowned_managed_loads_on_battery_discharge
        and battery_discharge_w >= thermal_shed_discharge_w
        and bool(unowned_candidates)
    )
    discharge_shed_required = settings.enabled and battery_discharge_w >= thermal_shed_discharge_w

    thermal_should_shed = (
        discharge_shed_required
        or (
            inputs.any_solar_owned_heat_load_on
            and (
                (
                    not forecast_override
                    and soc_known
                    and soc < thermal_start_min_soc
                    and battery_charge_w < settings.thermal_keep_running_min_charge_w
                )
                or (
                    pre_peak_preserve_required
                    and not forecast_override
                    and soc_known
                    and soc < thermal_start_min_soc
                )
                or overnight_protection_required
            )
        )
    )

    thermal_should_emergency_shed = (
        settings.enabled
        and (
            battery_discharge_w >= settings.thermal_emergency_shed_w
            or battery_discharge_w >= settings.emergency_shed_discharge_w
        )
    )
    emergency_unowned_candidates = [load for load in unowned_candidates if not load.never_emergency_shed]
    pv_load_test_recommended = (
        settings.enabled
        and settings.export_limited_mode_enabled
        and inputs.heat_available
        and time_between(inputs.now, "08:00", "16:30")
        and not inputs.any_solar_owned_heat_load_on
        and not pre_peak_preserve_required
        and soc_known
        and soc >= settings.pv_load_test_min_soc
        and soc < tier.target_17_soc
        and discretionary_budget_positive
        and battery_charge_w <= settings.pv_load_test_max_battery_charge_w
        and expected_pv_power_w >= settings.pv_load_test_min_expected_power_w
        and remaining_forecast_kwh >= settings.pv_load_test_min_remaining_forecast_kwh
        and battery_discharge_w < 200.0
    )

    shed_candidates = sorted(
        [
            load
            for load in satisfied_heat_loads(inputs.heat_loads, settings, thermal_mode)
            if cooldown_block_reason(load, settings, inputs.now, "shed") is None
        ],
        key=lambda load: load.priority,
        reverse=True,
    )
    add_candidates = sorted(
        [
            load
            for load in needy_heat_loads(inputs.heat_loads, settings, thermal_mode)
            if cooldown_block_reason(load, settings, inputs.now, "add") is None
            and (
                discretionary_budget_kwh is not None
                and discretionary_budget_kwh >= load_energy_cost_kwh(load, settings) + settings.solar_soak_required_battery_margin_kwh
            )
        ],
        key=lambda load: load.priority,
    )
    thermal_load_to_shed = (
        shed_candidates[0].name
        if shed_candidates
        else emergency_unowned_candidates[0].name
        if thermal_should_emergency_shed and emergency_unowned_candidates
        else unowned_candidates[0].name
        if unowned_shed_allowed
        else None
    )
    morning_preheat_load_to_add = preheat_candidates[0].name if morning_preheat_allowed else None
    comfort_load_to_add = comfort_candidates[0].name if comfort_heat_allowed else None
    solar_soak_load_to_add = add_candidates[0].name if add_candidates else None
    thermal_load_to_add = morning_preheat_load_to_add or underfloor_load_to_add or comfort_load_to_add or (solar_soak_load_to_add if thermal_allowed else None)
    comfort_load = next((load for load in comfort_candidates if load.name == comfort_load_to_add), None)
    underfloor_load = next((load for load in inputs.heat_loads if load.name == underfloor_load_to_add), None)
    thermal_rotation_recommended = (
        thermal_allowed
        and settings.thermal_rotation_enabled
        and inputs.heat_available
        and bool(shed_candidates)
        and bool(add_candidates)
        and thermal_load_to_shed is not None
        and thermal_load_to_add is not None
        and cooldown_block_reason(shed_candidates[0], settings, inputs.now, "rotate") is None
        and cooldown_block_reason(add_candidates[0], settings, inputs.now, "rotate") is None
    )
    thermal_load_to_normalise = thermal_load_to_shed if thermal_should_shed else None
    solar_owned_count = sum(1 for load in inputs.heat_loads if load.solar_owned)
    active_thermal_loads = [load.name for load in inputs.heat_loads if load.solar_owned and load_is_active(load, thermal_mode)]
    thermal_should_return_to_normal = thermal_should_shed and settings.return_to_normal_on_shed_enabled

    (
        ev_charging_detected,
        ev_grid_bypass_required,
        ev_solar_charge_allowed,
        ev_latch_active,
        ev_reason,
        ev_action,
        ev_detected_power_w,
        ev_hold_until,
    ) = ev_decision(inputs, settings, cheap_window, battery_priority_satisfied, forecast_override)
    if not discretionary_budget_positive and ev_solar_charge_allowed:
        ev_solar_charge_allowed = False
        ev_reason = f"EV solar charge blocked: {energy_budget_reason}"
        if ev_action == "allow_solar_charge":
            ev_action = "none"
    ev_grid_mode_required = ev_grid_bypass_required

    grid_charge_required = (
        settings.enabled
        and settings.grid_charge_control_enabled
        and time_between(inputs.now, "03:00", "07:00")
        and tier.grid_charge_target_soc > 0
        and soc_known
        and soc < tier.grid_charge_target_soc - 1.0
        and not (ev_grid_bypass_required or inputs.ev_latch_on)
    )

    thermal_action = "none"
    shed_blocked_no_loads = thermal_should_shed and not inputs.any_solar_owned_heat_load_on and thermal_load_to_shed is None
    if thermal_should_emergency_shed and not shed_blocked_no_loads:
        thermal_action = "emergency_shed_all"
    elif thermal_rotation_recommended:
        thermal_action = "rotate"
    elif shed_blocked_no_loads:
        thermal_action = "shed_blocked_no_owned_loads"
    elif thermal_should_shed:
        thermal_action = "return_to_normal" if settings.return_to_normal_on_shed_enabled else "shed_one"
    elif morning_preheat_allowed and thermal_load_to_add:
        thermal_action = "morning_preheat"
    elif underfloor_comfort_allowed and thermal_load_to_add:
        thermal_action = "underfloor_comfort"
    elif comfort_heat_allowed and thermal_load_to_add:
        thermal_action = "comfort_heat"
    elif thermal_allowed and thermal_load_to_add:
        thermal_action = "add_one"
    elif thermal_allowed:
        thermal_action = "hold"

    thermal_policy_state = "battery_priority"
    if thermal_should_emergency_shed:
        thermal_policy_state = "emergency_shed"
    elif thermal_should_shed:
        thermal_policy_state = "shed"
    elif paid_grid_avoidance_required:
        thermal_policy_state = "battery_priority"
    elif morning_preheat_allowed:
        thermal_policy_state = "morning_preheat"
    elif underfloor_comfort_allowed:
        thermal_policy_state = "underfloor_comfort"
    elif comfort_heat_allowed:
        thermal_policy_state = "comfort_only"
    elif full_send_soak_allowed and thermal_allowed:
        thermal_policy_state = "solar_soak_full_send"
    elif thermal_allowed:
        thermal_policy_state = "solar_soak_allowed"
    elif inputs.any_solar_owned_heat_load_on:
        thermal_policy_state = "normalise"

    target_temperature: float | None = None
    target_fan_mode: str | None = None
    target_hvac_mode: str | None = None
    lease_reason = "none"
    if thermal_action == "morning_preheat":
        target_temperature = settings.morning_preheat_target_temp
        target_fan_mode = settings.morning_preheat_fan_mode
        target_hvac_mode = "heat"
        lease_reason = "morning_preheat"
    elif thermal_action == "underfloor_comfort":
        target_temperature = min(
            load_comfort_target_temp(underfloor_load, settings),
            settings.underfloor_max_target_temp,
            underfloor_load.comfort_target_temp if underfloor_load and underfloor_load.comfort_target_temp is not None else settings.underfloor_comfort_target_temp,
        )
        target_fan_mode = None
        target_hvac_mode = "heat"
        lease_reason = "scheduled_underfloor_comfort"
    elif thermal_action == "comfort_heat":
        target_temperature = load_comfort_target_temp(comfort_load, settings) if comfort_load else settings.heat_comfort_target_temp
        target_fan_mode = settings.heat_normal_fan_mode
        target_hvac_mode = "heat"
        lease_reason = "comfort_heat"
    elif thermal_action == "add_one":
        target_temperature = settings.cool_soak_target_temp if thermal_mode == "cooling" else settings.heat_soak_target_temp
        target_fan_mode = settings.cool_soak_fan_mode if thermal_mode == "cooling" else settings.heat_soak_fan_mode
        target_hvac_mode = "cool" if thermal_mode == "cooling" else "heat"
        lease_reason = "solar_soak"

    proposed_actions: list[str] = []
    reason_parts = []
    thermal_reason_parts: list[str] = []
    if control_blocked:
        reason_parts.append("manager disabled")
    reason_parts.append(f"forecast {tier.mode}")
    reason_parts.append(f"solar_phase={phase}")
    reason_parts.append(f"thermal_policy_state={thermal_policy_state}")
    if inputs.soc_source == "live" and soc_known:
        reason_parts.append(f"SOC live: {soc:.0f}%")
    elif inputs.soc_source == "last_known_good" and soc_known:
        reason_parts.append(f"SOC last-known-good: {soc:.0f}%, age {inputs.soc_age_minutes or 0:.0f}m")
    else:
        reason_parts.append(f"SOC unavailable: raw {inputs.raw_soc or 'missing'} and fallback stale")
    if thermal_allowed:
        reason = "thermal_allowed=true"
        reason += f": {energy_budget_reason}"
        reason_parts.append(reason)
        thermal_reason_parts.append(reason)
    else:
        if thermal_mode == "off":
            reason = "thermal_allowed=false: thermal mode off"
        elif not thermal_control_enabled:
            reason = "thermal_allowed=false: thermal control disabled"
        elif battery_discharge_w >= thermal_shed_discharge_w:
            reason = f"thermal_allowed=false: battery discharging {battery_discharge_w:.0f}W >= shed threshold {thermal_shed_discharge_w:.0f}W"
        elif paid_grid_avoidance_required:
            reason = "thermal_allowed=false: paid grid avoidance required"
        elif passive_warming_likely:
            reason = "thermal_allowed=false: passive warming likely and battery priority active"
        elif discretionary_budget_kwh is not None and discretionary_budget_kwh <= 0:
            reason = f"thermal_allowed=false: battery_priority: {energy_budget_reason}"
        elif not soc_known:
            reason = (
                "thermal_allowed=false: "
                f"SOC unavailable, charge {battery_charge_w:.0f}W < {thermal_start_min_charge_w:.0f}W, "
                f"forecast_full_override={forecast_override}"
            )
        else:
            reason = (
                "thermal_allowed=false: "
                f"{energy_budget_reason}; "
                f"forecast_full_override={forecast_override}"
            )
        reason_parts.append(reason)
        thermal_reason_parts.append(reason)
    if thermal_allowed and thermal_load_to_add:
        proposed_actions.append("add_one_heat_load")
    if morning_preheat_allowed and thermal_load_to_add:
        proposed_actions.append("morning_preheat")
        reason_parts.append(morning_preheat_reason)
        thermal_reason_parts.append(morning_preheat_reason)
    elif underfloor_comfort_allowed and thermal_load_to_add:
        proposed_actions.append("underfloor_comfort")
        reason_parts.append(underfloor_reason)
        thermal_reason_parts.append(underfloor_reason)
    elif comfort_heat_allowed and thermal_load_to_add:
        proposed_actions.append("comfort_heat")
        reason_parts.append(f"comfort_only: {thermal_load_to_add} below {settings.comfort_min_room_temp:.1f}C")
        thermal_reason_parts.append(f"comfort_only: {thermal_load_to_add} below {settings.comfort_min_room_temp:.1f}C")
    if thermal_should_shed:
        if thermal_load_to_shed:
            proposed_actions.append("shed_one_heat_load")
        if not thermal_load_to_shed:
            shed_reason = (
                f"thermal_should_shed=true: battery discharging {battery_discharge_w:.0f}W >= shed threshold {thermal_shed_discharge_w:.0f}W; "
                "no owned thermal loads to shed"
            )
            if not settings.shed_unowned_managed_loads_on_battery_discharge:
                shed_reason += "; unowned shedding disabled"
        elif unowned_shed_allowed and not inputs.any_solar_owned_heat_load_on:
            shed_reason = (
                f"thermal_should_shed=true: battery discharging {battery_discharge_w:.0f}W >= threshold {thermal_shed_discharge_w:.0f}W; "
                f"normalising unowned managed load due to battery discharge"
            )
        else:
            shed_reason = f"thermal_should_shed=true: battery discharging {battery_discharge_w:.0f}W >= shed threshold {thermal_shed_discharge_w:.0f}W" if battery_discharge_w >= thermal_shed_discharge_w else "thermal_should_shed=true"
        reason_parts.append(shed_reason)
        thermal_reason_parts.append(shed_reason)
    else:
        if battery_discharge_w >= thermal_shed_discharge_w and not inputs.any_solar_owned_heat_load_on:
            reason_parts.append(
                f"thermal_should_shed=false: battery discharging {battery_discharge_w:.0f}W >= threshold {thermal_shed_discharge_w:.0f}W, "
                "but no owned thermal loads and unowned shedding disabled"
            )
        else:
            reason_parts.append(f"thermal_should_shed=false: battery charge {battery_charge_w:.0f}W, forecast_full_override={forecast_override}")
    if thermal_should_emergency_shed and not shed_blocked_no_loads:
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
            f"SOC {soc:.0f}% >= {settings.pv_load_test_min_soc:.0f}%"
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
            f"grid_charge_required=true: forecast {tier.mode}, SOC {soc:.0f} < target {tier.grid_charge_target_soc:.0f}, EV mode off"
        )
    if paid_grid_avoidance_required:
        proposed_actions.append("paid_grid_avoidance")
        reason_parts.append(paid_time_reserve_reason)
    if forecast_drain_blocked:
        reason_parts.append(f"forecast drain blocked: paid-time reserve floor {paid_floor:.0f}%")
    if passive_warming_likely:
        reason_parts.append(passive_warming_reason)
    if ev_grid_mode_required:
        proposed_actions.append("ev_grid_mode")
        reason_parts.append("ev_grid_mode_required=true")
    if ev_action != "none":
        proposed_actions.append(ev_action)
        reason_parts.append(ev_reason)
    if pre_peak_preserve_required:
        reason_parts.append(
            f"pre_peak_preserve_required=true: SOC {soc:.0f} < target_17 {tier.target_17_soc:.0f} "
            f"and charge {battery_charge_w:.0f}W < {settings.heat_add_min_charge_w:.0f}W"
        )

    expected_action = "none"
    if thermal_action == "shed_blocked_no_owned_loads":
        expected_action = "shed_blocked_no_owned_loads"
    elif thermal_should_emergency_shed:
        expected_action = f"thermal_{thermal_action}"
    elif thermal_should_shed and thermal_action != "none":
        expected_action = f"thermal_{thermal_action}"
    elif ev_action != "none":
        expected_action = ev_action
    elif paid_grid_avoidance_required:
        expected_action = "paid_grid_avoidance"
    elif grid_charge_required:
        expected_action = "grid_charge_enable"
    elif thermal_action != "none":
        expected_action = f"thermal_{thermal_action}"

    return EnergyManagerDecision(
        now=inputs.now,
        forecast_mode=tier.mode,
        active_slot=active_slot(inputs.now),
        tariff_window=tariff_window(inputs.now),
        target_17_soc=tier.target_17_soc,
        current_reserve_soc=reserve_soc,
        grid_charge_target_soc=tier.grid_charge_target_soc,
        battery_soc=inputs.battery_soc,
        raw_soc=inputs.raw_soc,
        resolved_soc=inputs.battery_soc,
        soc_source=inputs.soc_source,
        soc_age_minutes=inputs.soc_age_minutes,
        last_good_soc=inputs.last_good_soc,
        last_good_soc_updated=inputs.last_good_soc_updated,
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
        thermal_policy_state=thermal_policy_state,
        solar_phase=phase,
        passive_warming_likely=passive_warming_likely,
        passive_warming_reason=passive_warming_reason,
        battery_priority_reason=(
            paid_time_reserve_reason
            if paid_grid_avoidance_required
            else f"battery_priority: {energy_budget_reason}"
            if discretionary_budget_kwh is not None and discretionary_budget_kwh <= 0
            else "battery target reachable today; discretionary budget available"
        ),
        comfort_heat_allowed=comfort_heat_allowed,
        solar_soak_allowed=solar_soak_allowed,
        full_send_soak_allowed=full_send_soak_allowed,
        morning_preheat_allowed=morning_preheat_allowed,
        morning_preheat_reason=morning_preheat_reason,
        morning_preheat_load_to_add=morning_preheat_load_to_add,
        underfloor_comfort_allowed=underfloor_comfort_allowed,
        underfloor_policy_state=underfloor_policy_state,
        underfloor_reason=underfloor_reason,
        underfloor_load_to_add=underfloor_load_to_add,
        underfloor_current_window=underfloor_current_window,
        paid_grid_avoidance_required=paid_grid_avoidance_required,
        paid_time_reserve_reason=paid_time_reserve_reason,
        paid_time_floor_soc=paid_floor,
        active_reserve_target_soc=active_reserve_target_soc,
        active_reserve_current_soc=reserve_soc,
        paid_grid_import_w=max(inputs.grid_power_w, 0.0),
        solar_arrived=solar_has_arrived,
        solar_arrived_reason=solar_arrived_reason,
        forecast_drain_blocked=forecast_drain_blocked,
        thermal_target_temperature=target_temperature,
        thermal_target_fan_mode=target_fan_mode,
        thermal_target_hvac_mode=target_hvac_mode,
        thermal_lease_reason=lease_reason,
        daily_battery_target_soc=settings.daily_battery_target_soc,
        remaining_solar_budget_kwh=remaining_forecast_kwh,
        battery_kwh_needed_to_target=battery_kwh_needed,
        expected_house_load_until_solar_end_kwh=expected_house_load_kwh,
        safety_buffer_kwh=safety_buffer_kwh,
        discretionary_energy_budget_kwh=discretionary_budget_kwh,
        energy_budget_reason=energy_budget_reason,
        discretionary_budget_positive=discretionary_budget_positive,
        battery_target_reachable_today=battery_target_reachable,
        base_load_estimate_w=base_load_w,
        estimated_solar_hours_remaining=solar_hours_remaining,
        committed_flexible_load_energy_kwh=committed_flexible_kwh,
        effective_thermal_mode=thermal_mode,
        auto_mode_reason=auto_reason,
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
        ev_charging_detected=ev_charging_detected,
        ev_grid_bypass_required=ev_grid_bypass_required,
        ev_solar_charge_allowed=ev_solar_charge_allowed,
        ev_latch_active=ev_latch_active,
        ev_decision_reason=ev_reason,
        ev_expected_action=ev_action,
        ev_detected_power_w=ev_detected_power_w,
        pre_peak_preserve_required=pre_peak_preserve_required,
        control_blocked=control_blocked,
        expected_action=expected_action,
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
