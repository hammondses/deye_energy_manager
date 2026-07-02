"""Coordinator and safe actuator helpers for Deye Energy Manager."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CHARGE_OPTION_ALLOW_GRID,
    CHARGE_OPTION_NO_GRID,
    CONF_ENTITY_MAP,
    CONF_HEAT_LOADS,
    DEFAULT_ENTITY_MAP,
    DEFAULT_HEAT_LOADS,
    DEFAULT_HEAT_MODE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STRATEGY,
    DEFAULT_THERMAL_ACTUATION_MODE,
    DEFAULT_THERMAL_MODE,
    FAN_MODE_DEFAULTS,
    FEATURE_DEFAULTS,
    NUMBER_DEFAULTS,
    PROG_CAPACITY_ENTITIES,
    PROG_CHARGE_SELECT_ENTITIES,
    PROG_POWER_ENTITIES,
)
from .decision import decide, forecast_tier, resolve_soc_value, slot_capacity_targets, thermal_load_diagnostics
from .migration import infer_load_slug
from .models import EnergyManagerDecision, EnergyManagerInputs, EnergyManagerSettings, HeatLoadState
from .repairs import async_update_issues

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE = {"unknown", "unavailable", None}


class DeyeEnergyManagerCoordinator(DataUpdateCoordinator[EnergyManagerDecision]):
    """Collect HA state, calculate decisions, and perform gated writes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""

        super().__init__(
            hass,
            _LOGGER,
            name="Deye Energy Manager",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self.started_at = dt_util.utcnow()
        self.previous_essential_power_w: float | None = None
        self.ev_latch_on = False
        self.ev_hold_until: datetime | None = None
        self.ev_low_since: datetime | None = None
        self.last_control_action = "none"
        self._last_written: dict[str, object] = {}
        self._heat_blocked_until: dict[str, datetime] = {}
        self._thermal_last_added_at: dict[str, datetime] = {}
        self._thermal_last_shed_at: dict[str, datetime] = {}
        self._thermal_last_rotated_at: dict[str, datetime] = {}
        self._thermal_last_action: dict[str, tuple[str, str]] = {}
        self.recent_proposed_actions: deque[dict[str, object | None]] = deque(maxlen=10)
        self.load_diagnostics: dict[str, object] = {}
        self._remove_listeners: list[Callable[[], None]] = []

        watch_entities = [entity for entity in self.entity_map.values() if entity]
        self._remove_listeners.append(
            async_track_state_change_event(hass, watch_entities, self._handle_state_change)
        )
        self._remove_listeners.append(
            async_track_time_interval(hass, self._handle_time_interval, DEFAULT_SCAN_INTERVAL)
        )
        entry.async_on_unload(self._remove_all_listeners)

    @property
    def entity_map(self) -> dict[str, str]:
        """Return configured entity mappings."""

        configured = self.entry.options.get(CONF_ENTITY_MAP, self.entry.data.get(CONF_ENTITY_MAP, {}))
        return {**DEFAULT_ENTITY_MAP, **configured}

    @property
    def heat_loads(self) -> list[dict[str, object]]:
        """Return configured heat loads."""

        configured = self.entry.options.get(CONF_HEAT_LOADS, self.entry.data.get(CONF_HEAT_LOADS, DEFAULT_HEAT_LOADS))
        loads = list(configured) or list(DEFAULT_HEAT_LOADS)
        return [self._normalise_heat_load(load) for load in loads]

    def _normalise_heat_load(self, load: dict[str, object]) -> dict[str, object]:
        """Return a load config with a stable slug for entity unique IDs."""

        normalised = dict(load)
        normalised["slug"] = str(normalised.get("slug") or infer_load_slug(normalised))
        return normalised

    @property
    def settings(self) -> EnergyManagerSettings:
        """Build settings from config entry options."""

        options = {**FEATURE_DEFAULTS, **FAN_MODE_DEFAULTS, **NUMBER_DEFAULTS, **self.entry.options}
        return EnergyManagerSettings(
            enabled=bool(options["enabled"]),
            advisory_enabled=bool(options["advisory_enabled"]),
            deye_control_enabled=bool(options["deye_control_enabled"]),
            grid_charge_control_enabled=bool(options["grid_charge_control_enabled"]),
            ev_control_enabled=bool(options["ev_control_enabled"]),
            ev_grid_bypass_enabled=bool(options["ev_grid_bypass_enabled"]),
            ev_solar_charging_enabled=bool(options["ev_solar_charging_enabled"]),
            ev_cheap_grid_charging_enabled=bool(options["ev_cheap_grid_charging_enabled"]),
            heat_control_enabled=bool(options["heat_control_enabled"]),
            thermal_control_enabled=bool(options["thermal_control_enabled"] or options["heat_control_enabled"]),
            direct_climate_control_enabled=bool(options["direct_climate_control_enabled"]),
            pv_load_test_control_enabled=bool(options["pv_load_test_control_enabled"]),
            export_limited_mode_enabled=bool(options["export_limited_mode_enabled"]),
            return_to_normal_on_shed_enabled=bool(options["return_to_normal_on_shed_enabled"]),
            forecast_full_override_enabled=bool(options["forecast_full_override_enabled"]),
            thermal_rotation_enabled=bool(options["thermal_rotation_enabled"]),
            shed_unowned_managed_loads_on_battery_discharge=bool(options["shed_unowned_managed_loads_on_battery_discharge"]),
            auto_mode_month_fallback_enabled=bool(options["auto_mode_month_fallback_enabled"]),
            max_fallback_soc_age_minutes=float(options["max_fallback_soc_age_minutes"]),
            strategy=str(options.get("strategy", DEFAULT_STRATEGY)),
            heat_mode=str(options.get("heat_mode", DEFAULT_HEAT_MODE)),
            thermal_mode=str(options.get("thermal_mode", DEFAULT_THERMAL_MODE)),
            thermal_actuation_mode=self._effective_thermal_actuation_mode(options),
            flexible_load_priority=str(options.get("flexible_load_priority", "battery_first")),
            heat_soak_fan_mode=str(options["heat_soak_fan_mode"]),
            heat_normal_fan_mode=str(options["heat_normal_fan_mode"]),
            cool_soak_fan_mode=str(options["cool_soak_fan_mode"]),
            cool_normal_fan_mode=str(options["cool_normal_fan_mode"]),
            heat_add_min_charge_w=float(options.get("heat_add_min_charge_w", options["thermal_start_min_charge_w"])),
            heat_add_min_soc=float(options.get("heat_add_min_soc", options["thermal_start_min_soc"])),
            heat_shed_discharge_w=float(options.get("heat_shed_discharge_w", options["thermal_shed_discharge_w"])),
            heat_soak_target_temp=float(options["heat_soak_target_temp"]),
            heat_normal_target_temp=float(options["heat_normal_target_temp"]),
            cool_soak_target_temp=float(options["cool_soak_target_temp"]),
            cool_normal_target_temp=float(options["cool_normal_target_temp"]),
            thermal_start_min_soc=float(options.get("thermal_start_min_soc", options.get("heat_add_min_soc", 80.0))),
            thermal_start_min_charge_w=float(options.get("thermal_start_min_charge_w", options.get("heat_add_min_charge_w", 6000.0))),
            thermal_keep_running_min_charge_w=float(options["thermal_keep_running_min_charge_w"]),
            thermal_shed_discharge_w=float(options.get("thermal_shed_discharge_w", options.get("heat_shed_discharge_w", 500.0))),
            thermal_emergency_shed_w=float(options["thermal_emergency_shed_w"]),
            room_satisfied_delta_c=float(options["room_satisfied_delta_c"]),
            room_resume_delta_c=float(options["room_resume_delta_c"]),
            forecast_full_confidence_buffer_kwh=float(options["forecast_full_confidence_buffer_kwh"]),
            ev_start_load_jump_w=float(options["ev_start_load_jump_w"]),
            ev_stop_load_drop_w=float(options["ev_stop_load_drop_w"]),
            ev_active_load_threshold_w=float(options["ev_active_load_threshold_w"]),
            ev_stopped_load_threshold_w=float(options["ev_stopped_load_threshold_w"]),
            ev_hold_extra_minutes=float(options["ev_hold_extra_minutes"]),
            ev_fallback_hold_minutes=float(options["ev_fallback_hold_minutes"]),
            ev_restore_program_power_w=float(options["ev_restore_program_power_w"]),
            min_thermal_run_minutes=float(options["min_thermal_run_minutes"]),
            min_thermal_rest_minutes=float(options["min_thermal_rest_minutes"]),
            thermal_rotation_cooldown_minutes=float(options["thermal_rotation_cooldown_minutes"]),
            auto_heating_below_temp=float(options["auto_heating_below_temp"]),
            auto_cooling_above_temp=float(options["auto_cooling_above_temp"]),
            forecast_safety_buffer_kwh=float(options["forecast_safety_buffer_kwh"]),
            min_soc_floor=float(options["min_soc_floor"]),
            max_grid_charge_target_soc=float(options["max_grid_charge_target_soc"]),
            pv_load_test_min_soc=float(options["pv_load_test_min_soc"]),
            pv_load_test_min_expected_power_w=float(options["pv_load_test_min_expected_power_w"]),
            pv_load_test_max_battery_charge_w=float(options["pv_load_test_max_battery_charge_w"]),
            pv_load_test_min_remaining_forecast_kwh=float(options["pv_load_test_min_remaining_forecast_kwh"]),
            heat_satisfied_margin_c=float(options["heat_satisfied_margin_c"]),
            heat_need_margin_c=float(options["heat_need_margin_c"]),
            manual_override_cooldown_min=float(options["manual_override_cooldown_min"]),
            emergency_shed_discharge_w=float(options.get("emergency_shed_discharge_w", options["thermal_emergency_shed_w"])),
            battery_capacity_kwh=float(options["battery_capacity_kwh"]),
            overnight_bedroom_taper_target_temp=float(options["overnight_bedroom_taper_target_temp"]),
        )

    def _legacy_thermal_actuation_mode(self, options: dict[str, object]) -> str:
        heat_mode = str(options.get("heat_mode", DEFAULT_HEAT_MODE))
        if heat_mode == "auto_scripts":
            return "scripts"
        if heat_mode == "auto_direct":
            return "direct"
        return DEFAULT_THERMAL_ACTUATION_MODE

    def _effective_thermal_actuation_mode(self, options: dict[str, object]) -> str:
        thermal_mode = str(options.get("thermal_actuation_mode", DEFAULT_THERMAL_ACTUATION_MODE))
        legacy_mode = self._legacy_thermal_actuation_mode(options)
        if (
            bool(options.get("heat_control_enabled", False))
            and thermal_mode == DEFAULT_THERMAL_ACTUATION_MODE
            and legacy_mode != DEFAULT_THERMAL_ACTUATION_MODE
        ):
            return legacy_mode
        return thermal_mode

    @callback
    def _handle_state_change(self, _event) -> None:
        self.async_set_updated_data(self._calculate())
        self.hass.async_create_task(self.async_apply_decision())

    @callback
    def _handle_time_interval(self, _now) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _remove_all_listeners(self) -> None:
        for remove in self._remove_listeners:
            remove()
        self._remove_listeners.clear()

    async def _async_update_data(self) -> EnergyManagerDecision:
        """Fetch data from HA states."""

        decision = self._calculate()
        await self.async_apply_decision(decision)
        await async_update_issues(self.hass, self)
        return decision

    def _state_float(self, key: str) -> float | None:
        entity_id = self.entity_map.get(key)
        if not entity_id:
            return None
        return self._entity_float(entity_id)

    def _entity_float(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _entity_state_string(self, entity_id: str | None) -> str | None:
        state = self.hass.states.get(entity_id) if entity_id else None
        return str(state.state) if state is not None else None

    def _state_datetime(self, key: str) -> datetime | None:
        entity_id = self.entity_map.get(key)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in UNAVAILABLE:
            return None
        return dt_util.parse_datetime(state.state)

    def _entity_datetime(self, entity_id: str | None) -> datetime | None:
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in UNAVAILABLE:
            return None
        return dt_util.parse_datetime(state.state)

    def _resolve_soc(self, now: datetime, settings: EnergyManagerSettings) -> tuple[float | None, str | None, str, float | None]:
        primary_entity = self.entity_map.get("primary_soc_entity") or self.entity_map.get("battery_soc")
        fallback_entity = self.entity_map.get("fallback_soc_entity")
        fallback_timestamp_entity = self.entity_map.get("fallback_soc_timestamp_entity")
        raw_soc = self._entity_state_string(primary_entity)
        live_soc = self._entity_float(primary_entity) if primary_entity else None
        if live_soc is not None:
            return live_soc, raw_soc, "live", 0.0

        fallback_soc = self._entity_float(fallback_entity) if fallback_entity else None
        fallback_ts = self._entity_datetime(fallback_timestamp_entity)
        if fallback_soc is not None and fallback_ts is not None:
            if fallback_ts.tzinfo is None:
                fallback_ts = dt_util.as_local(fallback_ts)
        resolved_soc, soc_source, soc_age_minutes = resolve_soc_value(
            raw_soc,
            fallback_soc,
            fallback_ts,
            now,
            settings.max_fallback_soc_age_minutes,
        )
        return resolved_soc, raw_soc, soc_source, soc_age_minutes


    def _any_owned_heat_on(self) -> bool:
        for load in self.heat_loads:
            ownership = str(load.get("ownership_entity", ""))
            state = self.hass.states.get(ownership)
            if state and state.state == "on":
                return True
        return False

    def _heat_load_states(self) -> list[HeatLoadState]:
        states: list[HeatLoadState] = []
        now = dt_util.now()
        for load in self.heat_loads:
            climate = str(load.get("climate_entity", ""))
            name = str(load.get("name", climate or "unknown"))
            ownership = str(load.get("ownership_entity", ""))
            climate_state = self.hass.states.get(climate) if climate else None
            ownership_state = self.hass.states.get(ownership) if ownership else None
            power_w = None
            if power_entity := str(load.get("optional_power_sensor", "")):
                power_state = self.hass.states.get(power_entity)
                if power_state is not None and power_state.state not in UNAVAILABLE:
                    try:
                        power_w = float(power_state.state)
                    except (TypeError, ValueError):
                        power_w = None
            current_temp = None
            target_temp = None
            fan_mode = None
            supported_fan_modes: tuple[str, ...] = ()
            if climate_state is not None:
                raw_current = climate_state.attributes.get("current_temperature")
                raw_target = climate_state.attributes.get("temperature", load.get("target_temp"))
                fan_mode = climate_state.attributes.get("fan_mode")
                raw_fan_modes = climate_state.attributes.get("fan_modes") or ()
                if isinstance(raw_fan_modes, (list, tuple)):
                    supported_fan_modes = tuple(str(mode) for mode in raw_fan_modes)
                try:
                    current_temp = float(raw_current) if raw_current is not None else None
                    target_temp = float(raw_target) if raw_target is not None else None
                except (TypeError, ValueError):
                    current_temp = None
                    target_temp = None
            configured_target = load.get("target_temp")
            if ownership_state is not None and ownership_state.state == "on":
                manually_off = climate_state is not None and climate_state.state == "off"
                target_lowered = (
                    target_temp is not None
                    and configured_target is not None
                    and target_temp < float(configured_target) - 0.1
                )
                if manually_off or target_lowered:
                    self._block_heat_load(name, "manual off" if manually_off else "target lowered")
                    self.hass.async_create_task(self._clear_heat_ownership(load, f"manual override: {name}"))
            blocked_until = self._heat_blocked_until.get(name)
            if blocked_until is not None and blocked_until <= now:
                self._heat_blocked_until.pop(name, None)
                blocked_until = None
            states.append(
                HeatLoadState(
                    name=name,
                    priority=int(load.get("priority", 999)),
                    slug=str(load.get("slug") or infer_load_slug(load)),
                    climate_entity=climate or None,
                    ownership_entity=ownership or None,
                    power_sensor=str(load.get("optional_power_sensor", "")) or None,
                    is_on=climate_state is not None and climate_state.state not in {"off", *UNAVAILABLE},
                    solar_owned=ownership_state is not None and ownership_state.state == "on",
                    current_temp=current_temp,
                    target_temp=target_temp,
                    estimated_load_w=float(load.get("estimated_load_w", 0.0) or 0.0),
                    blocked_until=blocked_until,
                    load_type=str(load.get("type", "other")),
                    hvac_mode=climate_state.state if climate_state is not None else None,
                    hvac_action=str(climate_state.attributes.get("hvac_action")) if climate_state is not None and climate_state.attributes.get("hvac_action") is not None else None,
                    fan_mode=str(fan_mode) if fan_mode is not None else None,
                    supported_fan_modes=supported_fan_modes,
                    power_w=power_w,
                    active_power_threshold_w=float(load.get("active_power_threshold_w", 800.0) or 800.0),
                    idle_power_threshold_w=float(load.get("idle_power_threshold_w", 150.0) or 150.0),
                    taper_power_threshold_w=float(load.get("taper_power_threshold_w", 400.0) or 400.0),
                    enabled=bool(load.get("enabled", True)),
                    supports_heating=bool(load.get("supports_heating", True)),
                    supports_cooling=bool(load.get("supports_cooling", False)),
                    last_added_at=self._thermal_last_added_at.get(name),
                    last_shed_at=self._thermal_last_shed_at.get(name),
                    last_rotated_at=self._thermal_last_rotated_at.get(name),
                    last_action=(self._thermal_last_action.get(name) or (None, None))[0],
                    last_action_reason=(self._thermal_last_action.get(name) or (None, None))[1],
                )
            )
        return states

    def _block_heat_load(self, name: str, reason: str) -> None:
        self._heat_blocked_until[name] = dt_util.now() + timedelta(minutes=self.settings.manual_override_cooldown_min)
        self.last_control_action = f"blocked heat load {name}: {reason}"

    def _calculate(self) -> EnergyManagerDecision:
        now = dt_util.now()
        essential_power = self._state_float("essential_power") or 0.0
        ev_power = self._state_float("ev_power")
        settings = self.settings
        resolved_soc, raw_soc, soc_source, soc_age_minutes = self._resolve_soc(now, settings)
        if ev_power is not None and ev_power < settings.ev_stopped_load_threshold_w:
            self.ev_low_since = self.ev_low_since or now
        else:
            self.ev_low_since = None
        inputs = EnergyManagerInputs(
            now=now,
            battery_soc=resolved_soc,
            raw_soc=raw_soc,
            soc_source=soc_source,
            soc_age_minutes=soc_age_minutes,
            battery_power_w=self._state_float("battery_power") or 0.0,
            essential_power_w=essential_power,
            previous_essential_power_w=self.previous_essential_power_w,
            forecast_today_kwh=self._state_float("forecast_today"),
            forecast_remaining_today_kwh=self._state_float("forecast_remaining_today"),
            forecast_tomorrow_kwh=self._state_float("forecast_tomorrow"),
            pv_power_now_w=self._state_float("pv_power_now"),
            pv_power_in_30_minutes_w=self._state_float("pv_power_in_30_minutes"),
            pv_power_in_1_hour_w=self._state_float("pv_power_in_1_hour"),
            outdoor_temperature=self._state_float("outdoor_temperature"),
            indoor_average_temperature=self._state_float("indoor_average_temperature"),
            any_solar_owned_heat_load_on=self._any_owned_heat_on(),
            heat_loads=self._heat_load_states(),
            heat_available=bool(self.heat_loads),
            ev_latch_on=self.ev_latch_on,
            ev_hold_until=self.ev_hold_until,
            ev_power_w=ev_power,
            ev_low_since=self.ev_low_since,
            porsche_soc=self._state_float("porsche_soc"),
            porsche_charging_status=self._state_string("porsche_charging_status"),
            porsche_charging_ends=self._state_datetime("porsche_charging_ends"),
        )
        decision = decide(inputs, settings)
        self._update_load_diagnostics(inputs, settings, decision)
        self._append_proposed_action(decision)
        self.previous_essential_power_w = essential_power
        self.ev_latch_on = decision.ev_latch_active
        self.ev_hold_until = decision.ev_hold_until if decision.ev_latch_active else None
        return decision

    def _update_load_diagnostics(
        self,
        inputs: EnergyManagerInputs,
        settings: EnergyManagerSettings,
        decision: EnergyManagerDecision,
    ) -> None:
        self.load_diagnostics = thermal_load_diagnostics(inputs, settings, decision)

    def _append_proposed_action(self, decision: EnergyManagerDecision) -> None:
        action = decision.expected_action
        subsystem = "thermal" if action.startswith("thermal_") else "ev" if action.startswith("ev_") else "grid" if action.startswith("grid_") else "system"
        self.recent_proposed_actions.append(
            {
                "timestamp": decision.now.isoformat(),
                "subsystem": subsystem,
                "proposed_action": action,
                "would_actuate": self._would_actuate(subsystem),
                "actuation_mode": self.settings.thermal_actuation_mode if subsystem == "thermal" else "direct" if subsystem == "ev" else "advisory",
                "target_entity": decision.thermal_load_to_add or decision.thermal_load_to_shed,
                "reason": decision.thermal_action_reason if subsystem == "thermal" else decision.ev_decision_reason if subsystem == "ev" else decision.reason,
                "blocked_reason": self._blocked_reason(subsystem),
                "control_enabled": self.settings.thermal_control_enabled if subsystem == "thermal" else self.settings.ev_control_enabled if subsystem == "ev" else self.settings.enabled,
            }
        )

    def _would_actuate(self, subsystem: str) -> bool:
        settings = self.settings
        if subsystem == "thermal":
            return settings.thermal_control_enabled and settings.thermal_actuation_mode != "advisory"
        if subsystem == "ev":
            return settings.ev_control_enabled and settings.ev_grid_bypass_enabled
        return False

    def _blocked_reason(self, subsystem: str) -> str | None:
        settings = self.settings
        if subsystem == "thermal":
            if not settings.thermal_control_enabled:
                return "thermal control disabled"
            if settings.thermal_actuation_mode == "advisory":
                return "advisory mode"
            if settings.thermal_actuation_mode == "direct" and not settings.direct_climate_control_enabled:
                return "direct climate control disabled"
        if subsystem == "ev" and not settings.ev_control_enabled:
            return "EV control disabled"
        return None

    def _state_string(self, key: str) -> str | None:
        entity_id = self.entity_map.get(key)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in UNAVAILABLE:
            return None
        return str(state.state)

    async def async_set_option(self, key: str, value: object) -> None:
        """Update one config option."""

        options = {**self.entry.options, key: value}
        if key == "heat_control_enabled":
            options["thermal_control_enabled"] = bool(value)
        elif key == "thermal_control_enabled":
            options["heat_control_enabled"] = bool(value)
        elif key == "heat_mode":
            if value == "auto_scripts":
                options["thermal_actuation_mode"] = "scripts"
            elif value == "auto_direct":
                options["thermal_actuation_mode"] = "direct"
            elif value == "advisory":
                options["thermal_actuation_mode"] = "advisory"
        elif key == "thermal_actuation_mode":
            if value == "scripts":
                options["heat_mode"] = "auto_scripts"
            elif value == "direct":
                options["heat_mode"] = "auto_direct"
            elif value == "advisory":
                options["heat_mode"] = "advisory"
        self.hass.config_entries.async_update_entry(
            self.entry,
            options=options,
        )
        await self.async_request_refresh()

    async def async_clear_ev_latch(self) -> None:
        """Clear the in-memory EV latch."""

        self.ev_latch_on = False
        self.ev_hold_until = None
        self.last_control_action = "EV latch cleared manually"
        await self.async_request_refresh()

    async def async_apply_decision(self, decision: EnergyManagerDecision | None = None) -> None:
        """Apply safe, gated actuator writes."""

        decision = decision or self.data
        if decision is None or decision.control_blocked:
            return
        if dt_util.utcnow() - self.started_at < timedelta(seconds=60):
            return
        settings = self.settings
        if settings.deye_control_enabled:
            await self._apply_deye_capacity_targets(decision)
        if settings.ev_control_enabled:
            await self._apply_ev_mode(decision.ev_grid_bypass_required)
        if settings.grid_charge_control_enabled:
            await self._apply_grid_charge(decision)
        if settings.heat_control_enabled or settings.thermal_control_enabled:
            await self._apply_heat(decision)

    async def _call_number_set(self, entity_id: str, value: float) -> None:
        if self._last_written.get(entity_id) == value:
            return
        state = self.hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE:
            return
        await self.hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id, "value": value},
            blocking=False,
        )
        self._last_written[entity_id] = value

    async def _call_select_option(self, entity_id: str, option: str) -> None:
        if self._last_written.get(entity_id) == option:
            return
        state = self.hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE or state.state == option:
            return
        await self.hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_id, "option": option},
            blocking=False,
        )
        self._last_written[entity_id] = option

    async def _call_switch(self, entity_id: str, on: bool) -> None:
        if self._last_written.get(entity_id) == on:
            return
        state = self.hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE or state.state == ("on" if on else "off"):
            return
        await self.hass.services.async_call(
            "switch",
            "turn_on" if on else "turn_off",
            {"entity_id": entity_id},
            blocking=False,
        )
        self._last_written[entity_id] = on

    async def _apply_deye_capacity_targets(self, decision: EnergyManagerDecision) -> None:
        tier = forecast_tier(decision.forecast_tomorrow_kwh, self.settings)
        targets = slot_capacity_targets(tier)
        slot_to_entity = {
            "Prog1": PROG_CAPACITY_ENTITIES[0],
            "Prog2": PROG_CAPACITY_ENTITIES[1],
            "Prog3": PROG_CAPACITY_ENTITIES[2],
            "Prog4": PROG_CAPACITY_ENTITIES[3],
            "Prog5": PROG_CAPACITY_ENTITIES[4],
            "Prog6": PROG_CAPACITY_ENTITIES[5],
        }
        for slot, value in targets.items():
            await self._call_number_set(slot_to_entity[slot], value)
        self.last_control_action = "updated Deye reserve floors"

    async def _apply_ev_mode(self, required: bool) -> None:
        for entity_id in PROG_POWER_ENTITIES[:4]:
            await self._call_number_set(entity_id, 0.0 if required else self.settings.ev_restore_program_power_w)
        self.last_control_action = "EV grid bypass start: Deye programme powers -> 0" if required else "EV grid bypass restore: Deye programme powers restored"

    async def _apply_grid_charge(self, decision: EnergyManagerDecision) -> None:
        switch_id = self.entity_map.get("grid_charge_switch", "switch.deye_grid_charge_enabled")
        await self._call_switch(switch_id, decision.grid_charge_required)
        if decision.grid_charge_required:
            for entity_id in PROG_CHARGE_SELECT_ENTITIES[:2]:
                await self._call_select_option(entity_id, CHARGE_OPTION_ALLOW_GRID)
            for entity_id in PROG_CAPACITY_ENTITIES[:2]:
                await self._call_number_set(entity_id, decision.grid_charge_target_soc)
            for entity_id in PROG_POWER_ENTITIES[:2]:
                await self._call_number_set(entity_id, 12000.0)
        else:
            for entity_id in PROG_CHARGE_SELECT_ENTITIES[:2]:
                await self._call_select_option(entity_id, CHARGE_OPTION_NO_GRID)
        self.last_control_action = "updated grid charge state"

    async def _apply_heat(self, decision: EnergyManagerDecision) -> None:
        mode = self.settings.thermal_actuation_mode
        if mode == "advisory":
            self.last_control_action = "thermal advisory only: no action"
            return
        if decision.thermal_should_emergency_shed:
            if mode == "direct" and self.settings.direct_climate_control_enabled:
                await self._direct_shed_all_heat_loads("emergency battery discharge")
            elif mode == "scripts":
                await self.hass.services.async_call("script", "deye_energy_manager_emergency_shed_all_heat_loads", {}, blocking=False)
                self.last_control_action = "requested thermal emergency shed all script"
            return
        if mode == "direct":
            if not self.settings.direct_climate_control_enabled:
                self.last_control_action = "thermal direct mode blocked: direct climate control disabled"
                return
            if decision.bedroom_heat_taper_recommended:
                await self._direct_taper_bedroom_heat()
            if decision.overnight_protection_required:
                await self._direct_shed_one_heat_load(nonessential_only=True)
            elif decision.thermal_should_shed:
                await self._direct_shed_one_heat_load(decision.thermal_load_to_normalise)
            elif decision.thermal_rotation_recommended and self.settings.thermal_rotation_enabled:
                await self._direct_rotate_heat_load(decision)
            elif decision.thermal_allowed or (decision.pv_load_test_recommended and self.settings.pv_load_test_control_enabled):
                await self._direct_add_one_heat_load(decision.thermal_load_to_add)
            return
        if mode != "scripts":
            return
        if decision.bedroom_heat_taper_recommended:
            await self.hass.services.async_call("script", "deye_energy_manager_taper_bedroom_heat", {}, blocking=False)
            self.last_control_action = "requested thermal bedroom taper script"
        if decision.overnight_protection_required:
            await self.hass.services.async_call("script", "deye_energy_manager_shed_one_heat_load", {}, blocking=False)
            self.last_control_action = "requested overnight protection heat shed script"
            return
        if decision.thermal_should_shed:
            await self.hass.services.async_call("script", "deye_energy_manager_shed_one_heat_load", {}, blocking=False)
            self.last_control_action = "requested thermal shed script"
        elif decision.thermal_rotation_recommended and self.settings.thermal_rotation_enabled:
            await self.hass.services.async_call("script", "deye_energy_manager_shed_one_heat_load", {}, blocking=False)
            await self.hass.services.async_call("script", "deye_energy_manager_add_one_heat_load", {}, blocking=False)
            self.last_control_action = "requested thermal rotation scripts"
        elif decision.thermal_allowed or (decision.pv_load_test_recommended and self.settings.pv_load_test_control_enabled):
            await self.hass.services.async_call("script", "deye_energy_manager_add_one_heat_load", {}, blocking=False)
            self.last_control_action = "requested PV load test script" if decision.pv_load_test_recommended else "requested thermal add script"

    def _thermal_mode(self) -> str:
        return "heating" if self.settings.thermal_mode == "auto" else self.settings.thermal_mode

    def _soak_target(self) -> float:
        return self.settings.cool_soak_target_temp if self._thermal_mode() == "cooling" else self.settings.heat_soak_target_temp

    def _normal_target(self) -> float:
        return self.settings.cool_normal_target_temp if self._thermal_mode() == "cooling" else self.settings.heat_normal_target_temp

    def _hvac_mode(self) -> str:
        return "cool" if self._thermal_mode() == "cooling" else "heat"

    def _soak_fan_mode(self) -> str:
        return self.settings.cool_soak_fan_mode if self._thermal_mode() == "cooling" else self.settings.heat_soak_fan_mode

    def _normal_fan_mode(self) -> str:
        return self.settings.cool_normal_fan_mode if self._thermal_mode() == "cooling" else self.settings.heat_normal_fan_mode

    async def _call_climate_fan_mode(self, entity_id: str, fan_mode: str) -> str | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE:
            return "climate unavailable"
        supported = state.attributes.get("fan_modes") or ()
        if not isinstance(supported, (list, tuple)) or not supported:
            return "climate does not expose fan_modes"
        if fan_mode not in supported:
            return f"fan mode {fan_mode} not in supported fan_modes"
        if state.attributes.get("fan_mode") == fan_mode or self._last_written.get(f"{entity_id}:fan_mode") == fan_mode:
            return None
        await self.hass.services.async_call(
            "climate",
            "set_fan_mode",
            {"entity_id": entity_id, "fan_mode": fan_mode},
            blocking=False,
        )
        self._last_written[f"{entity_id}:fan_mode"] = fan_mode
        return None

    async def _direct_add_one_heat_load(self, preferred_name: str | None = None) -> None:
        for load in sorted(self.heat_loads, key=lambda item: int(item.get("priority", 999))):
            if preferred_name and str(load.get("name", "")) != preferred_name:
                continue
            if not bool(load.get("enabled", True)):
                continue
            if self._thermal_mode() == "cooling" and not bool(load.get("supports_cooling", False)):
                continue
            if self._thermal_mode() == "heating" and not bool(load.get("supports_heating", True)):
                continue
            climate = str(load.get("climate_entity", ""))
            ownership = str(load.get("ownership_entity", ""))
            if not climate or self.hass.states.get(climate) is None:
                continue
            name = str(load.get("name", climate))
            if (blocked_until := self._heat_blocked_until.get(name)) and blocked_until > dt_util.now():
                continue
            if ownership and (state := self.hass.states.get(ownership)) and state.state == "on":
                continue
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": climate, "hvac_mode": self._hvac_mode()},
                blocking=False,
            )
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": climate, "temperature": self._soak_target()},
                blocking=False,
            )
            fan_blocked_reason = await self._call_climate_fan_mode(climate, self._soak_fan_mode())
            if ownership and self.hass.states.get(ownership):
                await self.hass.services.async_call("input_boolean", "turn_on", {"entity_id": ownership}, blocking=False)
            now = dt_util.now()
            self._thermal_last_added_at[name] = now
            fan_detail = f", fan {self._soak_fan_mode()}" if fan_blocked_reason is None else f", fan skipped: {fan_blocked_reason}"
            self._thermal_last_action[name] = ("add", f"direct thermal add {self._hvac_mode()} {self._soak_target():.1f}{fan_detail}")
            self.last_control_action = f"direct added thermal load {load.get('name', climate)} at {self._soak_target():.1f}C{fan_detail}"
            return

    async def _direct_shed_one_heat_load(self, preferred_name: str | None = None, nonessential_only: bool = False) -> None:
        owned_loads = []
        for load in self.heat_loads:
            if preferred_name and str(load.get("name", "")) != preferred_name:
                continue
            if nonessential_only and "bedroom" in f"{load.get('name', '')} {load.get('type', '')}".lower():
                continue
            ownership = str(load.get("ownership_entity", ""))
            state = self.hass.states.get(ownership) if ownership else None
            if state and state.state == "on":
                owned_loads.append(load)
            elif preferred_name and self.settings.shed_unowned_managed_loads_on_battery_discharge:
                owned_loads.append(load)
        for load in sorted(owned_loads, key=lambda item: int(item.get("priority", 999)), reverse=True):
            climate = str(load.get("climate_entity", ""))
            ownership = str(load.get("ownership_entity", ""))
            if climate and self.hass.states.get(climate):
                await self._normalise_or_turn_off_load(load)
            if ownership and self.hass.states.get(ownership):
                await self.hass.services.async_call("input_boolean", "turn_off", {"entity_id": ownership}, blocking=False)
            name = str(load.get("name", climate))
            self._thermal_last_shed_at[name] = dt_util.now()
            action_reason = "normalising unowned managed load due to battery discharge" if not (ownership and self.hass.states.get(ownership) and self.hass.states.get(ownership).state == "on") else "direct thermal normalise/shed"
            self._thermal_last_action[name] = ("shed", action_reason)
            self.last_control_action = f"direct normalised thermal load {load.get('name', climate)}: {action_reason}"
            return

    async def _direct_rotate_heat_load(self, decision: EnergyManagerDecision) -> None:
        await self._direct_shed_one_heat_load(decision.thermal_load_to_shed)
        await self._direct_add_one_heat_load(decision.thermal_load_to_add)
        now = dt_util.now()
        if decision.thermal_load_to_shed:
            self._thermal_last_rotated_at[decision.thermal_load_to_shed] = now
        if decision.thermal_load_to_add:
            self._thermal_last_rotated_at[decision.thermal_load_to_add] = now
        self.last_control_action = f"direct rotated thermal load {decision.thermal_load_to_shed} -> {decision.thermal_load_to_add}"

    async def _clear_heat_ownership(self, load: dict[str, object], reason: str) -> None:
        ownership = str(load.get("ownership_entity", ""))
        if ownership and self.hass.states.get(ownership):
            await self.hass.services.async_call("input_boolean", "turn_off", {"entity_id": ownership}, blocking=False)
            self.last_control_action = reason

    async def _direct_shed_all_heat_loads(self, reason: str) -> None:
        for load in self.heat_loads:
            ownership = str(load.get("ownership_entity", ""))
            state = self.hass.states.get(ownership) if ownership else None
            if not state or state.state != "on":
                continue
            climate = str(load.get("climate_entity", ""))
            if climate and self.hass.states.get(climate):
                await self._normalise_or_turn_off_load(load)
            await self.hass.services.async_call("input_boolean", "turn_off", {"entity_id": ownership}, blocking=False)
            name = str(load.get("name", climate))
            self._thermal_last_shed_at[name] = dt_util.now()
            self._thermal_last_action[name] = ("emergency_shed", reason)
        self.last_control_action = f"direct emergency shed all heat loads: {reason}"

    async def _normalise_or_turn_off_load(self, load: dict[str, object]) -> None:
        climate = str(load.get("climate_entity", ""))
        is_underfloor = str(load.get("type", "")).lower() == "underfloor"
        if not self.settings.return_to_normal_on_shed_enabled or is_underfloor:
            await self.hass.services.async_call("climate", "turn_off", {"entity_id": climate}, blocking=False)
            return
        await self.hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": climate, "hvac_mode": self._hvac_mode()},
            blocking=False,
        )
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": climate, "temperature": self._normal_target()},
            blocking=False,
        )
        await self._call_climate_fan_mode(climate, self._normal_fan_mode())

    async def _direct_taper_bedroom_heat(self) -> None:
        for load in self.heat_loads:
            if "bedroom" not in f"{load.get('name', '')} {load.get('type', '')}".lower():
                continue
            ownership = str(load.get("ownership_entity", ""))
            state = self.hass.states.get(ownership) if ownership else None
            if not state or state.state != "on":
                continue
            climate = str(load.get("climate_entity", ""))
            if climate and self.hass.states.get(climate):
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": climate, "temperature": self.settings.overnight_bedroom_taper_target_temp},
                    blocking=False,
                )
                self.last_control_action = f"direct tapered bedroom heat {load.get('name', climate)}"
                return
