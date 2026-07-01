"""Pure models for Deye Energy Manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class EnergyManagerSettings:
    """Configurable thresholds and feature gates."""

    enabled: bool = True
    advisory_enabled: bool = True
    deye_control_enabled: bool = False
    grid_charge_control_enabled: bool = False
    ev_control_enabled: bool = False
    heat_control_enabled: bool = False
    direct_climate_control_enabled: bool = False
    pv_load_test_control_enabled: bool = False
    export_limited_mode_enabled: bool = False
    strategy: str = "normal"
    heat_mode: str = "advisory"
    heat_add_min_charge_w: float = 6000.0
    heat_add_min_soc: float = 90.0
    heat_shed_discharge_w: float = 500.0
    ev_start_load_jump_w: float = 5000.0
    ev_stop_load_drop_w: float = 6000.0
    forecast_safety_buffer_kwh: float = 2.0
    min_soc_floor: float = 12.0
    max_grid_charge_target_soc: float = 80.0
    pv_load_test_min_soc: float = 70.0
    pv_load_test_min_expected_power_w: float = 4000.0
    pv_load_test_max_battery_charge_w: float = 2500.0
    pv_load_test_min_remaining_forecast_kwh: float = 8.0
    heat_satisfied_margin_c: float = 0.5
    heat_need_margin_c: float = 1.0


@dataclass(frozen=True, slots=True)
class HeatLoadState:
    """Pure state for one managed heat load."""

    name: str
    priority: int
    is_on: bool = False
    solar_owned: bool = False
    current_temp: float | None = None
    target_temp: float | None = None
    estimated_load_w: float = 0.0


@dataclass(slots=True)
class EnergyManagerInputs:
    """State snapshot consumed by the decision engine."""

    now: datetime
    battery_soc: float = 0.0
    battery_power_w: float = 0.0
    essential_power_w: float = 0.0
    previous_essential_power_w: float | None = None
    forecast_today_kwh: float | None = None
    forecast_remaining_today_kwh: float | None = None
    forecast_tomorrow_kwh: float | None = None
    pv_power_now_w: float | None = None
    pv_power_in_30_minutes_w: float | None = None
    pv_power_in_1_hour_w: float | None = None
    any_solar_owned_heat_load_on: bool = False
    heat_loads: list[HeatLoadState] = field(default_factory=list)
    heat_available: bool = False
    cooldown_passed: bool = True
    ev_latch_on: bool = False
    ev_hold_until: datetime | None = None
    porsche_soc: float | None = None
    porsche_charging_ends: datetime | None = None
    manual_clear_ev_latch: bool = False


@dataclass(frozen=True, slots=True)
class ForecastTier:
    """Forecast policy tier."""

    mode: str
    overnight_floor: float
    morning_floor: float
    pre_peak_floor: float
    peak_floor: float
    target_17_soc: float
    grid_charge_target_soc: float


@dataclass(slots=True)
class EnergyManagerDecision:
    """Decision output published by entities and consumed by controls."""

    now: datetime
    forecast_mode: str
    active_slot: str
    tariff_window: str
    target_17_soc: float
    current_reserve_soc: float
    grid_charge_target_soc: float
    battery_soc: float
    battery_power_w: float
    battery_charge_w: float
    battery_discharge_w: float
    battery_priority_satisfied: bool
    heat_allowed: bool
    heat_should_shed: bool
    pv_load_test_recommended: bool
    heat_rotation_recommended: bool
    heat_load_to_shed: str | None
    heat_load_to_add: str | None
    grid_charge_required: bool
    ev_grid_mode_required: bool
    pre_peak_preserve_required: bool
    control_blocked: bool
    reason: str
    proposed_actions: list[str] = field(default_factory=list)
    forecast_today_kwh: float | None = None
    forecast_remaining_today_kwh: float | None = None
    forecast_tomorrow_kwh: float | None = None
    pv_power_now_w: float | None = None
    ev_hold_until: datetime | None = None
    forecast_data_valid: bool = True
