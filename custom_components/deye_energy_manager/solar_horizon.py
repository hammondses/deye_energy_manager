"""Continuous-energy horizon model for house battery completion only.

This module calculates a completion envelope under caller-supplied DC PV and
house-load intervals. It does not optimize EV charging, export, uncertainty,
or actuator targets. Inputs are assumed already clipped to the caller's solar
planning deadline; PV must be explicitly available DC power.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math

from .battery_dynamics import discharge_to_house, integrate_battery_charge


@dataclass(frozen=True, slots=True)
class SolarHorizonInterval:
    """One constant-power forecast interval; powers are kW, duration hours."""

    duration_hours: float
    pv_dc_kw: float
    non_ev_house_ac_kw: float
    bms_max_dc_power_kw: float


@dataclass(frozen=True, slots=True)
class SolarHorizonSettings:
    capacity_kwh: float
    target_energy_kwh: float
    reserve_energy_kwh: float
    charge_efficiency: float
    discharge_efficiency: float
    inverter_efficiency: float
    inverter_ac_limit_kw: float
    max_discharge_dc_power_kw: float
    soc_charge_curve: Sequence[tuple[float, float]]


@dataclass(frozen=True, slots=True)
class SolarHorizonResult:
    """Completion requirements and max-charge forward simulation."""

    required_energy_by_boundary_kwh: tuple[float | None, ...]
    forward_energy_by_boundary_kwh: tuple[float, ...]
    terminal_energy_kwh: float
    terminal_shortfall_kwh: float
    target_reachable_from_initial: bool


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


def _validate(
    intervals: Sequence[SolarHorizonInterval],
    settings: SolarHorizonSettings,
    initial_energy_kwh: float,
) -> None:
    if not isinstance(intervals, Sequence) or isinstance(intervals, (str, bytes)):
        raise ValueError("intervals must be a sequence")
    for name, value in (
        ("capacity_kwh", settings.capacity_kwh),
        ("target_energy_kwh", settings.target_energy_kwh),
        ("reserve_energy_kwh", settings.reserve_energy_kwh),
        ("inverter_ac_limit_kw", settings.inverter_ac_limit_kw),
        ("max_discharge_dc_power_kw", settings.max_discharge_dc_power_kw),
        ("initial_energy_kwh", initial_energy_kwh),
    ):
        _finite_nonnegative(name, value)
    for name, value in (
        ("charge_efficiency", settings.charge_efficiency),
        ("discharge_efficiency", settings.discharge_efficiency),
        ("inverter_efficiency", settings.inverter_efficiency),
    ):
        _efficiency(name, value)
    if settings.capacity_kwh <= 0:
        raise ValueError("capacity_kwh must be greater than zero")
    if settings.target_energy_kwh > settings.capacity_kwh:
        raise ValueError("target_energy_kwh cannot exceed capacity_kwh")
    if settings.reserve_energy_kwh > settings.capacity_kwh:
        raise ValueError("reserve_energy_kwh cannot exceed capacity_kwh")
    if initial_energy_kwh > settings.capacity_kwh:
        raise ValueError("initial_energy_kwh cannot exceed capacity_kwh")
    if not intervals:
        # An empty horizon is valid but cannot add energy before its deadline.
        pass
    for index, interval in enumerate(intervals):
        if not isinstance(interval, SolarHorizonInterval):
            raise ValueError(f"interval {index} has the wrong type")
        for name, value in (
            ("duration_hours", interval.duration_hours),
            ("pv_dc_kw", interval.pv_dc_kw),
            ("non_ev_house_ac_kw", interval.non_ev_house_ac_kw),
            ("bms_max_dc_power_kw", interval.bms_max_dc_power_kw),
        ):
            _finite_nonnegative(f"interval {index} {name}", value)
        if interval.duration_hours <= 0:
            raise ValueError(f"interval {index} duration_hours must be greater than zero")

    # Validate the SOC curve even for an empty horizon, where no interval
    # transition would otherwise call the lower-level validator.
    integrate_battery_charge(
        stored_energy_kwh=initial_energy_kwh,
        capacity_kwh=settings.capacity_kwh,
        duration_hours=1.0,
        available_dc_power_kw=0.0,
        bms_max_dc_power_kw=0.0,
        charge_efficiency=settings.charge_efficiency,
        soc_charge_curve=settings.soc_charge_curve,
    )


def _advance(
    energy_kwh: float,
    interval: SolarHorizonInterval,
    settings: SolarHorizonSettings,
) -> float:
    """Serve house PV first, then battery discharge or surplus charging."""
    pv_house_ac_kw = min(
        interval.non_ev_house_ac_kw,
        interval.pv_dc_kw * settings.inverter_efficiency,
        settings.inverter_ac_limit_kw,
    )
    house_dc_kw = pv_house_ac_kw / settings.inverter_efficiency
    surplus_dc_kw = max(interval.pv_dc_kw - house_dc_kw, 0.0)
    house_deficit_ac_kw = max(interval.non_ev_house_ac_kw - pv_house_ac_kw, 0.0)
    remaining_ac_headroom_kw = max(
        settings.inverter_ac_limit_kw - pv_house_ac_kw, 0.0
    )
    battery_servable_deficit_kw = min(
        house_deficit_ac_kw, remaining_ac_headroom_kw
    )

    # Determine the operating mode in AC space rather than from a tiny
    # floating-point DC remainder (for example 1.136 - 1.136*0.96/0.96).
    # If some house deficit can be supplied inside the inverter ceiling,
    # model battery discharge for that deficit before considering charging.
    if battery_servable_deficit_kw <= 0 and surplus_dc_kw > 0:
        charge = integrate_battery_charge(
            stored_energy_kwh=energy_kwh,
            capacity_kwh=settings.capacity_kwh,
            duration_hours=interval.duration_hours,
            available_dc_power_kw=surplus_dc_kw,
            bms_max_dc_power_kw=interval.bms_max_dc_power_kw,
            charge_efficiency=settings.charge_efficiency,
            soc_charge_curve=settings.soc_charge_curve,
        )
        return charge.stored_energy_end_kwh

    if battery_servable_deficit_kw > 0:
        discharge = discharge_to_house(
            stored_energy_kwh=energy_kwh,
            required_house_ac_energy_kwh=(
                battery_servable_deficit_kw * interval.duration_hours
            ),
            duration_hours=interval.duration_hours,
            max_discharge_dc_power_kw=settings.max_discharge_dc_power_kw,
            reserve_energy_kwh=settings.reserve_energy_kwh,
            discharge_efficiency=settings.discharge_efficiency,
            inverter_efficiency=settings.inverter_efficiency,
        )
        return discharge.stored_energy_end_kwh

    return energy_kwh


def plan_battery_completion(
    intervals: Sequence[SolarHorizonInterval],
    settings: SolarHorizonSettings,
    *,
    initial_energy_kwh: float,
    bisection_iterations: int = 40,
) -> SolarHorizonResult:
    """Compute backward minimum starting energy and forward maximum trajectory.

    Backward requirements use monotone bisection over each interval transition.
    If even a full battery cannot reach a downstream requirement, that boundary
    and all earlier boundaries are ``None``. Forward simulation preserves
    continuous floating-point energy across intervals (no per-step rounding).
    """
    _validate(intervals, settings, initial_energy_kwh)
    if isinstance(bisection_iterations, bool) or not isinstance(
        bisection_iterations, int
    ) or bisection_iterations < 1 or bisection_iterations > 80:
        raise ValueError("bisection_iterations must be an integer from 1 to 80")

    boundary_count = len(intervals) + 1
    required: list[float | None] = [None] * boundary_count
    required[-1] = float(settings.target_energy_kwh)

    for index in range(len(intervals) - 1, -1, -1):
        next_required = required[index + 1]
        if next_required is None:
            continue
        interval = intervals[index]
        if _advance(float(settings.capacity_kwh), interval, settings) + 1e-10 < next_required:
            continue
        if _advance(0.0, interval, settings) + 1e-12 >= next_required:
            required[index] = 0.0
            continue
        low, high = 0.0, float(settings.capacity_kwh)
        for _ in range(bisection_iterations):
            middle = (low + high) / 2
            if _advance(middle, interval, settings) + 1e-12 >= next_required:
                high = middle
            else:
                low = middle
        required[index] = high

    forward = [float(initial_energy_kwh)]
    for interval in intervals:
        forward.append(_advance(forward[-1], interval, settings))

    terminal = forward[-1]
    shortfall = max(float(settings.target_energy_kwh) - terminal, 0.0)
    initial_requirement = required[0]
    return SolarHorizonResult(
        required_energy_by_boundary_kwh=tuple(required),
        forward_energy_by_boundary_kwh=tuple(forward),
        terminal_energy_kwh=terminal,
        terminal_shortfall_kwh=shortfall,
        target_reachable_from_initial=(
            initial_requirement is not None
            and initial_energy_kwh + 1e-9 >= initial_requirement
            and shortfall <= 1e-9
        ),
    )
