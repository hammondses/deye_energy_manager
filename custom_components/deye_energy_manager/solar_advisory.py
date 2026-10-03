"""Pure current-action solar advisory combining EV and battery completion.

The detailed forecast retains its supplier PV-output semantics. For battery
completion only, forecast output is used unchanged as a deliberately
conservative DC-available proxy: it is not relabelled as measured DC or used to
claim a clipping estimate. A separate empirical physical scenario can project
DC capture; it is neither a probability bound nor a global clipping optimum.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Sequence

from .battery_dynamics import discharge_to_house, integrate_battery_charge
from .solar_capture import SolarCaptureResult, project_solar_capture
from .solar_forecast import SolarForecast, SolarForecastInterval
from .solar_horizon import (
    SolarHorizonInterval,
    SolarHorizonSettings,
    plan_battery_completion,
)


@dataclass(frozen=True, slots=True)
class SolarAdvisoryInput:
    forecast: SolarForecast
    now: datetime
    current_soc_pct: float
    capacity_kwh: float
    target_soc_pct: float
    reserve_energy_kwh: float
    non_ev_base_house_kw: float
    current_non_ev_house_kw: float
    live_pv_dc_kw: float
    voltage_v: float
    live_bms_max_dc_kw: float
    max_battery_dc_kw: float
    max_discharge_dc_kw: float
    soc_charge_curve: Sequence[tuple[float, float]]
    site_ac_limit_kw: float
    inverter_ac_limit_kw: float
    export_limit_kw: float
    battery_charge_efficiency: float
    battery_discharge_efficiency: float
    inverter_efficiency: float
    safety_buffer_kwh: float
    max_ev_amps: int
    ev_allowed: bool
    forecast_p50_weight: float
    forecast_max_age: timedelta = timedelta(minutes=60)
    physical_dc_upper_kw: tuple[float, ...] | None = None


@dataclass(frozen=True, slots=True)
class SolarAdvisory:
    valid: bool = False
    reason: str = "invalid_input"
    target_reachable: bool = False
    required_energy_now_kwh: float | None = None
    required_soc_now_pct: float | None = None
    completion_margin_kwh: float | None = None
    recommended_ev_amps: int = 0
    recommended_battery_dc_kw: float = 0.0
    recommended_battery_expected_average_dc_kw: float | None = None
    deadline: datetime | None = None
    generated_at: datetime | None = None
    forecast_source_updated_at: datetime | None = None
    forecast_ac_proxy_used: bool = False
    forecast_energy_available_kwh: float | None = None
    instantaneous_dc_excess_after_ac_export_kw: float | None = None
    clipping_estimate_kwh: float | None = None
    clipping_captured_kwh: float | None = None
    clipping_potential_kwh: float | None = None
    physical_scenario_soc_trajectory: tuple[float, ...] = ()
    physical_scenario_boundary_times: tuple[datetime, ...] = ()
    clipping_headroom_kwh: float | None = None
    clipping_plan_available: bool = False


@dataclass(frozen=True, slots=True)
class _CurrentAction:
    amps: int
    next_energy_kwh: float
    battery_charge_kw: float
    battery_average_kw: float
    excess_dc_kw: float


def _finite_nonnegative(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite non-negative number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")


def _efficiency(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite and in (0, 1]")
    if not math.isfinite(value) or not 0 < value <= 1:
        raise ValueError(f"{name} must be finite and in (0, 1]")


def _as_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _validate(inputs: SolarAdvisoryInput) -> datetime:
    if not isinstance(inputs, SolarAdvisoryInput):
        raise ValueError("inputs must be SolarAdvisoryInput")
    if not isinstance(inputs.forecast, SolarForecast):
        raise ValueError("forecast must be a validated SolarForecast")
    now = _as_utc(inputs.now, "now")
    source_updated = _as_utc(inputs.forecast.source_updated_at, "forecast source timestamp")
    forecast_start = _as_utc(inputs.forecast.start, "forecast start")
    forecast_deadline = _as_utc(inputs.forecast.deadline, "forecast deadline")
    if source_updated > now:
        raise ValueError("forecast source timestamp is in the future")
    if not isinstance(inputs.forecast_max_age, timedelta) or inputs.forecast_max_age < timedelta(0):
        raise ValueError("forecast_max_age must be a non-negative timedelta")
    if now - source_updated > inputs.forecast_max_age:
        raise ValueError("forecast source timestamp is stale")
    if forecast_deadline <= forecast_start or forecast_start > now:
        raise ValueError("forecast horizon does not contain now")
    if not inputs.forecast.intervals:
        raise ValueError("forecast has no intervals")

    for name, value in (
        ("current_soc_pct", inputs.current_soc_pct),
        ("target_soc_pct", inputs.target_soc_pct),
        ("capacity_kwh", inputs.capacity_kwh),
        ("reserve_energy_kwh", inputs.reserve_energy_kwh),
        ("non_ev_base_house_kw", inputs.non_ev_base_house_kw),
        ("current_non_ev_house_kw", inputs.current_non_ev_house_kw),
        ("live_pv_dc_kw", inputs.live_pv_dc_kw),
        ("voltage_v", inputs.voltage_v),
        ("live_bms_max_dc_kw", inputs.live_bms_max_dc_kw),
        ("max_battery_dc_kw", inputs.max_battery_dc_kw),
        ("max_discharge_dc_kw", inputs.max_discharge_dc_kw),
        ("site_ac_limit_kw", inputs.site_ac_limit_kw),
        ("inverter_ac_limit_kw", inputs.inverter_ac_limit_kw),
        ("export_limit_kw", inputs.export_limit_kw),
        ("safety_buffer_kwh", inputs.safety_buffer_kwh),
        ("forecast_p50_weight", inputs.forecast_p50_weight),
    ):
        _finite_nonnegative(name, value)
    for name, value in (
        ("battery_charge_efficiency", inputs.battery_charge_efficiency),
        ("battery_discharge_efficiency", inputs.battery_discharge_efficiency),
        ("inverter_efficiency", inputs.inverter_efficiency),
    ):
        _efficiency(name, value)
    if inputs.capacity_kwh <= 0 or inputs.voltage_v <= 0:
        raise ValueError("capacity_kwh and voltage_v must be greater than zero")
    if inputs.current_soc_pct > 100 or inputs.target_soc_pct > 100:
        raise ValueError("SOC percentages must not exceed 100")
    if inputs.target_soc_pct > 100 or inputs.reserve_energy_kwh > inputs.capacity_kwh:
        raise ValueError("target or reserve exceeds battery capacity")
    if inputs.forecast_p50_weight > 1:
        raise ValueError("forecast_p50_weight must be in [0, 1]")
    if not isinstance(inputs.ev_allowed, bool):
        raise ValueError("ev_allowed must be boolean")
    if isinstance(inputs.max_ev_amps, bool) or not isinstance(inputs.max_ev_amps, int):
        raise ValueError("max_ev_amps must be an integer")
    if inputs.max_ev_amps < 0 or inputs.max_ev_amps > 32:
        raise ValueError("max_ev_amps must be from 0 to 32")
    if inputs.physical_dc_upper_kw is not None:
        if len(inputs.physical_dc_upper_kw) != len(inputs.forecast.intervals):
            raise ValueError("physical DC upper curve length must match forecast intervals")
        for power in inputs.physical_dc_upper_kw:
            _finite_nonnegative("physical DC upper power", power)

    cursor = now
    first_duration = None
    for index, interval in enumerate(inputs.forecast.intervals):
        if not isinstance(interval, SolarForecastInterval):
            raise ValueError(f"forecast interval {index} has the wrong type")
        start = _as_utc(interval.start, f"forecast interval {index} start")
        end = _as_utc(interval.end, f"forecast interval {index} end")
        if end <= start:
            raise ValueError("forecast interval has non-positive duration")
        if end <= now:
            continue
        clipped_start = max(start, now)
        if clipped_start != cursor:
            raise ValueError("forecast intervals have a gap or overlap")
        start = clipped_start
        if first_duration is None:
            first_duration = (end - start).total_seconds() / 3600.0
        cursor = end
        values = (
            interval.pv_estimate10_kw,
            interval.pv_estimate_kw,
            interval.pv_estimate90_kw,
        )
        for value in values:
            _finite_nonnegative("forecast PV estimate", value)
        if not values[0] <= values[1] <= values[2]:
            raise ValueError("forecast PV quantiles are disordered")
    if first_duration is None or cursor != forecast_deadline:
        raise ValueError("forecast does not cover from now through its deadline")
    return now


def _blend(interval: SolarForecastInterval, p50_weight: float) -> float:
    return interval.pv_estimate10_kw + p50_weight * (
        interval.pv_estimate_kw - interval.pv_estimate10_kw
    )


def _forecast_horizon(
    inputs: SolarAdvisoryInput, now: datetime
) -> tuple[list[SolarHorizonInterval], datetime, float]:
    source_intervals = inputs.forecast.intervals
    active: list[tuple[SolarForecastInterval, datetime, datetime, float]] = []
    for interval in source_intervals:
        start = max(_as_utc(interval.start, "forecast interval start"), now)
        end = _as_utc(interval.end, "forecast interval end")
        if end <= now:
            continue
        power = _blend(interval, inputs.forecast_p50_weight)
        active.append((interval, start, end, power))
    if not active:
        raise ValueError("forecast has no interval remaining after now")

    load_dc_kw = (
        min(inputs.non_ev_base_house_kw, inputs.inverter_ac_limit_kw)
        / inputs.inverter_efficiency
    )
    raw_last_positive = max(
        (
            index
            for index, (_, _, _, power) in enumerate(active)
            if power > load_dc_kw
        ),
        default=-1,
    )
    # Discard forecast energy after the raw net-positive endpoint before
    # applying the safety buffer, so the configured buffer is withheld from
    # the energy considered useful for battery completion.
    raw_usable = active[: raw_last_positive + 1] if raw_last_positive >= 0 else []
    total_energy = sum(
        power * (end - start).total_seconds() / 3600
        for _, start, end, power in raw_usable
    )
    remaining_energy = max(total_energy - inputs.safety_buffer_kwh, 0.0)
    scale = remaining_energy / total_energy if total_energy > 0 else 0.0
    adjusted = [
        (item, start, end, power * scale)
        for item, start, end, power in raw_usable
    ]

    # End this completion horizon at the last forecast interval with positive
    # PV headroom above the base house load. Future EV presence is not assumed.
    last_positive = -1
    for index, (_, _, _, power) in enumerate(adjusted):
        if power > load_dc_kw:
            last_positive = index
    if last_positive < 0:
        deadline = active[0][2]
        planning_rows: list[tuple[SolarForecastInterval, datetime, datetime, float]] = []
    else:
        deadline = adjusted[last_positive][2]
        planning_rows = adjusted[: last_positive + 1]

    forecast_energy_available = sum(
        power * (end - start).total_seconds() / 3600
        for _, start, end, power in planning_rows
    )
    horizon = [
        SolarHorizonInterval(
            duration_hours=(end - start).total_seconds() / 3600,
            # Deliberately conservative AC-output-as-DC proxy: no inverse
            # efficiency or clipping uplift is applied to supplier forecast.
            pv_dc_kw=power,
            non_ev_house_ac_kw=inputs.non_ev_base_house_kw,
            bms_max_dc_power_kw=min(
                inputs.max_battery_dc_kw, inputs.live_bms_max_dc_kw
            ),
        )
        for _, start, end, power in planning_rows
    ]
    return horizon, deadline, forecast_energy_available


def _horizon_settings(inputs: SolarAdvisoryInput) -> SolarHorizonSettings:
    return SolarHorizonSettings(
        capacity_kwh=inputs.capacity_kwh,
        target_energy_kwh=inputs.target_soc_pct * inputs.capacity_kwh / 100,
        reserve_energy_kwh=inputs.reserve_energy_kwh,
        charge_efficiency=inputs.battery_charge_efficiency,
        discharge_efficiency=inputs.battery_discharge_efficiency,
        inverter_efficiency=inputs.inverter_efficiency,
        inverter_ac_limit_kw=inputs.inverter_ac_limit_kw,
        max_discharge_dc_power_kw=inputs.max_discharge_dc_kw,
        soc_charge_curve=inputs.soc_charge_curve,
    )


def _current_step(
    inputs: SolarAdvisoryInput,
    energy_kwh: float,
    duration_hours: float,
    amps: int,
    required_next_kwh: float | None,
) -> _CurrentAction | None:
    ev_kw = amps * inputs.voltage_v / 1000.0
    if amps and inputs.current_non_ev_house_kw + ev_kw > inputs.site_ac_limit_kw + 1e-9:
        return None

    house_pv_ac_kw = min(
        inputs.current_non_ev_house_kw,
        inputs.live_pv_dc_kw * inputs.inverter_efficiency,
        inputs.inverter_ac_limit_kw,
    )
    house_deficit_kw = max(inputs.current_non_ev_house_kw - house_pv_ac_kw, 0.0)
    ac_headroom_kw = max(inputs.inverter_ac_limit_kw - house_pv_ac_kw, 0.0)
    battery_house_kw = min(house_deficit_kw, ac_headroom_kw)
    if battery_house_kw > 0:
        if amps > 0:
            return None
        discharged = discharge_to_house(
            stored_energy_kwh=energy_kwh,
            required_house_ac_energy_kwh=battery_house_kw * duration_hours,
            duration_hours=duration_hours,
            max_discharge_dc_power_kw=inputs.max_discharge_dc_kw,
            reserve_energy_kwh=inputs.reserve_energy_kwh,
            discharge_efficiency=inputs.battery_discharge_efficiency,
            inverter_efficiency=inputs.inverter_efficiency,
        )
        if (
            required_next_kwh is not None
            and discharged.stored_energy_end_kwh + 1e-9 < required_next_kwh
        ):
            return None
        return _CurrentAction(
            amps, discharged.stored_energy_end_kwh, 0.0, 0.0, 0.0
        )

    pv_remaining_dc_kw = max(
        inputs.live_pv_dc_kw - house_pv_ac_kw / inputs.inverter_efficiency,
        0.0,
    )
    ev_ac_headroom_kw = max(inputs.inverter_ac_limit_kw - house_pv_ac_kw, 0.0)
    ev_served_kw = min(
        ev_kw,
        ev_ac_headroom_kw,
        pv_remaining_dc_kw * inputs.inverter_efficiency,
    )
    if ev_served_kw + 1e-9 < ev_kw:
        return None
    pv_remaining_dc_kw = max(
        pv_remaining_dc_kw - ev_served_kw / inputs.inverter_efficiency,
        0.0,
    )

    export_ac_kw = min(
        inputs.export_limit_kw,
        max(inputs.inverter_ac_limit_kw - house_pv_ac_kw - ev_served_kw, 0.0),
    )
    excess_dc_kw = max(
        pv_remaining_dc_kw - export_ac_kw / inputs.inverter_efficiency,
        0.0,
    )
    max_source_kw = min(
        pv_remaining_dc_kw,
        inputs.live_bms_max_dc_kw,
        inputs.max_battery_dc_kw,
    )
    maximum = integrate_battery_charge(
        stored_energy_kwh=energy_kwh,
        capacity_kwh=inputs.capacity_kwh,
        duration_hours=duration_hours,
        available_dc_power_kw=max_source_kw,
        bms_max_dc_power_kw=inputs.live_bms_max_dc_kw,
        charge_efficiency=inputs.battery_charge_efficiency,
        soc_charge_curve=inputs.soc_charge_curve,
    )

    if required_next_kwh is None:
        return _CurrentAction(
            amps,
            maximum.stored_energy_end_kwh,
            max_source_kw,
            maximum.average_dc_charge_power_kw,
            excess_dc_kw,
        )
    if maximum.stored_energy_end_kwh + 1e-9 < required_next_kwh:
        return None

    if energy_kwh >= required_next_kwh:
        min_source_kw = 0.0
    else:
        low, high = 0.0, max_source_kw
        for _ in range(40):
            middle = (low + high) / 2
            result = integrate_battery_charge(
                stored_energy_kwh=energy_kwh,
                capacity_kwh=inputs.capacity_kwh,
                duration_hours=duration_hours,
                available_dc_power_kw=middle,
                bms_max_dc_power_kw=inputs.live_bms_max_dc_kw,
                charge_efficiency=inputs.battery_charge_efficiency,
                soc_charge_curve=inputs.soc_charge_curve,
            )
            if result.stored_energy_end_kwh + 1e-10 >= required_next_kwh:
                high = middle
            else:
                low = middle
        min_source_kw = high

    # Completion charging may displace export. Once that minimum is met, add
    # only PV that would otherwise exceed the available AC/export path.
    requested_kw = min(max_source_kw, max(min_source_kw, excess_dc_kw))
    selected = integrate_battery_charge(
        stored_energy_kwh=energy_kwh,
        capacity_kwh=inputs.capacity_kwh,
        duration_hours=duration_hours,
        available_dc_power_kw=requested_kw,
        bms_max_dc_power_kw=inputs.live_bms_max_dc_kw,
        charge_efficiency=inputs.battery_charge_efficiency,
        soc_charge_curve=inputs.soc_charge_curve,
    )
    return _CurrentAction(
        amps,
        selected.stored_energy_end_kwh,
        requested_kw,
        selected.average_dc_charge_power_kw,
        excess_dc_kw,
    )


def _required_energy_now(
    inputs: SolarAdvisoryInput,
    duration_hours: float,
    required_next_kwh: float | None,
) -> float | None:
    if required_next_kwh is None:
        return None
    low, high = 0.0, inputs.capacity_kwh
    if _current_step(inputs, 0.0, duration_hours, 0, required_next_kwh) is not None:
        return 0.0
    if _current_step(inputs, high, duration_hours, 0, required_next_kwh) is None:
        return None
    for _ in range(40):
        middle = (low + high) / 2
        if _current_step(inputs, middle, duration_hours, 0, required_next_kwh) is not None:
            high = middle
        else:
            low = middle
    return high


def _capture_projection(inputs, now, settings, chosen, required_now, future_requirements) -> SolarCaptureResult | None:
    """Project the chosen action against an empirical clear-sky scenario.

    This is a separate scenario, not a probability bound. It uses measured PV
    and the chosen EV action now, with no assumed EV presence in future bins.
    Completion floors expire at the useful-solar deadline; subsequent house
    demand may normally discharge the battery after it has reached its target.
    """
    if inputs.physical_dc_upper_kw is None:
        return None
    intervals = []
    for index, interval in enumerate(inputs.forecast.intervals):
        if interval.end <= now:
            continue
        current = not intervals
        intervals.append(SolarHorizonInterval(
            duration_hours=(interval.end - max(interval.start, now)).total_seconds() / 3600,
            pv_dc_kw=inputs.live_pv_dc_kw if current else inputs.physical_dc_upper_kw[index],
            non_ev_house_ac_kw=(
                inputs.current_non_ev_house_kw + chosen.amps * inputs.voltage_v / 1000
                if current else inputs.non_ev_base_house_kw
            ),
            bms_max_dc_power_kw=min(inputs.max_battery_dc_kw, inputs.live_bms_max_dc_kw),
        ))
    floors = [required_now, *future_requirements]
    floors.extend([0.0] * (len(intervals) + 1 - len(floors)))
    return project_solar_capture(
        intervals, settings,
        initial_energy_kwh=inputs.current_soc_pct * inputs.capacity_kwh / 100,
        export_limit_kw=inputs.export_limit_kw,
        required_energy_by_boundary_kwh=floors,
        first_charge_limit_kw=chosen.battery_charge_kw,
    )


def recommend_solar_action(inputs: SolarAdvisoryInput) -> SolarAdvisory:
    """Return a current EV amp and battery-charge recommendation without writes."""
    try:
        now = _validate(inputs)
    except ValueError as err:
        return SolarAdvisory(reason=str(err))

    try:
        horizon, deadline, forecast_energy = _forecast_horizon(inputs, now)
        settings = _horizon_settings(inputs)
        future_horizon = horizon[1:] if horizon else []
        future_plan = plan_battery_completion(
            future_horizon,
            settings,
            initial_energy_kwh=inputs.current_soc_pct * inputs.capacity_kwh / 100,
        )
        next_requirement = future_plan.required_energy_by_boundary_kwh[0]
        current_duration = (
            horizon[0].duration_hours
            if horizon
            else max(
                0.0,
                (inputs.forecast.intervals[0].end - now).total_seconds() / 3600,
            )
        )
        if current_duration <= 0:
            current_duration = inputs.forecast.intervals[0].duration_hours

        current_energy = inputs.current_soc_pct * inputs.capacity_kwh / 100
        required_now = _required_energy_now(inputs, current_duration, next_requirement)
        candidate_amps = [0]
        if inputs.ev_allowed and inputs.max_ev_amps >= 6 and next_requirement is not None:
            candidate_amps.extend(range(6, inputs.max_ev_amps + 1))

        chosen: _CurrentAction | None = None
        for amps in reversed(candidate_amps):
            candidate = _current_step(
                inputs, current_energy, current_duration, amps, next_requirement
            )
            if candidate is not None:
                chosen = candidate
                break
        if chosen is None:
            chosen = _current_step(
                inputs, current_energy, current_duration, 0, None
            )

        if chosen is None:
            # Zero EV is always a defined no-actuation fallback; this branch
            # means the live source data are physically inconsistent.
            return SolarAdvisory(reason="no_valid_current_action")

        terminal_plan = plan_battery_completion(
            future_horizon,
            settings,
            initial_energy_kwh=chosen.next_energy_kwh,
        )
        target_energy = settings.target_energy_kwh
        completion_margin = (
            current_energy - required_now if required_now is not None else None
        )
        reachable = (
            terminal_plan.terminal_energy_kwh + 1e-9 >= target_energy
            and next_requirement is not None
        )
        reason = "ok" if reachable else "target_unreachable_from_forecast"
        capture = _capture_projection(
            inputs, now, settings, chosen, required_now,
            future_plan.required_energy_by_boundary_kwh,
        )
        return SolarAdvisory(
            valid=True,
            reason=reason,
            target_reachable=reachable,
            required_energy_now_kwh=required_now,
            required_soc_now_pct=(
                required_now / inputs.capacity_kwh * 100
                if required_now is not None
                else None
            ),
            completion_margin_kwh=completion_margin,
            recommended_ev_amps=chosen.amps,
            recommended_battery_dc_kw=chosen.battery_charge_kw,
            recommended_battery_expected_average_dc_kw=chosen.battery_average_kw,
            deadline=deadline,
            generated_at=now,
            forecast_source_updated_at=_as_utc(
                inputs.forecast.source_updated_at, "forecast source timestamp"
            ),
            forecast_ac_proxy_used=True,
            forecast_energy_available_kwh=forecast_energy,
            instantaneous_dc_excess_after_ac_export_kw=chosen.excess_dc_kw,
            clipping_headroom_kwh=None,
            clipping_estimate_kwh=capture.predicted_clipped_dc_kwh if capture else None,
            clipping_captured_kwh=capture.captured_clipping_dc_kwh if capture else None,
            clipping_potential_kwh=capture.potential_clipping_dc_kwh if capture else None,
            physical_scenario_soc_trajectory=(
                tuple(100 * energy / inputs.capacity_kwh for energy in capture.energy_by_boundary_kwh)
                if capture else ()
            ),
            physical_scenario_boundary_times=(
                (now, *(interval.end for interval in inputs.forecast.intervals if interval.end > now))
                if capture else ()
            ),
            clipping_plan_available=capture is not None,
        )
    except ValueError as err:
        return SolarAdvisory(reason=str(err))
