"""Offline safety checks for the review-only EV plan handover candidate."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment


CANDIDATE = (
    Path(__file__).parents[3]
    / "docs"
    / "automation-candidates"
    / "ev-plan-handover.json"
)
NOW = datetime.fromisoformat("2026-10-03T12:00:00+13:00")


class _States:
    def __init__(self, values: dict[str, str], reported: datetime) -> None:
        self.values = values
        self.reported = reported

    def __call__(self, entity_id: str) -> str:
        return self.values.get(entity_id, "unknown")

    def __getattr__(self, domain: str) -> SimpleNamespace:
        class _Domain:
            def __getattr__(_, object_id: str) -> SimpleNamespace:
                return SimpleNamespace(last_reported=self.reported)

        return _Domain()


def _timestamp(value: object, default: float = 0) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return float(default)


def _is_number(value: object) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _native(value: str) -> object:
    if value in {"True", "true"}:
        return True
    if value in {"False", "false"}:
        return False
    try:
        return float(value)
    except ValueError:
        return value


def _base_states(**overrides: str) -> dict[str, str]:
    states = {
        "switch.garage_deye_energy_manager_ev_manual_charging_override": "off",
        "switch.garage_deye_energy_manager_ev_solar_charging_enabled": "on",
        "switch.garage_deye_energy_manager_enabled": "on",
        "switch.garage_deye_energy_manager_ev_control_enabled": "on",
        "select.garage_deye_energy_manager_daytime_ev_writer": "external_automation",
        "switch.garage_deye_energy_manager_enabled": "on",
        "sensor.garage_deye_energy_manager_solar_plan_status": "advisory",
        "sensor.garage_deye_energy_manager_solar_plan_generated_at": NOW.isoformat(),
        "sensor.garage_deye_energy_manager_solar_plan_recommended_ev_amps": "8",
        "sensor.garage_deye_energy_manager_solar_plan_expected_battery_dc_power": "3.0",
        "sensor.garage_deye_energy_manager_solar_plan_target_reachable": "yes",
        "sensor.garage_deye_energy_manager_ev_active_target_soc": "80",
        "sensor.garage_deye_energy_manager_effective_taycan_soc": "65",
        "sensor.evcharger_status_connector": "Finishing",
        "sensor.evcharger_current_import": "0",
        "sensor.evcharger_power_active_import": "0",
        "sensor.evcharger_voltage": "240",
        "sensor.deye_grid_voltage": "240",
        "sensor.deye_essential_power": "6400",
        "sensor.garage_deye_energy_manager_base_load_estimate": "0",
        "sensor.deye_grid_ct_power": "-4000",
        "sensor.deye_battery_power": "300",
        "sensor.deye_battery_soc": "100",
        "number.garage_deye_energy_manager_daily_battery_target_soc": "100",
        "input_boolean.ev_solar_ev_telemetry_verified": "on",
        "input_boolean.ev_solar_controller_owns_session": "off",
        "input_boolean.ev_solar_controller_stopped_session": "on",
        "input_boolean.ev_solar_start_confirmation_pending": "off",
        "switch.evcharger_charge_control": "off",
        "switch.evcharger_availability": "on",
        "input_number.ev_solar_site_ceiling_w": "13500",
        "input_number.ev_solar_target_tolerance_pct": "0.5",
        "input_number.ev_solar_restart_amps": "8",
        "input_number.ev_solar_restart_margin_w": "300",
        "input_number.ev_solar_deficit_battery_w": "500",
        "input_number.ev_solar_deficit_grid_w": "500",
        "input_number.ev_solar_battery_charge_shortfall_w": "500",
        "input_number.ev_solar_deficit_minutes": "12",
        "input_number.ev_solar_invalid_plan_minutes": "5",
        "input_number.ev_solar_restart_minutes": "7",
        "timer.ev_solar_sustained_deficit": "idle",
        "timer.ev_solar_restart_qualification": "idle",
        "timer.ev_solar_invalid_data_grace": "idle",
        "timer.ev_solar_start_confirmation": "idle",
        "timer.ev_solar_start_confirmation": "idle",
    }
    states.update(overrides)
    return states


def _context(overrides: dict[str, str] | None = None, *, age_seconds: int = 0) -> dict[str, object]:
    candidate = json.loads(CANDIDATE.read_text())
    env = Environment()
    rendered_states = _base_states(**(overrides or {}))
    if age_seconds:
        rendered_states["sensor.garage_deye_energy_manager_solar_plan_generated_at"] = (
            NOW - timedelta(seconds=age_seconds)
        ).isoformat()
    state_api = _States(rendered_states, NOW)
    env.globals.update(
        states=state_api,
        is_state=lambda entity_id, expected: state_api(entity_id) == expected,
        is_number=_is_number,
        as_timestamp=_timestamp,
        now=lambda: NOW,
    )
    context: dict[str, object] = {}
    for name, template in candidate["candidate_config"]["variables"].items():
        rendered = env.from_string(template).render(**context)
        context[name] = _native(rendered)
    return context


def _walk(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _matches_candidate_conditions(
    conditions: list[dict[str, object]], states: dict[str, str]
) -> bool:
    env = Environment()
    state_api = _States(states, NOW)
    context = _context(states)
    env.globals.update(
        states=state_api,
        is_state=lambda entity_id, expected: state_api(entity_id) == expected,
        is_number=_is_number,
        as_timestamp=_timestamp,
        now=lambda: NOW,
    )
    for condition in conditions:
        if condition["condition"] == "state":
            if state_api(str(condition["entity_id"])) != condition["state"]:
                return False
        elif condition["condition"] == "template":
            rendered = env.from_string(str(condition["value_template"])).render(**context)
            if rendered not in {"True", "true", "1"}:
                return False
        else:
            raise AssertionError(f"Unexpected top-level condition in simulation: {condition}")
    return True


def _first_matching_action(states: dict[str, str]) -> str | None:
    choices = json.loads(CANDIDATE.read_text())["candidate_config"]["actions"][0]["choose"]
    return next(
        (branch["alias"] for branch in choices if _matches_candidate_conditions(branch["conditions"], states)),
        None,
    )


def test_plan_freshness_has_bounded_age_and_future_skew() -> None:
    assert _context(age_seconds=90)["plan_fresh"] is True
    assert _context(age_seconds=91)["plan_fresh"] is False
    assert _context({"sensor.garage_deye_energy_manager_solar_plan_generated_at": (NOW + timedelta(seconds=5)).isoformat()})["plan_fresh"] is True
    assert _context({"sensor.garage_deye_energy_manager_solar_plan_generated_at": (NOW + timedelta(seconds=6)).isoformat()})["plan_fresh"] is False


def test_non_ev_house_and_integer_site_cap_use_live_ev_telemetry() -> None:
    values = _context()
    assert values["ev_power_fresh"] is True
    assert values["non_ev_house_w"] == 6400
    assert values["site_room_a"] == 29
    assert values["request_amps"] == 8


def test_restart_needs_eight_amp_advice_or_full_battery_six_amp_case() -> None:
    assert _context()["restart_qualified_now"] is True
    below = _context({
        "sensor.garage_deye_energy_manager_solar_plan_recommended_ev_amps": "7",
        "sensor.deye_battery_soc": "99",
    })
    assert below["restart_qualified_now"] is False
    full_battery = _context({
        "sensor.garage_deye_energy_manager_solar_plan_recommended_ev_amps": "6",
        "sensor.deye_battery_soc": "100",
    })
    assert full_battery["restart_qualified_now"] is True


def test_completion_pressure_includes_zero_ev_budget_and_battery_charge_shortfall() -> None:
    zero_ev_budget = _context({
        "sensor.garage_deye_energy_manager_solar_plan_target_reachable": "yes",
        "sensor.garage_deye_energy_manager_solar_plan_recommended_ev_amps": "0",
        "sensor.deye_battery_power": "600",
        "sensor.deye_grid_ct_power": "-1000",
    })
    assert zero_ev_budget["completion_risk"] is True
    assert zero_ev_budget["sustained_deficit"] is True

    not_charging_enough = _context({
        "sensor.garage_deye_energy_manager_solar_plan_target_reachable": "yes",
        "sensor.garage_deye_energy_manager_solar_plan_recommended_ev_amps": "0",
        "sensor.garage_deye_energy_manager_solar_plan_expected_battery_dc_power": "3.0",
        "sensor.deye_battery_power": "-1000",
        "sensor.deye_grid_ct_power": "-1000",
    })
    assert not_charging_enough["completion_risk"] is True
    assert not_charging_enough["battery_charge_shortfall"] is True
    assert not_charging_enough["sustained_deficit"] is True


def test_unverified_ev_telemetry_blocks_restart_and_increases() -> None:
    values = _context({"input_boolean.ev_solar_ev_telemetry_verified": "off"})
    assert values["ev_power_fresh"] is False
    assert values["ev_current_fresh"] is False
    assert values["restart_qualified_now"] is False


def test_candidate_keeps_integer_ocpp_profile_and_guarded_recovery() -> None:
    candidate = json.loads(CANDIDATE.read_text())
    config = candidate["candidate_config"]
    calls = [node for node in _walk(config) if node.get("action") == "ocpp.set_charge_rate"]
    assert calls
    for call in calls:
        profile = call["data"]["custom_profile"]
        assert profile["chargingProfileId"] == 9102
        assert profile["chargingProfilePurpose"] == "TxDefaultProfile"
        assert profile["chargingProfileKind"] == "Absolute"
        assert profile["chargingSchedule"]["chargingRateUnit"] == "A"
        limit = profile["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"]
        if isinstance(limit, int):
            continue
        assert isinstance(limit, str) and limit.startswith("{{ ") and limit.endswith(" }}")
        expression = limit[3:-3].strip()
        if "| int" in expression or "|int" in expression:
            continue
        definitions = [
            node["variables"][expression]
            for node in _walk(config)
            if isinstance(node.get("variables"), dict) and expression in node["variables"]
        ]
        assert definitions, f"No integer-valued template defines {expression}"
        assert any("| int" in template or "|int" in template for template in definitions)
    recovery = next(node for node in _walk(config) if node.get("alias", "").startswith("One-shot SuspendedEV"))
    assert any(node.get("delay") == {"seconds": 3} for node in recovery["sequence"])
    assert sum(node.get("delay") == {"seconds": 1} for node in recovery["sequence"]) == 1
    assert any(node.get("entity_id") == "switch.garage_deye_energy_manager_ev_manual_charging_override" for node in recovery["sequence"])
    assert any(node.get("action") == "ocpp.clear_profile" for node in _walk(config))


def test_manual_and_night_yield_without_stopping_manual_session() -> None:
    candidate = json.loads(CANDIDATE.read_text())
    actions = candidate["candidate_config"]["actions"][0]["choose"]
    yield_branch = next(branch for branch in actions if branch.get("alias", "").startswith("Yield ownership"))
    yield_actions = list(_walk(yield_branch["sequence"]))
    assert any("manual or not daytime" in node.get("value_template", "") for node in _walk(yield_branch))
    assert not any(node.get("action") == "switch.turn_off" and node.get("target", {}).get("entity_id") == "switch.evcharger_charge_control" for node in yield_actions)
    assert candidate["candidate_config"]["mode"] == "single"
    assert {helper["entity_id"] for helper in candidate["helpers"] if helper["platform"] == "timer"} == {
        "timer.ev_solar_sustained_deficit",
        "timer.ev_solar_restart_qualification",
        "timer.ev_solar_invalid_data_grace",
        "timer.ev_solar_start_confirmation",
    }


def test_invalid_advice_and_sustained_deficit_both_have_bounded_stop_paths() -> None:
    candidate = json.loads(CANDIDATE.read_text())
    actions = candidate["candidate_config"]["actions"][0]["choose"]
    invalid = next(branch for branch in actions if branch.get("alias", "").startswith("Ride through invalid"))
    assert any(node.get("id") == "invalid_timer_finished" for node in _walk(candidate["candidate_config"]["triggers"]))
    invalid_stop = next(branch for branch in actions if branch.get("alias", "").startswith("Stop owned session when invalid-data grace"))
    assert any(node.get("action") == "switch.turn_off" and node.get("target", {}).get("entity_id") == "switch.evcharger_charge_control" for node in _walk(invalid_stop))
    safe_six_profile = next(node for node in _walk(invalid) if node.get("action") == "ocpp.set_charge_rate")
    assert safe_six_profile["data"]["custom_profile"]["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"] == 6
    cloud = next(branch for branch in actions if branch.get("alias", "").startswith("Keep a connected active session"))
    assert any("completion_risk and sustained_deficit" in node.get("value_template", "") for node in _walk(cloud))
    assert any(node.get("id") == "deficit_timer_finished" for node in _walk(candidate["candidate_config"]["triggers"]))
    invalid_grace = next(helper for helper in candidate["helpers"] if helper["entity_id"] == "input_number.ev_solar_invalid_plan_minutes")
    assert invalid_grace["creation_default"] == 5 and "initial" not in invalid_grace and invalid_grace["min"] >= 1 and invalid_grace["max"] <= 10


def test_expired_deficit_timer_is_consumed_after_a_missed_timer_finished_event() -> None:
    active = _base_states(
        **{
            "sensor.garage_deye_energy_manager_solar_plan_target_reachable": "no",
            "sensor.garage_deye_energy_manager_solar_plan_recommended_ev_amps": "0",
            "sensor.deye_battery_power": "600",
            "input_boolean.ev_solar_controller_owns_session": "on",
            "input_boolean.ev_solar_deficit_stop_pending": "on",
            "switch.evcharger_charge_control": "on",
            "timer.ev_solar_sustained_deficit": "idle",
        }
    )
    assert _first_matching_action(active) == "Stop after sustained deficit when timer expiry was delivered or recovered by polling"
    still_waiting = {**active, "timer.ev_solar_sustained_deficit": "active"}
    assert _first_matching_action(still_waiting) == "Keep a connected active session at 6 A while advice is below threshold"


def test_stop_paths_keep_ownership_until_charge_control_confirms_off() -> None:
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    stop_paths = [
        branch
        for branch in config["actions"][0]["choose"]
        if branch.get("alias", "").startswith((
            "Immediately stop",
            "Stop after sustained deficit",
            "Stop owned session when invalid-data",
            "Stop immediately if even",
        ))
    ]
    assert len(stop_paths) == 4
    for branch in stop_paths:
        sequence = branch["sequence"]
        stop_index = next(
            i
            for i, action in enumerate(sequence)
            if action.get("action") == "switch.turn_off"
            and action.get("target", {}).get("entity_id") == "switch.evcharger_charge_control"
        )
        assert sequence[stop_index + 1]["wait_template"] == "{{ is_state('switch.evcharger_charge_control', 'off') }}"
        assert sequence[stop_index + 1]["continue_on_timeout"] is False
        clear_owner = next(
            i
            for i, action in enumerate(sequence)
            if action.get("action") == "input_boolean.turn_off"
            and action.get("target", {}).get("entity_id") == "input_boolean.ev_solar_controller_owns_session"
        )
        assert clear_owner > stop_index + 1


def test_restart_timer_expiry_is_consumed_by_next_poll_with_fresh_rechecks() -> None:
    states = _base_states(
        **{
            "input_boolean.ev_solar_controller_stopped_session": "on",
            "input_boolean.ev_solar_restart_pending": "on",
            "timer.ev_solar_restart_qualification": "idle",
        }
    )
    assert _context(states)["restart_qualified_now"] is True
    assert _first_matching_action(states) == "Start or restart only after sustained qualified surplus"


def test_site_room_uses_manager_base_load_floor_when_ev_and_house_samples_are_skewed() -> None:
    values = _context({
        "sensor.deye_essential_power": "3315",
        "sensor.evcharger_power_active_import": "6.657",
        "sensor.garage_deye_energy_manager_base_load_estimate": "1400",
        "sensor.evcharger_voltage": "248.5",
    })
    assert values["non_ev_house_w"] == 1400
    assert values["site_room_a"] == 48


def test_restart_requires_confirmed_off_and_has_async_active_confirmation_latch() -> None:
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    branches = config["actions"][0]["choose"]
    restart = next(branch for branch in branches if branch.get("alias", "").startswith("Start or restart"))
    sequence = restart["sequence"]
    service_index = next(i for i, node in enumerate(sequence) if node.get("action") == "switch.turn_on" and node.get("target", {}).get("entity_id") == "switch.evcharger_charge_control")
    assert sequence[service_index - 1]["action"] == "timer.start"
    assert any(node.get("action") == "input_boolean.turn_on" and node.get("target", {}).get("entity_id") == "input_boolean.ev_solar_controller_owns_session" for node in sequence[:service_index])
    assert sequence[service_index + 1]["wait_template"].find("sensor.evcharger_status_connector") >= 0
    assert sequence[service_index + 1]["continue_on_timeout"] is True
    assert "is_state('switch.evcharger_charge_control', 'off')" in config["variables"]["restart_qualified_now"]
    timeout_recovery = next(branch for branch in branches if branch.get("alias", "").startswith("Release failed RemoteStart"))
    assert all(any(action.get("action") == "input_boolean.turn_off" and action.get("target", {}).get("entity_id") == entity for action in timeout_recovery["sequence"]) for entity in ("input_boolean.ev_solar_controller_owns_session", "input_boolean.ev_solar_start_confirmation_pending"))
    stuck_start = next(branch for branch in branches if branch.get("alias", "").startswith("Stop unconfirmed OCPP start"))
    assert next(node for node in stuck_start["sequence"] if node.get("action") == "switch.turn_off")["target"]["entity_id"] == "switch.evcharger_charge_control"
    assert any(node.get("wait_template") == "{{ is_state('switch.evcharger_charge_control','off') }}" for node in stuck_start["sequence"])

def test_availability_switch_is_not_used_as_a_state_gate() -> None:
    config = json.loads(CANDIDATE.read_text())["candidate_config"]
    assert not any(node.get("condition") == "state" and node.get("entity_id") == "switch.evcharger_availability" for node in _walk(config))



def test_async_remote_start_poll_paths_confirm_retry_or_safely_stop() -> None:
    started = _base_states(
        **{
            "input_boolean.ev_solar_start_confirmation_pending": "on",
            "input_boolean.ev_solar_controller_owns_session": "on",
            "switch.evcharger_charge_control": "on",
            "sensor.evcharger_status_connector": "Charging",
        }
    )
    assert _first_matching_action(started) == "Confirm asynchronous OCPP start on later status update"

    rejected = _base_states(
        **{
            "input_boolean.ev_solar_start_confirmation_pending": "on",
            "input_boolean.ev_solar_controller_owns_session": "on",
            "switch.evcharger_charge_control": "off",
            "timer.ev_solar_start_confirmation": "idle",
        }
    )
    assert _first_matching_action(rejected) == "Release failed RemoteStart after bounded confirmation timeout"

    stuck = _base_states(
        **{
            "input_boolean.ev_solar_start_confirmation_pending": "on",
            "input_boolean.ev_solar_controller_owns_session": "on",
            "switch.evcharger_charge_control": "on",
            "sensor.evcharger_status_connector": "Preparing",
            "timer.ev_solar_start_confirmation": "idle",
        }
    )
    assert _first_matching_action(stuck) == "Stop unconfirmed OCPP start and retain restart hysteresis"
