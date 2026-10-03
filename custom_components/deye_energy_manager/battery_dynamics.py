"""Pure continuous-energy battery charge and house-discharge transitions.

Power is in kW, stored energy in kWh, and duration in hours. The charge curve
uses fractional SOC band starts and maximum DC-side charge power. This module
does not decide how PV is shared with house, EV, or export.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class ChargeResult:
    stored_energy_end_kwh: float
    dc_charge_energy_kwh: float
    average_dc_charge_power_kw: float
    unused_available_dc_energy_kwh: float
    captured_clipping_dc_energy_kwh: float = 0.0


@dataclass(frozen=True, slots=True)
class HouseDischargeResult:
    stored_energy_end_kwh: float
    stored_energy_withdrawn_kwh: float
    available_dc_energy_kwh: float
    house_ac_served_kwh: float
    house_ac_unserved_kwh: float


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


def integrate_battery_charge(
    *,
    stored_energy_kwh: float,
    capacity_kwh: float,
    duration_hours: float,
    available_dc_power_kw: float,
    bms_max_dc_power_kw: float,
    charge_efficiency: float,
    soc_charge_curve: Sequence[tuple[float, float]],
    otherwise_clipped_dc_power_kw: float = 0.0,
) -> ChargeResult:
    """Integrate charging across SOC-dependent power bands without rounding.

    ``soc_charge_curve`` contains ``(band_start_soc_fraction, max_dc_kw)``
    pairs. Starts must be strictly increasing from 0 and may end at 1.0; a
    100% entry is a terminal marker, since capacity itself stops charging.
    """
    for name, value in (
        ("stored_energy_kwh", stored_energy_kwh),
        ("capacity_kwh", capacity_kwh),
        ("duration_hours", duration_hours),
        ("available_dc_power_kw", available_dc_power_kw),
        ("bms_max_dc_power_kw", bms_max_dc_power_kw),
        ("otherwise_clipped_dc_power_kw", otherwise_clipped_dc_power_kw),
    ):
        _finite_nonnegative(name, value)
    _efficiency("charge_efficiency", charge_efficiency)
    if capacity_kwh <= 0 or duration_hours <= 0:
        raise ValueError("capacity_kwh and duration_hours must be greater than zero")
    if stored_energy_kwh > capacity_kwh:
        raise ValueError("stored_energy_kwh cannot exceed capacity_kwh")
    if not isinstance(soc_charge_curve, Sequence) or isinstance(
        soc_charge_curve, (str, bytes)
    ) or not soc_charge_curve:
        raise ValueError("soc_charge_curve must be a non-empty sequence")

    curve: list[tuple[float, float]] = []
    for index, pair in enumerate(soc_charge_curve):
        if not isinstance(pair, Sequence) or len(pair) != 2:
            raise ValueError("each SOC curve entry must be a (start_fraction, kW) pair")
        start, power = pair
        _finite_nonnegative("SOC band start", start)
        _finite_nonnegative("SOC band max power", power)
        if start > 1:
            raise ValueError("SOC band starts cannot exceed 1.0")
        if start == 1 and index != len(soc_charge_curve) - 1:
            raise ValueError("100% SOC may only be the final terminal marker")
        if index == 0 and start != 0:
            raise ValueError("SOC charge curve must start at 0")
        if curve and start <= curve[-1][0]:
            raise ValueError("SOC band starts must be strictly increasing")
        curve.append((float(start), float(power)))

    available_energy = float(available_dc_power_kw) * float(duration_hours)
    stored = float(stored_energy_kwh)
    dc_energy = 0.0
    captured_clipping_energy = 0.0
    time_left = float(duration_hours)
    power_ceiling = min(float(available_dc_power_kw), float(bms_max_dc_power_kw))

    while time_left > 0 and stored < capacity_kwh and power_ceiling > 0:
        band_index = 0
        for index, (start, _) in enumerate(curve):
            # Compare energy thresholds directly. Computing SOC by division can
            # round just below a band start (e.g. 32 * 0.91 / 32), which can
            # otherwise repeatedly select the preceding band at its boundary.
            if start * capacity_kwh <= stored:
                band_index = index
            else:
                break
        band_power = curve[band_index][1]
        dc_power = min(power_ceiling, band_power)
        if dc_power <= 0:
            break

        next_threshold = (
            curve[band_index + 1][0] * capacity_kwh
            if band_index + 1 < len(curve)
            else float(capacity_kwh)
        )
        to_threshold_stored = max(next_threshold - stored, 0.0)
        if to_threshold_stored <= 1e-12:
            # Advance the local band cursor without changing state energy.
            # This is a defensive tolerance path; exact boundary selection
            # above should normally make the next threshold strictly greater.
            if band_index + 1 < len(curve):
                band_index += 1
                band_power = curve[band_index][1]
                dc_power = min(power_ceiling, band_power)
                if dc_power <= 0:
                    break
                next_threshold = (
                    curve[band_index + 1][0] * capacity_kwh
                    if band_index + 1 < len(curve)
                    else float(capacity_kwh)
                )
                to_threshold_stored = max(next_threshold - stored, 0.0)
            if to_threshold_stored <= 1e-12:
                break

        dc_to_threshold = to_threshold_stored / charge_efficiency
        time_to_threshold = dc_to_threshold / dc_power
        step_time = min(time_left, time_to_threshold)
        accepted_dc = dc_power * step_time
        gained_stored = min(accepted_dc * charge_efficiency, capacity_kwh - stored)
        accepted_dc_actual = gained_stored / charge_efficiency
        captured_clipping_energy += min(
            min(dc_power, float(otherwise_clipped_dc_power_kw)) * step_time,
            accepted_dc_actual,
        )
        stored += gained_stored
        dc_energy += accepted_dc_actual
        time_left -= step_time
        if step_time <= 0:
            break

    # Guard floating-point dust at capacity without changing meaningful energy.
    if capacity_kwh - stored <= 1e-12:
        stored = float(capacity_kwh)
    unused = max(available_energy - dc_energy, 0.0)
    return ChargeResult(
        stored_energy_end_kwh=stored,
        dc_charge_energy_kwh=dc_energy,
        average_dc_charge_power_kw=dc_energy / duration_hours,
        unused_available_dc_energy_kwh=unused,
        captured_clipping_dc_energy_kwh=captured_clipping_energy,
    )


def discharge_to_house(
    *,
    stored_energy_kwh: float,
    required_house_ac_energy_kwh: float,
    duration_hours: float,
    max_discharge_dc_power_kw: float,
    reserve_energy_kwh: float,
    discharge_efficiency: float,
    inverter_efficiency: float,
) -> HouseDischargeResult:
    """Serve house AC demand from the battery without crossing its reserve.

    Stored-energy withdrawal first passes through battery discharge efficiency
    to available DC, then inverter efficiency to house AC. The DC power limit
    applies to available battery-side DC output. This transition is for house
    demand only; callers must not use it to serve EV demand.
    """
    for name, value in (
        ("stored_energy_kwh", stored_energy_kwh),
        ("required_house_ac_energy_kwh", required_house_ac_energy_kwh),
        ("duration_hours", duration_hours),
        ("max_discharge_dc_power_kw", max_discharge_dc_power_kw),
        ("reserve_energy_kwh", reserve_energy_kwh),
    ):
        _finite_nonnegative(name, value)
    _efficiency("discharge_efficiency", discharge_efficiency)
    _efficiency("inverter_efficiency", inverter_efficiency)
    if duration_hours <= 0:
        raise ValueError("duration_hours must be greater than zero")

    discharge_efficiency = float(discharge_efficiency)
    inverter_efficiency = float(inverter_efficiency)
    available_stored = max(float(stored_energy_kwh) - float(reserve_energy_kwh), 0.0)
    max_dc_energy = float(max_discharge_dc_power_kw) * float(duration_hours)
    max_stored_by_power = max_dc_energy / discharge_efficiency
    stored_withdrawn = min(
        available_stored,
        max_stored_by_power,
        float(required_house_ac_energy_kwh)
        / (discharge_efficiency * inverter_efficiency),
    )
    dc_energy = stored_withdrawn * discharge_efficiency
    house_served = dc_energy * inverter_efficiency
    return HouseDischargeResult(
        stored_energy_end_kwh=float(stored_energy_kwh) - stored_withdrawn,
        stored_energy_withdrawn_kwh=stored_withdrawn,
        available_dc_energy_kwh=dc_energy,
        house_ac_served_kwh=house_served,
        house_ac_unserved_kwh=max(float(required_house_ac_energy_kwh) - house_served, 0.0),
    )
