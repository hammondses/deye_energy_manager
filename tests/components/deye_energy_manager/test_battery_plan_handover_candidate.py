"""Offline Jinja checks for the review-only HA battery handover candidate."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment


CANDIDATE = (
    Path(__file__).parents[3]
    / "docs"
    / "automation-candidates"
    / "battery-plan-handover.json"
)
NOW = datetime.fromisoformat("2026-10-03T12:00:00+13:00")


def _environment(states: dict[str, str]) -> Environment:
    class States:
        number = SimpleNamespace(deye_battery_max_charge_current=SimpleNamespace(
            last_changed="2026-10-03T11:55:00+13:00"))
        def __getitem__(self, entity_id):
            return SimpleNamespace(state=states.get(entity_id, "unknown"), last_reported=NOW)
        def __call__(self, entity_id):
            return states.get(entity_id, "unknown")
    env = Environment()
    env.globals.update(
        states=States(),
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



def test_stale_plan_keeps_live_capture_without_legacy() -> None:
    states = _base_states(
        **{"sensor.garage_deye_energy_manager_solar_plan_generated_at": "2026-10-03T11:58:00+13:00"}
    )
    context = _evaluate(states)
    assert context["manager_plan_usable"] is False
    assert context["scheduled_target_inverter_w"] == 11520
    assert context["battery_feedback_mode"] == "live_capture_only"




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


def _damping_conditions(**overrides):
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    choices = config["actions"][8]["choose"][0]["sequence"][0]["choose"]
    context = _evaluate(_base_states())
    context.update(manager_plan_usable=True, current_limit_a=5, desired_limit_a=2,
                   ac_error_w=-100, actual_charge_a=4, inverter_w=9500,
                   physical_ac_ceiling_w=11000, gate_age_seconds=300)
    context.update(probe_feedback_fresh=True)
    context.update(overrides)
    context["shared_feedback_enabled"] = context["manager_plan_usable"]
    context["fast_probe_eligible"] = _as_native(_environment(_base_states()).from_string(config["actions"][7]["variables"]["fast_probe_eligible"]).render(**context))
    env = _environment(_base_states())
    return tuple(env.from_string(c["conditions"][0]["value_template"]).render(**context).strip() == "True" for c in choices)


def test_morning_noise_does_not_correct_or_probe_below_physical_ceiling():
    assert _damping_conditions() == (False, False)
    assert _damping_conditions(ac_error_w=-199, desired_limit_a=1) == (False, False)


def test_capture_is_fast_but_repeated_triggers_cannot_bypass_settling():
    assert _damping_conditions(ac_error_w=1500, desired_limit_a=32, gate_age_seconds=10)[0]
    assert not _damping_conditions(ac_error_w=1500, desired_limit_a=32, gate_age_seconds=9)[0]


def test_release_waits_and_small_amp_changes_are_ignored():
    assert not _damping_conditions(ac_error_w=-500, desired_limit_a=1, gate_age_seconds=44)[0]
    assert _damping_conditions(ac_error_w=-500, desired_limit_a=1, gate_age_seconds=45)[0]
    assert not _damping_conditions(ac_error_w=-500, desired_limit_a=3)[0]


def test_probe_requires_physical_ceiling_and_two_minute_settling():
    assert _damping_conditions(inverter_w=10900, gate_age_seconds=120)[1]
    assert not _damping_conditions(inverter_w=10900, gate_age_seconds=119)[1]
    assert not _damping_conditions(inverter_w=10900, actual_charge_a=1)[1]
    assert not _damping_conditions(inverter_w=10900, manager_live_current_ceiling_a=5)[1]


def test_lower_live_ceiling_bypasses_damping_immediately():
    assert _damping_conditions(manager_live_current_ceiling_a=0, gate_age_seconds=0, ac_error_w=0)[0]



def test_fast_probe_requires_fresh_saturated_binding_feedback():
    assert _damping_conditions(inverter_w=10960, ac_error_w=0, gate_age_seconds=10)[1]
    assert not _damping_conditions(inverter_w=10960, ac_error_w=0, gate_age_seconds=9)[1]
    assert not _damping_conditions(inverter_w=10960, ac_error_w=0, probe_feedback_fresh=False)[1]
    assert not _damping_conditions(inverter_w=10960, ac_error_w=0, actual_charge_a=1)[1]
    assert not _damping_conditions(inverter_w=10900, ac_error_w=0, gate_age_seconds=10)[1]


def test_probe_step_switches_back_to_slow_and_clamps_to_bms():
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    env = _environment(_base_states())
    t = env.from_string(config["actions"][7]["variables"]["adaptive_probe_limit_a"])
    context = dict(current_limit_a=24, manager_live_current_ceiling_a=250, fast_probe_step_a=5)
    assert float(t.render(**context, fast_probe_eligible=True)) == 29
    assert float(t.render(**context, fast_probe_eligible=False)) == 25
    context["manager_live_current_ceiling_a"] = 26
    assert float(t.render(**context, fast_probe_eligible=True)) == 26


def test_post_command_feedback_rejects_old_reports_and_invalid_power():
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    env = _environment(_base_states())
    t = env.from_string(config["actions"][7]["variables"]["probe_feedback_fresh"])
    assert t.render().strip() == "True"
    env.globals["states"].number.deye_battery_max_charge_current.last_changed = NOW
    assert t.render().strip() == "False"
    env = _environment(_base_states(**{"sensor.deye_grid_ct_power": "unavailable"}))
    assert env.from_string(t.name or config["actions"][7]["variables"]["probe_feedback_fresh"]).render().strip() == "False"


def test_forecast_loss_never_uses_shadow_full_charge_request():
    states = _base_states(**{
        "sensor.garage_deye_energy_manager_solar_plan_status": "unavailable",
        "sensor.garage_deye_energy_manager_solar_plan_generated_at": "unknown",
        "sensor.garage_deye_energy_manager_solar_plan_recommended_battery_dc_power": "unknown",
        "sensor.deye_shadow_recommended_charge_power": "13000",
        "sensor.deye_pv_power": "14000",
        "sensor.deye_inverter_power": "1500",
        "sensor.deye_grid_ct_power": "0",
        "sensor.deye_battery_power": "-12200",
        "number.deye_battery_max_charge_current": "226",
    })
    c = _evaluate(states)
    assert c["battery_feedback_mode"] == "live_capture_only"
    assert c["scheduled_target_inverter_w"] == 11500
    assert c["desired_limit_a"] < 40
    assert c["plan_battery_dc_w"] == 0



def test_missing_live_feedback_holds_gate_before_default_actions():
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    t = config["conditions"][-1]["value_template"]
    states = _base_states()
    assert _environment(states).from_string(t).render().strip() == "True"
    for id in ["sensor.deye_pv_power", "sensor.deye_grid_ct_power", "sensor.deye_battery_voltage"]:
        assert _environment({**states,id:"unavailable"}).from_string(t).render().strip() == "False"
    assert _environment({**states,"sensor.deye_battery_voltage":"0"}).from_string(t).render().strip() == "False"


def test_retired_planners_have_no_control_path_and_handover_off_stops_writes():
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    text = json.dumps(config)
    assert "sensor.deye_shadow" not in text
    assert "legacy_scheduled_target" not in text
    assert "binary_sensor.deye_energy_manager_forecast_data_valid" not in text
    assert "sensor.solcast_pv_forecast_forecast_remaining_today" not in text
    assert config["conditions"][0] == {"condition":"state", "entity_id":"input_boolean.deye_battery_plan_handover_enabled", "state":"on"}


def test_forecast_loss_retains_damped_feedback_conditions():
    states = _base_states(**{"sensor.garage_deye_energy_manager_solar_plan_status":"unavailable"})
    context = _evaluate(states)
    assert context["shared_feedback_enabled"] is True
    assert context["manager_plan_usable"] is False
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    context.update(current_limit_a=226, desired_limit_a=37, ac_error_w=-10000,gate_age_seconds=60)
    t = config["actions"][8]["choose"][0]["sequence"][0]["choose"][0]["conditions"][0]["value_template"]
    assert _environment(states).from_string(t).render(**context).strip() == "True"
