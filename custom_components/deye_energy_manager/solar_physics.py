"""Pure interval-level solar allocation and energy accounting.

All power inputs are in kW, stored energies are in kWh, and interval duration
is in hours. This model handles only PV-fed house, battery, EV and export
flows. It does not model battery discharge or grid charging: any house AC load
that PV cannot serve is supplied by grid import.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class SolarIntervalInput:
    """Inputs for one fixed-duration solar allocation interval."""

    duration_hours: float
    pv_dc_kw: float
    non_ev_house_ac_kw: float
    ev_requested_ac_kw: float
    battery_requested_dc_kw: float
    battery_stored_kwh: float
    battery_capacity_kwh: float
    battery_bms_max_dc_kw: float
    battery_acceptance_max_dc_kw: float
    inverter_ac_limit_kw: float
    export_limit_kw: float
    inverter_efficiency: float
    battery_efficiency: float


@dataclass(frozen=True, slots=True)
class SolarIntervalResult:
    """PV allocations and interval energy totals, with powers in kW."""

    house_pv_ac_kw: float
    house_grid_import_ac_kw: float
    battery_charge_dc_kw: float
    battery_stored_delta_kwh: float
    battery_stored_end_kwh: float
    ev_requested_ac_kw: float
    ev_served_ac_kw: float
    ev_unserved_ac_kw: float
    export_ac_kw: float
    inverter_ac_output_kw: float
    inverter_ac_input_dc_kw: float
    inverter_conversion_loss_kw: float
    battery_charge_loss_kw: float
    clipped_pv_dc_kw: float
    pv_dc_energy_kwh: float
    dc_to_inverter_energy_kwh: float
    battery_dc_energy_kwh: float
    clipped_pv_energy_kwh: float


def _validate(inputs: SolarIntervalInput) -> None:
    nonnegative = (
        "duration_hours",
        "pv_dc_kw",
        "non_ev_house_ac_kw",
        "ev_requested_ac_kw",
        "battery_requested_dc_kw",
        "battery_stored_kwh",
        "battery_capacity_kwh",
        "battery_bms_max_dc_kw",
        "battery_acceptance_max_dc_kw",
        "inverter_ac_limit_kw",
        "export_limit_kw",
    )
    for name in nonnegative:
        value = getattr(inputs, name)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")

    if inputs.duration_hours <= 0:
        raise ValueError("duration_hours must be greater than zero")
    for name in ("inverter_efficiency", "battery_efficiency"):
        value = getattr(inputs, name)
        if not math.isfinite(value) or not 0 < value <= 1:
            raise ValueError(f"{name} must be finite and in (0, 1]")
    if inputs.battery_stored_kwh > inputs.battery_capacity_kwh:
        raise ValueError("battery_stored_kwh cannot exceed battery_capacity_kwh")


def simulate_solar_interval(inputs: SolarIntervalInput) -> SolarIntervalResult:
    """Allocate PV for house, requested battery charging, EV, then export.

    The house load has first claim on PV through the inverter. The explicit
    battery request is then served from remaining DC PV, limited by request,
    measured BMS acceptance, separately modelled battery charge acceptance,
    PV remaining, and battery headroom. EV charging uses the remaining
    PV-backed AC capacity; export receives what remains after the EV, subject
    to the export and inverter limits. PV that cannot be consumed or exported
    is reported as clipped. The caller must apply any upstream PV hardware or
    input limit before supplying ``pv_dc_kw``; this is not a complete shared
    DC-bus or inverter mode model. No allocation can charge the battery from
    grid power or discharge it to serve a house/EV load.
    """

    _validate(inputs)
    duration = inputs.duration_hours
    inverter_efficiency = inputs.inverter_efficiency

    # Serve the non-EV house load first. A deficit is grid import; the battery
    # is deliberately not dispatched in this solar-only calculation.
    house_pv_ac_kw = min(
        inputs.non_ev_house_ac_kw,
        inputs.inverter_ac_limit_kw,
        inputs.pv_dc_kw * inverter_efficiency,
    )
    house_dc_kw = house_pv_ac_kw / inverter_efficiency
    pv_remaining_dc_kw = max(inputs.pv_dc_kw - house_dc_kw, 0.0)

    headroom_dc_kw = max(
        inputs.battery_capacity_kwh - inputs.battery_stored_kwh, 0.0
    ) / (duration * inputs.battery_efficiency)
    battery_charge_dc_kw = min(
        inputs.battery_requested_dc_kw,
        inputs.battery_bms_max_dc_kw,
        inputs.battery_acceptance_max_dc_kw,
        headroom_dc_kw,
        pv_remaining_dc_kw,
    )
    pv_remaining_dc_kw = max(pv_remaining_dc_kw - battery_charge_dc_kw, 0.0)

    inverter_ac_headroom_kw = max(
        inputs.inverter_ac_limit_kw - house_pv_ac_kw, 0.0
    )
    pv_to_ac_headroom_kw = pv_remaining_dc_kw * inverter_efficiency
    ev_served_ac_kw = min(
        inputs.ev_requested_ac_kw,
        inverter_ac_headroom_kw,
        pv_to_ac_headroom_kw,
    )
    ev_dc_kw = ev_served_ac_kw / inverter_efficiency
    pv_remaining_dc_kw = max(pv_remaining_dc_kw - ev_dc_kw, 0.0)

    inverter_ac_headroom_kw = max(
        inputs.inverter_ac_limit_kw - house_pv_ac_kw - ev_served_ac_kw,
        0.0,
    )
    export_ac_kw = min(
        inputs.export_limit_kw,
        inverter_ac_headroom_kw,
        pv_remaining_dc_kw * inverter_efficiency,
    )
    export_dc_kw = export_ac_kw / inverter_efficiency
    clipped_pv_dc_kw = max(pv_remaining_dc_kw - export_dc_kw, 0.0)

    inverter_ac_output_kw = house_pv_ac_kw + ev_served_ac_kw + export_ac_kw
    inverter_ac_input_dc_kw = inverter_ac_output_kw / inverter_efficiency
    battery_stored_delta_kwh = (
        battery_charge_dc_kw * duration * inputs.battery_efficiency
    )
    battery_stored_end_kwh = min(
        inputs.battery_capacity_kwh,
        inputs.battery_stored_kwh + battery_stored_delta_kwh,
    )

    return SolarIntervalResult(
        house_pv_ac_kw=house_pv_ac_kw,
        house_grid_import_ac_kw=max(inputs.non_ev_house_ac_kw - house_pv_ac_kw, 0.0),
        battery_charge_dc_kw=battery_charge_dc_kw,
        battery_stored_delta_kwh=battery_stored_delta_kwh,
        battery_stored_end_kwh=battery_stored_end_kwh,
        ev_requested_ac_kw=inputs.ev_requested_ac_kw,
        ev_served_ac_kw=ev_served_ac_kw,
        ev_unserved_ac_kw=max(inputs.ev_requested_ac_kw - ev_served_ac_kw, 0.0),
        export_ac_kw=export_ac_kw,
        inverter_ac_output_kw=inverter_ac_output_kw,
        inverter_ac_input_dc_kw=inverter_ac_input_dc_kw,
        inverter_conversion_loss_kw=inverter_ac_input_dc_kw - inverter_ac_output_kw,
        battery_charge_loss_kw=battery_charge_dc_kw * (1 - inputs.battery_efficiency),
        clipped_pv_dc_kw=clipped_pv_dc_kw,
        pv_dc_energy_kwh=inputs.pv_dc_kw * duration,
        dc_to_inverter_energy_kwh=inverter_ac_input_dc_kw * duration,
        battery_dc_energy_kwh=battery_charge_dc_kw * duration,
        clipped_pv_energy_kwh=clipped_pv_dc_kw * duration,
    )
