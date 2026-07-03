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
    shed_unowned_managed_loads_on_battery_discharge: bool = False
    morning_preheat_enabled: bool = True
    passive_warming_guard_enabled: bool = True
    paid_time_grid_avoidance_enabled: bool = True
    underfloor_schedule_enabled: bool = True
    underfloor_require_home: bool = True
    underfloor_allow_paid_grid: bool = False
    auto_mode_month_fallback_enabled: bool = True
    max_fallback_soc_age_minutes: float = 360.0
    strategy: str = "normal"
    heat_mode: str = "advisory"
    thermal_mode: str = "heating"
    thermal_actuation_mode: str = "advisory"
    flexible_load_priority: str = "battery_first"
    heat_soak_fan_mode: str = "high"
    heat_normal_fan_mode: str = "low"
    cool_soak_fan_mode: str = "high"
    cool_normal_fan_mode: str = "low"
    heat_add_min_charge_w: float = 6000.0
    heat_add_min_soc: float = 80.0
    heat_shed_discharge_w: float = 500.0
    heat_soak_target_temp: float = 27.0
    heat_normal_target_temp: float = 21.0
    cool_soak_target_temp: float = 18.0
    cool_normal_target_temp: float = 24.0
    heat_comfort_target_temp: float = 21.0
    cool_comfort_target_temp: float = 24.0
    comfort_min_room_temp: float = 19.0
    full_soak_min_soc: float = 90.0
    forecast_soak_min_soc: float = 75.0
    morning_battery_priority_soc: float = 70.0
    morning_preheat_start_hour: float = 7.0
    morning_preheat_end_hour: float = 9.0
    morning_preheat_min_room_temp: float = 18.5
    morning_preheat_target_temp: float = 21.0
    morning_preheat_min_soc: float = 40.0
    morning_preheat_max_grid_import_w: float = 500.0
    morning_preheat_forecast_buffer_kwh: float = 3.0
    morning_preheat_fan_mode: str = "low"
    paid_time_min_reserve_soc: float = 40.0
    morning_paid_time_min_reserve_soc: float = 45.0
    evening_paid_time_min_reserve_soc: float = 30.0
    pre_peak_preserve_min_reserve_soc: float = 75.0
    paid_grid_import_threshold_w: float = 500.0
    paid_grid_import_grace_minutes: float = 2.0
    solar_arrived_charge_threshold_w: float = 1500.0
    solar_arrived_pv_surplus_threshold_w: float = 1000.0
    daily_battery_target_soc: float = 100.0
    battery_charge_efficiency: float = 0.94
    base_load_estimate_w: float = 1200.0
    base_load_window_minutes: float = 30.0
    house_load_forecast_buffer_kwh: float = 1.5
    solar_soak_required_battery_margin_kwh: float = 1.0
    paid_grid_avoidance_buffer_kwh: float = 1.0
    dynamic_base_load_estimate_enabled: bool = True
    underfloor_morning_start_hour: float = 7.0
    underfloor_morning_end_hour: float = 9.0
    underfloor_evening_start_hour: float = 16.0
    underfloor_evening_end_hour: float = 24.0
    underfloor_preheat_minutes: float = 60.0
    underfloor_comfort_min_temp: float = 9.0
    underfloor_comfort_target_temp: float = 12.0
    underfloor_max_target_temp: float = 14.0
    underfloor_min_soc: float = 40.0
    underfloor_max_grid_import_w: float = 500.0
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
    fan_mode: str | None = None
    supported_fan_modes: tuple[str, ...] = ()
    power_w: float | None = None
    active_power_threshold_w: float = 800.0
    idle_power_threshold_w: float = 150.0
    taper_power_threshold_w: float = 400.0
    enabled: bool = True
    supports_heating: bool = True
    supports_cooling: bool = False
    owner: str = "none"
    lease_reason: str = "none"
    lease_started_at: datetime | None = None
    lease_until: datetime | None = None
    desired_hvac_mode: str | None = None
    desired_temperature: float | None = None
    desired_fan_mode: str | None = None
    normal_hvac_mode: str | None = None
    normal_temperature: float | None = None
    normal_fan_mode: str | None = None
    pending_confirmation_until: datetime | None = None
    manual_override_until: datetime | None = None
    last_manager_action_at: datetime | None = None
    last_external_change_at: datetime | None = None
    external_change_detected: bool = False
    allow_unowned_battery_shed: bool = True
    never_emergency_shed: bool = False
    comfort_sensor_type: str = "air"
    comfort_min_temp: float | None = None
    comfort_target_temp: float | None = None
    normal_target_temp: float | None = None
    allow_solar_soak: bool = True
    last_added_at: datetime | None = None
    last_shed_at: datetime | None = None
    last_rotated_at: datetime | None = None
    last_action: str | None = None
    last_action_reason: str | None = None


@dataclass(slots=True)
class EnergyManagerInputs:
    """State snapshot consumed by the decision engine."""

    now: datetime
    battery_soc: float | None = 0.0
    raw_soc: str | None = None
    soc_source: str = "live"
    soc_age_minutes: float | None = None
    battery_power_w: float = 0.0
    essential_power_w: float = 0.0
    grid_power_w: float = 0.0
    base_load_estimate_w: float | None = None
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
    battery_soc: float | None
    raw_soc: str | None
    resolved_soc: float | None
    soc_source: str
    soc_age_minutes: float | None
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
    thermal_policy_state: str
    solar_phase: str
    passive_warming_likely: bool
    passive_warming_reason: str
    battery_priority_reason: str
    comfort_heat_allowed: bool
    solar_soak_allowed: bool
    full_send_soak_allowed: bool
    morning_preheat_allowed: bool
    morning_preheat_reason: str
    morning_preheat_load_to_add: str | None
    underfloor_comfort_allowed: bool
    underfloor_policy_state: str
    underfloor_reason: str
    underfloor_load_to_add: str | None
    underfloor_current_window: str
    paid_grid_avoidance_required: bool
    paid_time_reserve_reason: str
    paid_time_floor_soc: float
    active_reserve_target_soc: float
    active_reserve_current_soc: float
    paid_grid_import_w: float
    solar_arrived: bool
    solar_arrived_reason: str
    forecast_drain_blocked: bool
    thermal_target_temperature: float | None
    thermal_target_fan_mode: str | None
    thermal_target_hvac_mode: str | None
    thermal_lease_reason: str
    daily_battery_target_soc: float
    remaining_solar_budget_kwh: float
    battery_kwh_needed_to_target: float | None
    expected_house_load_until_solar_end_kwh: float
    safety_buffer_kwh: float
    discretionary_energy_budget_kwh: float | None
    energy_budget_reason: str
    discretionary_budget_positive: bool
    battery_target_reachable_today: bool
    base_load_estimate_w: float
    estimated_solar_hours_remaining: float
    committed_flexible_load_energy_kwh: float
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
