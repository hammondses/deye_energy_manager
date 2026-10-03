"""Forward projection of policy-captured DC PV excess over a solar horizon.

This reports captured and still-potential clipping under a specified
completion-floor/current-charge policy. It does not claim a globally optimal
plan or label remaining clipping unavoidable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math

from .battery_dynamics import discharge_to_house, integrate_battery_charge
from .solar_horizon import SolarHorizonInterval, SolarHorizonSettings


@dataclass(frozen=True, slots=True)
class SolarCaptureResult:
    captured_clipping_dc_kwh: float
    predicted_clipped_dc_kwh: float
    potential_clipping_dc_kwh: float
    terminal_energy_kwh: float
    charge_command_kw: float
    energy_by_boundary_kwh: tuple[float, ...]
    predicted_energy_shortfall_kwh: float | None


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
    export_limit_kw: float,
    required_energy_by_boundary_kwh: Sequence[float | None],
    first_charge_limit_kw: float | None,
) -> None:
    if not isinstance(intervals, Sequence) or isinstance(intervals, (str, bytes)):
        raise ValueError("intervals must be a sequence")
    if not isinstance(settings, SolarHorizonSettings):
        raise ValueError("settings must be SolarHorizonSettings")
    if not isinstance(required_energy_by_boundary_kwh, Sequence) or isinstance(
        required_energy_by_boundary_kwh, (str, bytes)
    ):
        raise ValueError("required_energy_by_boundary_kwh must be a sequence")
    _finite_nonnegative("initial_energy_kwh", initial_energy_kwh)
    _finite_nonnegative("export_limit_kw", export_limit_kw)
    if first_charge_limit_kw is not None:
        _finite_nonnegative("first_charge_limit_kw", first_charge_limit_kw)
    if len(required_energy_by_boundary_kwh) != len(intervals) + 1:
        raise ValueError("required-energy boundary count must equal intervals + 1")

    for name, value in (
        ("capacity_kwh", settings.capacity_kwh),
        ("target_energy_kwh", settings.target_energy_kwh),
        ("reserve_energy_kwh", settings.reserve_energy_kwh),
        ("inverter_ac_limit_kw", settings.inverter_ac_limit_kw),
        ("max_discharge_dc_power_kw", settings.max_discharge_dc_power_kw),
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
    for index, required in enumerate(required_energy_by_boundary_kwh):
        if required is None:
            continue
        _finite_nonnegative(f"required energy at boundary {index}", required)
        if required > settings.capacity_kwh:
            raise ValueError(f"required energy at boundary {index} exceeds capacity")
    if not required_energy_by_boundary_kwh:
        raise ValueError("at least one required-energy boundary is required")
    # Validate the SOC curve independently, including an empty horizon.
    integrate_battery_charge(
        stored_energy_kwh=initial_energy_kwh,
        capacity_kwh=settings.capacity_kwh,
        duration_hours=1.0,
        available_dc_power_kw=0.0,
        bms_max_dc_power_kw=0.0,
        charge_efficiency=settings.charge_efficiency,
        soc_charge_curve=settings.soc_charge_curve,
    )


def _minimum_charge_power(
    *,
    energy_kwh: float,
    interval: SolarHorizonInterval,
    settings: SolarHorizonSettings,
    required_next_kwh: float,
    available_dc_kw: float,
) -> float:
    """Find the least source-power ceiling that reaches the next floor."""
    if energy_kwh >= required_next_kwh:
        return 0.0

    def end_energy(request_kw: float) -> float:
        return integrate_battery_charge(
            stored_energy_kwh=energy_kwh,
            capacity_kwh=settings.capacity_kwh,
            duration_hours=interval.duration_hours,
            available_dc_power_kw=min(request_kw, available_dc_kw),
            bms_max_dc_power_kw=interval.bms_max_dc_power_kw,
            charge_efficiency=settings.charge_efficiency,
            soc_charge_curve=settings.soc_charge_curve,
        ).stored_energy_end_kwh

    if end_energy(available_dc_kw) + 1e-9 < required_next_kwh:
        return available_dc_kw
    low, high = 0.0, available_dc_kw
    for _ in range(40):
        middle = (low + high) / 2
        if end_energy(middle) + 1e-10 >= required_next_kwh:
            high = middle
        else:
            low = middle
    return high


def project_solar_capture(
    intervals: Sequence[SolarHorizonInterval],
    settings: SolarHorizonSettings,
    *,
    initial_energy_kwh: float,
    export_limit_kw: float,
    required_energy_by_boundary_kwh: Sequence[float | None],
    first_charge_limit_kw: float | None = None,
) -> SolarCaptureResult:
    """Project direct-DC capture under completion floors and live charge limit.

    Each interval serves PV-backed house AC first. House deficit is supplied
    from the battery only within reserve, power, and inverter headroom; it
    prevents simultaneous charge and discharge. With DC surplus, battery
    charge power is the greater of the minimum completion-floor power and PV
    otherwise beyond the maximum house-plus-export AC path. A ``None`` next
    floor denotes infeasible completion and charges all available DC PV.
    """
    _validate(
        intervals,
        settings,
        initial_energy_kwh,
        export_limit_kw,
        required_energy_by_boundary_kwh,
        first_charge_limit_kw,
    )
    energy = float(initial_energy_kwh)
    energy_path = [energy]
    clipped_potential = 0.0
    clipped_captured = 0.0
    first_command = 0.0

    for index, interval in enumerate(intervals):
        house_pv_ac_kw = min(
            interval.non_ev_house_ac_kw,
            interval.pv_dc_kw * settings.inverter_efficiency,
            settings.inverter_ac_limit_kw,
        )
        house_dc_kw = house_pv_ac_kw / settings.inverter_efficiency
        surplus_dc_kw = max(interval.pv_dc_kw - house_dc_kw, 0.0)
        house_deficit_ac_kw = max(interval.non_ev_house_ac_kw - house_pv_ac_kw, 0.0)
        ac_headroom_kw = max(settings.inverter_ac_limit_kw - house_pv_ac_kw, 0.0)
        battery_servable_deficit_kw = min(house_deficit_ac_kw, ac_headroom_kw)

        if battery_servable_deficit_kw > 0:
            discharge = discharge_to_house(
                stored_energy_kwh=energy,
                required_house_ac_energy_kwh=(
                    battery_servable_deficit_kw * interval.duration_hours
                ),
                duration_hours=interval.duration_hours,
                max_discharge_dc_power_kw=settings.max_discharge_dc_power_kw,
                reserve_energy_kwh=settings.reserve_energy_kwh,
                discharge_efficiency=settings.discharge_efficiency,
                inverter_efficiency=settings.inverter_efficiency,
            )
            energy = discharge.stored_energy_end_kwh
            energy_path.append(energy)
            continue

        spill_dc_kw = max(
            interval.pv_dc_kw
            - min(
                settings.inverter_ac_limit_kw,
                interval.non_ev_house_ac_kw + export_limit_kw,
            )
            / settings.inverter_efficiency,
            0.0,
        )
        clipped_potential += spill_dc_kw * interval.duration_hours

        max_source_kw = min(surplus_dc_kw, interval.bms_max_dc_power_kw)
        required_next = required_energy_by_boundary_kwh[index + 1]
        if required_next is None:
            floor_power_kw = max_source_kw
        else:
            floor_power_kw = _minimum_charge_power(
                energy_kwh=energy,
                interval=interval,
                settings=settings,
                required_next_kwh=required_next,
                available_dc_kw=max_source_kw,
            )
        requested_power_kw = min(max_source_kw, max(floor_power_kw, spill_dc_kw))
        if index == 0 and first_charge_limit_kw is not None:
            requested_power_kw = min(requested_power_kw, first_charge_limit_kw)
        charge = integrate_battery_charge(
            stored_energy_kwh=energy,
            capacity_kwh=settings.capacity_kwh,
            duration_hours=interval.duration_hours,
            available_dc_power_kw=min(surplus_dc_kw, requested_power_kw),
            bms_max_dc_power_kw=interval.bms_max_dc_power_kw,
            charge_efficiency=settings.charge_efficiency,
            soc_charge_curve=settings.soc_charge_curve,
            otherwise_clipped_dc_power_kw=spill_dc_kw,
        )
        if index == 0:
            first_command = requested_power_kw
        clipped_captured += charge.captured_clipping_dc_energy_kwh
        energy = charge.stored_energy_end_kwh
        energy_path.append(energy)

    predicted_clipped = max(clipped_potential - clipped_captured, 0.0)
    final_floor = required_energy_by_boundary_kwh[-1]
    shortfall = max(final_floor - energy, 0.0) if final_floor is not None else None
    return SolarCaptureResult(
        captured_clipping_dc_kwh=clipped_captured,
        predicted_clipped_dc_kwh=predicted_clipped,
        potential_clipping_dc_kwh=clipped_potential,
        terminal_energy_kwh=energy,
        charge_command_kw=first_command,
        energy_by_boundary_kwh=tuple(energy_path),
        predicted_energy_shortfall_kwh=shortfall,
    )
