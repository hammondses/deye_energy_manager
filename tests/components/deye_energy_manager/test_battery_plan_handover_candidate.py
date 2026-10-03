"""Offline Jinja checks for the review-only HA battery handover candidate."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from jinja2 import Environment


CANDIDATE = (
    Path(__file__).parents[3]
    / "docs"
    / "automation-candidates"
    / "battery-plan-handover.json"
)
NOW = datetime.fromisoformat("2026-10-03T12:00:00+13:00")


def _environment(states: dict[str, str]) -> Environment:
    env = Environment()
    env.globals.update(
        states=lambda entity_id: states.get(entity_id, "unknown"),
        is_state=lambda entity_id, expected: states.get(entity_id, "unknown")
        == expected,
        is_number=lambda value: _is_number(value),
        as_timestamp=lambda value, default=0: _timestamp(value, default),
        now=lambda: NOW,
    )
    env.filters["bool"] = lambda value, default=False: (
        value if isinstance(value, bool) else str(value).lower() in {"true", "on", "yes", "1"}
    )
    return env


def _is_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _timestamp(value: object, default: float = 0) -> float:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return float(default)


def _as_native(value: str) -> object:
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return float(value)
    except ValueError:
        return value


def _base_states(**overrides: str) -> dict[str, str]:
    states = {
        "input_boolean.deye_battery_plan_handover_enabled": "on",
        "sensor.garage_deye_energy_manager_solar_plan_status": "advisory",
        "sensor.garage_deye_energy_manager_solar_plan_generated_at": "2026-10-03T12:00:00+13:00",
        "sensor.garage_deye_energy_manager_solar_plan_recommended_battery_dc_power": "5.0",
        "number.garage_deye_energy_manager_solar_plan_inverter_efficiency": "0.96",
        "number.garage_deye_energy_manager_solar_plan_battery_max_charge_dc_kw": "13.5",
        "sensor.deye_battery_charge_limit_current": "200",
        "sensor.deye_battery_voltage": "54",
        "sensor.deye_pv_power": "12000",
        "sensor.deye_battery_power": "-5000",
        "sensor.deye_inverter_power": "8000",
        "sensor.deye_grid_ct_power": "-2000",
        "sensor.deye_battery_max_charge_current": "100",
        "number.deye_battery_max_charge_current": "100",
        "number.deye_max_sell_power": "10000",
        "sensor.deye_rated_power": "12000",
        "sensor.deye_battery_soc": "70",
        "sensor.garage_deye_energy_manager_discretionary_energy_budget": "4",
        "sensor.garage_deye_energy_manager_active_reserve_target_soc": "12",
        "sensor.garage_deye_energy_manager_projected_16_00_soc": "95",
        "number.garage_deye_energy_manager_daily_battery_target_soc": "100",
        "input_number.deye_export_hold_minimum_soc": "25",
        "sensor.deye_shadow_recommended_charge_power": "0",
    }
    states.update(overrides)
    return states


def _evaluate(states: dict[str, str]) -> dict[str, object]:
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    actions = config["actions"]
    env = _environment(states)
    context: dict[str, object] = {}
    for index in range(8):
        for key, template in actions[index].get("variables", {}).items():
            rendered = env.from_string(template).render(**context)
            context[key] = _as_native(rendered)
    return context


def test_disabled_and_invalid_plan_keep_the_legacy_target_exactly() -> None:
    states = _base_states()
    disabled = _evaluate({**states, "input_boolean.deye_battery_plan_handover_enabled": "off"})
    invalid = _evaluate({**states, "sensor.garage_deye_energy_manager_solar_plan_status": "unavailable"})
    assert disabled["manager_plan_usable"] is False
    assert invalid["manager_plan_usable"] is False
    assert disabled["scheduled_target_inverter_w"] == disabled["legacy_scheduled_target_inverter_w"]
    assert invalid["scheduled_target_inverter_w"] == invalid["legacy_scheduled_target_inverter_w"]
    assert disabled["legacy_scheduled_target_inverter_w"] == 12000
    # Original current-gate result: (5 kW DC measured + 8 kW AC - 12 kW target) / 54 V.
    assert disabled["desired_limit_a"] == 19
    assert invalid["desired_limit_a"] == disabled["desired_limit_a"]
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    choose = next(action for action in config["actions"] if action.get("choose"))
    legacy_probe = choose["choose"][0]["sequence"][0]["choose"][1]["sequence"][0]["data"]["value"]
    rendered_probe = _environment(states).from_string(legacy_probe).render(
        manager_plan_usable=False,
        manager_probe_limit_a=0,
        current_limit_a=100,
        bms_charge_limit_a=200,
    )
    assert _as_native(rendered_probe) == 101


def test_stale_plan_falls_back_without_efficiency_adjusting_legacy() -> None:
    states = _base_states(
        **{"sensor.garage_deye_energy_manager_solar_plan_generated_at": "2026-10-03T11:58:00+13:00"}
    )
    context = _evaluate(states)
    assert context["manager_plan_usable"] is False
    assert context["scheduled_target_inverter_w"] == context["legacy_scheduled_target_inverter_w"]


def test_gateoff_with_zero_efficiency_and_nonfinite_plan_uses_legacy_without_new_division() -> None:
    states = _base_states(
        **{
            "input_boolean.deye_battery_plan_handover_enabled": "off",
            "number.garage_deye_energy_manager_solar_plan_inverter_efficiency": "0",
            "number.garage_deye_energy_manager_solar_plan_battery_max_charge_dc_kw": "inf",
            "sensor.garage_deye_energy_manager_solar_plan_recommended_battery_dc_power": "nan",
            "sensor.deye_battery_charge_limit_current": "inf",
            "sensor.deye_battery_voltage": "not-a-number",
        }
    )
    context = _evaluate(states)
    assert context["manager_plan_usable"] is False
    assert context["scheduled_target_inverter_w"] == context["legacy_scheduled_target_inverter_w"]
    assert context["manager_live_current_ceiling_a"] == 0
    assert context["manager_desired_limit_a"] == 0
    assert context["manager_probe_limit_a"] == 0


def test_unusable_plan_derived_calculations_are_safe_when_live_voltage_is_zero() -> None:
    """The old path already divides by voltage; new advisory math must add no such failure."""
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    actions = config["actions"]
    states = _base_states(
        **{
            "input_boolean.deye_battery_plan_handover_enabled": "off",
            "number.garage_deye_energy_manager_solar_plan_inverter_efficiency": "0",
            "sensor.deye_battery_voltage": "0",
        }
    )
    env = _environment(states)
    context: dict[str, object] = {
        "manager_plan_usable": False,
        "battery_v": 0,
        "bms_charge_limit_a": 0,
        "current_limit_a": 99,
        "battery_charge_w": 1000,
        "inverter_w": 1000,
        "scheduled_target_inverter_w": 1000,
    }
    for index, key in ((3, "manager_live_current_ceiling_a"), (6, "manager_desired_limit_a"), (6, "manager_probe_limit_a")):
        template = actions[index]["variables"][key]
        assert _as_native(env.from_string(template).render(**context)) == 0


def test_dc_plan_converts_to_ac_and_feedback_converts_error_back_to_dc() -> None:
    context = _evaluate(_base_states())
    assert context["manager_plan_usable"] is True
    assert context["plan_battery_dc_w"] == 5000
    # (12 kW DC PV - 5 kW DC battery demand) * 0.96, above the 6 kW live house floor.
    assert context["manager_scheduled_target_inverter_w"] == 6720
    assert context["scheduled_target_inverter_w"] == 6720
    # 5 kW measured DC battery charge + 1.28 kW AC error / 0.96 / 54 V.
    assert context["manager_desired_limit_a"] == 117
    assert context["desired_limit_a"] == 117


def test_zero_bms_acceptance_caps_charge_but_has_no_soc_hard_stop() -> None:
    states = _base_states(**{"sensor.deye_battery_charge_limit_current": "0"})
    context = _evaluate(states)
    assert context["manager_plan_usable"] is True
    assert context["plan_battery_dc_w"] == 0
    assert context["manager_live_current_ceiling_a"] == 0
    assert context["manager_desired_limit_a"] == 0
    assert "sensor.deye_battery_soc" not in json.loads(CANDIDATE.read_text())["candidate_config"]["actions"][3]["variables"]["manager_plan_usable"]


def test_actual_ev_ramp_load_sets_live_house_floor() -> None:
    # More EV draw lowers observed export and increases inverter-minus-export house load.
    context = _evaluate(_base_states(**{"sensor.deye_grid_ct_power": "0"}))
    assert context["house_w"] == 8000
    assert context["manager_scheduled_target_inverter_w"] == 8000


def test_probe_can_reveal_hidden_pv_above_minimum_plan_but_stays_within_live_ceiling() -> None:
    # Plan requests zero; with export already at the limit, the existing +1 A probe may still run.
    states = _base_states(
        **{
            "sensor.garage_deye_energy_manager_solar_plan_recommended_battery_dc_power": "0",
            "sensor.deye_inverter_power": "11520",
            "sensor.deye_grid_ct_power": "-10000",
            "sensor.deye_battery_power": "-5346",
            "number.deye_battery_max_charge_current": "99",
            "sensor.deye_battery_charge_limit_current": "200",
        }
    )
    context = _evaluate(states)
    assert context["manager_plan_usable"] is True
    assert context["plan_battery_dc_w"] == 0
    assert context["manager_scheduled_target_inverter_w"] == 11520
    assert context["manager_live_current_ceiling_a"] == 200
    assert context["manager_probe_limit_a"] == 100

    # A narrower configured DC limit binds the probe even though the plan request is still zero.
    narrow = _evaluate(
        {
            **states,
            "number.garage_deye_energy_manager_solar_plan_battery_max_charge_dc_kw": "5.4",
        }
    )
    assert narrow["manager_live_current_ceiling_a"] == 100
    assert narrow["manager_probe_limit_a"] == 100


def test_late_day_rule_comes_from_manager_and_not_a_shadow_clipping_window() -> None:
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    triggers = {trigger.get("entity_id") for trigger in config["triggers"]}
    assert "sensor.garage_deye_energy_manager_solar_plan_charge_all_surplus" in triggers
    serialized = json.dumps(config["actions"])
    assert "sensor.deye_shadow_clipping" not in serialized
    assert "sensor.garage_deye_energy_manager_solar_plan_physical_clipping_window_end" not in serialized
