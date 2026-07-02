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
    ev_grid_bypass_enabled: bool = False
    ev_solar_charging_enabled: bool = False
    ev_cheap_grid_charging_enabled: bool = True
    heat_control_enabled: bool = False
    thermal_control_enabled: bool = False
    direct_climate_control_enabled: bool = False
    pv_load_test_control_enabled: bool = False
    export_limited_mode_enabled: bool = False
    return_to_normal_on_shed_enabled: bool = True
    forecast_full_override_enabled: bool = True
    thermal_rotation_enabled: bool = True
    auto_mode_month_fallback_enabled: bool = True
    strategy: str = "normal"
    heat_mode: str = "advisory"
    thermal_mode: str = "heating"
    thermal_actuation_mode: str = "advisory"
    flexible_load_priority: str = "battery_first"
    heat_add_min_charge_w: float = 6000.0
    heat_add_min_soc: float = 80.0
    heat_shed_discharge_w: float = 500.0
    heat_soak_target_temp: float = 27.0
    heat_normal_target_temp: float = 21.0
    cool_soak_target_temp: float = 18.0
    cool_normal_target_temp: float = 24.0
    thermal_start_min_soc: float = 80.0
    thermal_start_min_charge_w: float = 6000.0
    thermal_keep_running_min_charge_w: float = 1500.0
    thermal_shed_discharge_w: float = 500.0
    thermal_emergency_shed_w: float = 2500.0
    room_satisfied_delta_c: float = 0.7
    room_resume_delta_c: float = 1.5
    forecast_full_confidence_buffer_kwh: float = 3.0
    ev_start_load_jump_w: float = 5000.0
    ev_stop_load_drop_w: float = 6000.0
    ev_active_load_threshold_w: float = 1000.0
    ev_stopped_load_threshold_w: float = 300.0
    ev_hold_extra_minutes: float = 10.0
    ev_fallback_hold_minutes: float = 180.0
    ev_restore_program_power_w: float = 12000.0
    min_thermal_run_minutes: float = 20.0
    min_thermal_rest_minutes: float = 10.0
    thermal_rotation_cooldown_minutes: float = 15.0
    auto_heating_below_temp: float = 16.0
    auto_cooling_above_temp: float = 24.0
    forecast_safety_buffer_kwh: float = 2.0
    min_soc_floor: float = 12.0
    max_grid_charge_target_soc: float = 80.0
    pv_load_test_min_soc: float = 70.0
    pv_load_test_min_expected_power_w: float = 4000.0
    pv_load_test_max_battery_charge_w: float = 2500.0
    pv_load_test_min_remaining_forecast_kwh: float = 8.0
    heat_satisfied_margin_c: float = 0.5
    heat_need_margin_c: float = 1.0
    manual_override_cooldown_min: float = 60.0
    emergency_shed_discharge_w: float = 4000.0
    battery_capacity_kwh: float = 30.0
    overnight_bedroom_taper_target_temp: float = 18.0


@dataclass(frozen=True, slots=True)
class HeatLoadState:
    """Pure state for one managed heat load."""

    name: str
    priority: int
    slug: str | None = None
    climate_entity: str | None = None
    ownership_entity: str | None = None
    power_sensor: str | None = None
    is_on: bool = False
    solar_owned: bool = False
    current_temp: float | None = None
    target_temp: float | None = None
    estimated_load_w: float = 0.0
    blocked_until: datetime | None = None
    load_type: str = "other"
    hvac_mode: str | None = None
    hvac_action: str | None = None
    power_w: float | None = None
    active_power_threshold_w: float = 800.0
    idle_power_threshold_w: float = 150.0
    taper_power_threshold_w: float = 400.0
    enabled: bool = True
    supports_heating: bool = True
    supports_cooling: bool = False
    last_added_at: datetime | None = None
    last_shed_at: datetime | None = None
    last_rotated_at: datetime | None = None
    last_action: str | None = None
    last_action_reason: str | None = None


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
    outdoor_temperature: float | None = None
    indoor_average_temperature: float | None = None
    any_solar_owned_heat_load_on: bool = False
    heat_loads: list[HeatLoadState] = field(default_factory=list)
    heat_available: bool = False
    cooldown_passed: bool = True
    ev_latch_on: bool = False
    ev_hold_until: datetime | None = None
    ev_power_w: float | None = None
    ev_low_since: datetime | None = None
    porsche_soc: float | None = None
    porsche_charging_status: str | None = None
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
    thermal_allowed: bool
    thermal_should_shed: bool
    thermal_should_emergency_shed: bool
    forecast_full_override_active: bool
    thermal_rotation_recommended: bool
    thermal_should_return_to_normal: bool
    thermal_action: str
    thermal_action_reason: str
    effective_thermal_mode: str
    auto_mode_reason: str
    thermal_load_to_add: str | None
    thermal_load_to_shed: str | None
    thermal_load_to_normalise: str | None
    solar_owned_thermal_load_count: int
    active_thermal_loads: list[str]
    pv_load_test_recommended: bool
    heat_rotation_recommended: bool
    heat_load_to_shed: str | None
    heat_load_to_add: str | None
    emergency_shed_all_required: bool
    overnight_protection_required: bool
    bedroom_heat_taper_recommended: bool
    projected_soc_08: float | None
    grid_charge_required: bool
    ev_grid_mode_required: bool
    ev_charging_detected: bool
    ev_grid_bypass_required: bool
    ev_solar_charge_allowed: bool
    ev_latch_active: bool
    ev_decision_reason: str
    ev_expected_action: str
    ev_detected_power_w: float | None
    pre_peak_preserve_required: bool
    control_blocked: bool
    expected_action: str
    reason: str
    proposed_actions: list[str] = field(default_factory=list)
    forecast_today_kwh: float | None = None
    forecast_remaining_today_kwh: float | None = None
    forecast_tomorrow_kwh: float | None = None
    pv_power_now_w: float | None = None
    ev_hold_until: datetime | None = None
    forecast_data_valid: bool = True


@dataclass(slots=True)
class ThermalLoadDiagnostic:
    """Diagnostic status for one managed thermal load."""

    slug: str
    state: str
    attributes: dict[str, object | None]
