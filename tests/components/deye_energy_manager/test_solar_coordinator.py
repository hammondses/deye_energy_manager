"""Advisory adapter tests using actual parsing and planning, without HA writes."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.deye_energy_manager import solar_advisory_adapter as module
from custom_components.deye_energy_manager.const import DEFAULT_ENTITY_MAP
from custom_components.deye_energy_manager.decision import decide
from custom_components.deye_energy_manager.models import EnergyManagerInputs, EnergyManagerSettings


def setup_adapter():
    now = datetime(2026, 3, 20, 12, tzinfo=timezone.utc)
    rows = [
        {"period_start": (now + timedelta(minutes=30*i)).isoformat(),
         "pv_estimate10": 8, "pv_estimate": 9, "pv_estimate90": 10}
        for i in range(6)
    ]
    states = {}

    def state(key, value, unit=None, **attributes):
        if unit is not None:
            attributes["unit_of_measurement"] = unit
        states[DEFAULT_ENTITY_MAP[key]] = SimpleNamespace(
            state=str(value), attributes=attributes, last_reported=now, last_updated=now,
        )

    state("sun", "above_horizon", next_setting=(now + timedelta(hours=3)).isoformat())
    state("forecast_today", 27, detailedForecast=rows)
    state("forecast_updated_at", now.isoformat())
    state("battery_soc", 50, "%")
    state("inverter_pv_power", 10, "kW")
    state("essential_power", 3000, "W")
    state("ev_power", 2, "kW")
    state("ev_voltage", 230, "V")
    state("battery_voltage", 54, "V")
    state("battery_charge_limit_current", 250, "A")
    coordinator = SimpleNamespace()
    coordinator.entry = SimpleNamespace(
        data={}, options={
            "daytime_plan_enabled": True,
            "solar_plan_charge_acceptance_curve": "[[0,13.5],[0.9,6]]",
        },
    )
    coordinator.hass = SimpleNamespace(states=states, config=SimpleNamespace(latitude=0, longitude=0))
    coordinator._daytime_solar_advisory = lambda inputs, settings, decision: module.build_daytime_advisory(
        inputs, settings, decision,
        options=coordinator.entry.options, entity_map=DEFAULT_ENTITY_MAP, states=states,
        latitude=coordinator.hass.config.latitude, longitude=coordinator.hass.config.longitude,
    )
    settings = EnergyManagerSettings(
        battery_capacity_kwh=32, ev_solar_charging_enabled=True,
        forecast_safety_buffer_kwh=0, house_load_forecast_buffer_kwh=0,
    )
    inputs = EnergyManagerInputs(
        now=now, battery_soc=50, base_load_estimate_w=1000,
        essential_power_w=3000, ev_power_w=2000, ev_charge_requested=True,
        ev_connector_status="Charging", porsche_soc=70, forecast_tomorrow_kwh=40,
    )
    return coordinator, inputs, settings, decide(inputs, settings), state


def test_adapter_produces_advisory_without_mutating_existing_decision(monkeypatch):
    coordinator, inputs, settings, decision, _ = setup_adapter()
    before = asdict(decision)
    captured = []
    original = module.recommend_solar_action

    def capture(value):
        captured.append(value)
        return original(value)

    monkeypatch.setattr(module, "recommend_solar_action", capture)
    plan = coordinator._daytime_solar_advisory(inputs, settings, decision)
    assert plan is not None and plan.valid, plan.reason
    assert plan.target_reachable
    assert plan.deadline == inputs.now + timedelta(hours=3)
    assert captured[0].current_non_ev_house_kw == 1
    assert captured[0].non_ev_base_house_kw == 1
    assert captured[0].live_pv_dc_kw == 10
    assert captured[0].physical_dc_upper_kw is not None
    assert plan.clipping_plan_available
    assert abs(plan.clipping_captured_kwh + plan.clipping_estimate_kwh - plan.clipping_potential_kwh) < 1e-9
    assert plan.physical_scenario_soc_trajectory[0] == 50
    assert asdict(decision) == before


def test_adapter_reports_missing_curve_and_disabled_state():
    coordinator, inputs, settings, decision, _ = setup_adapter()
    coordinator.entry.options["solar_plan_charge_acceptance_curve"] = ""
    plan = coordinator._daytime_solar_advisory(inputs, settings, decision)
    assert not plan.valid and "curve not configured" in plan.reason
    coordinator.entry.options["daytime_plan_enabled"] = False
    assert coordinator._daytime_solar_advisory(inputs, settings, decision) is None


def test_supplier_age_blocks_plan_even_when_sensor_was_just_refreshed():
    coordinator, inputs, settings, decision, state = setup_adapter()
    state("forecast_updated_at", (inputs.now - timedelta(hours=3)).isoformat())
    plan = coordinator._daytime_solar_advisory(inputs, settings, decision)
    assert not plan.valid and "stale" in plan.reason


def test_invalid_units_or_stale_live_pv_block_plan():
    coordinator, inputs, settings, decision, state = setup_adapter()
    state("inverter_pv_power", 10, "MW")
    plan = coordinator._daytime_solar_advisory(inputs, settings, decision)
    assert not plan.valid and "unit" in plan.reason
    state("inverter_pv_power", 10, "kW")
    coordinator.hass.states[DEFAULT_ENTITY_MAP["inverter_pv_power"]].last_reported -= timedelta(minutes=3)
    plan = coordinator._daytime_solar_advisory(inputs, settings, decision)
    assert not plan.valid and "stale" in plan.reason


def test_manual_override_preserves_battery_advisory_but_removes_solar_ev_allocation(monkeypatch):
    coordinator, inputs, settings, decision, _ = setup_adapter()
    inputs.ev_manual_charging_override = True
    captured = []
    original = module.recommend_solar_action

    def capture(value):
        captured.append(value)
        return original(value)

    monkeypatch.setattr(module, "recommend_solar_action", capture)
    plan = coordinator._daytime_solar_advisory(inputs, settings, decision)
    assert plan.valid, plan.reason
    assert plan.recommended_ev_amps == 0
    assert captured[0].current_non_ev_house_kw == 3


def test_finishing_connector_can_receive_restart_advice_but_available_cannot():
    coordinator, inputs, settings, decision, _ = setup_adapter()
    inputs.ev_connector_status = "Finishing"

    finishing_plan = coordinator._daytime_solar_advisory(inputs, settings, decision)

    assert finishing_plan is not None and finishing_plan.valid, finishing_plan.reason
    assert finishing_plan.recommended_ev_amps >= 6

    inputs.ev_connector_status = "Available"
    available_plan = coordinator._daytime_solar_advisory(inputs, settings, decision)

    assert available_plan is not None and available_plan.valid, available_plan.reason
    assert available_plan.recommended_ev_amps == 0


def test_invalid_curve_does_not_break_the_existing_manager_decision():
    coordinator, inputs, settings, decision, _ = setup_adapter()
    coordinator.entry.options["solar_plan_charge_acceptance_curve"] = "{broken json"
    before = asdict(decision)
    plan = coordinator._daytime_solar_advisory(inputs, settings, decision)
    assert not plan.valid
    assert asdict(decision) == before


def test_stopped_charger_voltage_uses_fresh_supply_and_rejects_stale_supply(monkeypatch):
    coordinator, inputs, settings, decision, state = setup_adapter()
    inputs.ev_connector_status = "Finishing"
    inputs.ev_charge_requested = False
    coordinator.hass.states[DEFAULT_ENTITY_MAP["ev_voltage"]].last_reported -= timedelta(hours=2)
    state("grid_voltage", 239, "V")
    captured = []
    original = module.recommend_solar_action

    def capture(value):
        captured.append(value)
        return original(value)

    monkeypatch.setattr(module, "recommend_solar_action", capture)
    plan = coordinator._daytime_solar_advisory(inputs, settings, decision)
    assert plan.valid and plan.recommended_ev_amps >= 6
    assert captured[0].voltage_v == 239
    coordinator.hass.states[DEFAULT_ENTITY_MAP["grid_voltage"]].last_reported -= timedelta(minutes=3)
    plan = coordinator._daytime_solar_advisory(inputs, settings, decision)
    assert not plan.valid and "grid_voltage stale" in plan.reason
