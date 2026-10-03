"""Read-only adapter from HA-like state snapshots to the pure solar advisory.

No Home Assistant imports or actuator calls: the coordinator supplies state
snapshots, persisted options and location. This boundary is testable offline.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import partial
from math import isfinite

from .const import FEATURE_DEFAULTS, NUMBER_DEFAULTS, TEXT_DEFAULTS
from .decision import time_between
from .models import EnergyManagerDecision, EnergyManagerInputs, EnergyManagerSettings
from .physical_solar import (
    PhysicalSolarSettings,
    clear_sky_dc_potential_kw,
    interval_clear_sky_dc_peak_kw,
)
from .solar_forecast import parse_detailed_forecast
from .solar_advisory import SolarAdvisory, SolarAdvisoryInput, recommend_solar_action

UNAVAILABLE = {"unknown", "unavailable", None}


def parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


def read_timestamp(states, entity_map: dict, key: str) -> datetime | None:
    state = states.get(entity_map.get(key, ""))
    return parse_datetime(state.state) if state is not None else None


def read_planning_sensor(states, entity_map, key: str, now: datetime, *, max_age_seconds: float = 600, reported_at=None) -> float:
    """Read fresh planning telemetry, normalising power to watts."""
    state = states.get(entity_map.get(key, ""))
    if state is None or state.state in UNAVAILABLE:
        raise ValueError(f"{key} unavailable")
    value = float(state.state)
    if not isfinite(value):
        raise ValueError(f"{key} nonfinite")
    reported = (reported_at(state) if reported_at else
                getattr(state, "last_reported", None) or getattr(state, "last_updated", None))
    if reported is None or reported.tzinfo is None:
        raise ValueError(f"{key} timestamp unavailable")
    age = (now - reported).total_seconds()
    if age < -5 or age > max_age_seconds:
        raise ValueError(f"{key} stale")
    unit = state.attributes.get("unit_of_measurement")
    expected_units = {"battery_soc": "%", "battery_voltage": "V", "battery_charge_limit_current": "A", "ev_voltage": "V", "grid_voltage": "V"}
    if key in expected_units and unit != expected_units[key]:
        raise ValueError(f"{key} unit must be {expected_units[key]}")
    if key in {"inverter_pv_power", "essential_power", "ev_power"}:
        if unit == "kW":
            value *= 1000
        elif unit != "W":
            raise ValueError(f"{key} power unit must be W or kW")
    if value < 0:
        raise ValueError(f"{key} negative")
    return value


def build_daytime_advisory(
    inputs: EnergyManagerInputs,
    settings: EnergyManagerSettings,
    decision: EnergyManagerDecision,
    *, options: dict, entity_map: dict, states, latitude: float, longitude: float,
    state_reported_at=None,
) -> SolarAdvisory | None:
    """Build a read-only interval advisory; never replace actuator decisions."""
    options = {**FEATURE_DEFAULTS, **NUMBER_DEFAULTS, **TEXT_DEFAULTS, **options}
    read_sensor = partial(read_planning_sensor, reported_at=state_reported_at)
    if not options.get("daytime_plan_enabled", False):
        return None
    if not settings.enabled or not settings.advisory_enabled:
        return SolarAdvisory(valid=False, reason="manager advisory disabled")
    try:
        sun = states.get(entity_map.get("sun", "sun.sun"))
        if sun is None or sun.state != "above_horizon":
            return SolarAdvisory(valid=False, reason="outside daylight or sun unavailable")
        sunset = parse_datetime(str(sun.attributes.get("next_setting", "")))
        if sunset is None or sunset.tzinfo is None or sunset <= inputs.now:
            raise ValueError("daylight deadline unavailable")
        curve_raw = options.get("solar_plan_charge_acceptance_curve", "")
        if not curve_raw or not str(curve_raw).strip():
            raise ValueError("charge acceptance curve not configured")
        curve = json.loads(str(curve_raw))
        if not isinstance(curve, list) or not curve:
            raise ValueError("charge acceptance curve must contain SOC fraction / DC kW pairs")
        forecast_state = states.get(entity_map.get("forecast_today", ""))
        if forecast_state is None:
            raise ValueError("detailed forecast unavailable")
        source_updated = read_timestamp(states, entity_map, "forecast_updated_at")
        if source_updated is None:
            raise ValueError("forecast supplier timestamp unavailable")
        forecast = parse_detailed_forecast(
            forecast_state.attributes.get("detailedForecast", []),
            now=inputs.now,
            deadline=sunset,
            source_updated_at=source_updated,
            max_age=timedelta(minutes=float(options["solar_plan_max_forecast_age_minutes"])),
        )
        soc = read_sensor(states, entity_map, "battery_soc", inputs.now)
        pv_w = read_sensor(states, entity_map, "inverter_pv_power", inputs.now, max_age_seconds=120)
        essential_w = read_sensor(states, entity_map, "essential_power", inputs.now, max_age_seconds=120)
        battery_v = read_sensor(states, entity_map, "battery_voltage", inputs.now)
        bms_a = read_sensor(states, entity_map, "battery_charge_limit_current", inputs.now)
        if not 0 <= soc <= 100 or battery_v <= 0:
            raise ValueError("invalid battery SOC or voltage")
        try:
            ev_w = read_sensor(states, entity_map, "ev_power", inputs.now, max_age_seconds=120)
        except ValueError:
            if inputs.ev_charge_requested is not False:
                raise
            ev_w = 0.0
        if ev_w > essential_w + 500:
            raise ValueError("EV power exceeds essential load; telemetry is inconsistent")
        ev_allowed = (
            settings.ev_solar_charging_enabled
            and not inputs.ev_manual_charging_override
            and inputs.porsche_soc is not None
            and inputs.porsche_soc < settings.ev_solar_target_soc
            and (inputs.ev_connector_status or "").lower()
            in {"preparing", "charging", "suspendedev", "suspendedevse", "finishing"}
            and not time_between(inputs.now, "21:00", "07:00")
        )
        voltage = 230.0
        if ev_allowed:
            try:
                voltage = read_sensor(states, entity_map, "ev_voltage", inputs.now)
            except ValueError:
                # TIMXON may stop reporting voltage between transactions.
                # The single-phase inverter supply is an independent live
                # estimate for planning; never reuse an old charger sample.
                voltage = read_sensor(states, entity_map, "grid_voltage", inputs.now,
                                               max_age_seconds=120)
        base_load = inputs.base_load_estimate_w
        if base_load is None or not isfinite(base_load) or base_load < 0:
            raise ValueError("non-EV base load unavailable")
        capacity = settings.battery_capacity_kwh
        buffer_kwh = (
            settings.forecast_safety_buffer_kwh
            + settings.house_load_forecast_buffer_kwh
            + decision.committed_flexible_load_energy_kwh
        )
        physical = PhysicalSolarSettings(
            latitude_deg=float(latitude),
            longitude_deg=float(longitude),
            panel_tilt_deg=float(options["solar_plan_array_tilt_deg"]),
            panel_azimuth_deg=float(options["solar_plan_array_azimuth_deg"]),
            pv_capacity_kw=float(options["solar_plan_array_capacity_kw"]),
            clear_sky_scale=float(options["solar_plan_clear_sky_scale"]),
            pv_dc_cap_kw=float(options["solar_plan_pv_dc_limit_kw"]),
        )
        physical_scenario = tuple(
            clear_sky_dc_potential_kw(
                interval.start + (interval.end - interval.start) / 2,
                physical,
                weather_factor=float(options["solar_plan_clear_sky_weather_factor"]),
            )
            for interval in forecast.intervals
        )
        return recommend_solar_action(SolarAdvisoryInput(
            forecast=forecast,
            now=inputs.now,
            current_soc_pct=soc,
            capacity_kwh=capacity,
            target_soc_pct=settings.daily_battery_target_soc,
            reserve_energy_kwh=capacity * decision.active_reserve_target_soc / 100,
            non_ev_base_house_kw=base_load / 1000,
            # A manual session remains an actual load that this solar plan
            # cannot turn down. Do not allocate its power to the battery.
            # OCPP publication time is not the meter's sample time. A delayed
            # EV reading can make subtraction understate house load even when
            # it passes the gross-consistency check above. Preserve the base
            # load estimate as a conservative floor, not as synchronized data.
            current_non_ev_house_kw=(
                essential_w if inputs.ev_manual_charging_override
                else max(essential_w - ev_w, base_load)
            ) / 1000,
            live_pv_dc_kw=pv_w / 1000,
            voltage_v=voltage,
            live_bms_max_dc_kw=bms_a * battery_v / 1000,
            soc_charge_curve=curve,
            inverter_efficiency=float(options["solar_plan_inverter_efficiency"]),
            battery_charge_efficiency=settings.battery_charge_efficiency,
            battery_discharge_efficiency=float(options["solar_plan_discharge_efficiency"]),
            inverter_ac_limit_kw=float(options["solar_plan_inverter_ac_limit_kw"]),
            export_limit_kw=float(options["solar_plan_export_limit_kw"]),
            site_ac_limit_kw=float(options["solar_plan_site_ac_limit_kw"]),
            max_battery_dc_kw=float(options["solar_plan_battery_max_charge_dc_kw"]),
            max_discharge_dc_kw=float(options["solar_plan_battery_max_discharge_dc_kw"]),
            safety_buffer_kwh=buffer_kwh,
            max_ev_amps=32,
            ev_allowed=ev_allowed,
            forecast_p50_weight=float(options["solar_plan_forecast_risk_blend"]),
            forecast_max_age=timedelta(minutes=float(options["solar_plan_max_forecast_age_minutes"])),
            physical_dc_upper_kw=physical_scenario,
            clipping_envelope_dc_kw=tuple(
                interval_clear_sky_dc_peak_kw(
                    interval.start,
                    interval.end,
                    physical,
                    weather_factor=1.1,
                ) for interval in forecast.intervals
            ),
        ))
    except (ValueError, TypeError, KeyError) as err:
        return SolarAdvisory(valid=False, reason=f"daytime planning unavailable: {err}")
