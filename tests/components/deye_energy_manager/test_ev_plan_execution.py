"""Execute candidate actions with fake services and state changes during delays.

This focused interpreter preserves cached variables until explicit refresh;
it does not replace HA schema validation or live traces.
"""

import json
from datetime import timedelta
from jinja2 import Environment
import pytest
from test_ev_plan_handover_candidate import (
    CANDIDATE,
    NOW,
    _States,
    _base_states,
    _is_number,
    _native,
    _timestamp,
)

OWNER = "input_boolean.ev_solar_controller_owns_session"
CHARGE = "switch.evcharger_charge_control"
DEFICIT = "timer.ev_solar_sustained_deficit"
PLAN = "sensor.garage_deye_energy_manager_solar_plan_"


class Halt(Exception):
    pass


class Run:
    def __init__(self, states, stop_succeeds=True, delay_change=None, reported_overrides=None):
        self.states, self.stop_succeeds, self.delay_change = (
            states,
            stop_succeeds,
            delay_change,
        )
        self.reported_overrides = reported_overrides or {}
        for helper in json.loads(CANDIDATE.read_text())["helpers"]:
            if helper["platform"] == "input_boolean":
                states.setdefault(helper["entity_id"], "off")
            elif helper["platform"] == "timer":
                states.setdefault(helper["entity_id"], "idle")
        self.now, self.context, self.calls = NOW, {}, []
        self.env = Environment()
        api = _States(states, NOW, self.reported_overrides)
        self.env.globals.update(
            states=api,
            is_state=lambda e, s: api(e) == s,
            is_number=_is_number,
            as_timestamp=_timestamp,
            now=lambda: self.now,
        )

    def render(self, v):
        if isinstance(v, str):
            return _native(self.env.from_string(v).render(**self.context).strip())
        if isinstance(v, dict):
            return {k: self.render(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self.render(x) for x in v]
        return v

    def condition(self, c):
        kind = c["condition"]
        if kind == "template":
            return bool(self.render(c["value_template"]))
        if kind == "state":
            return self.states.get(c["entity_id"], "unknown") in (
                c["state"] if isinstance(c["state"], list) else [c["state"]]
            )
        if kind == "time":
            return (
                c.get("after", "00:00:00")
                <= self.now.strftime("%H:%M:%S")
                < c.get("before", "24:00:00")
            )
        if kind == "trigger":
            return "poll" in (c["id"] if isinstance(c["id"], list) else [c["id"]])
        if kind in ("and", "or", "not"):
            values = [self.condition(x) for x in c["conditions"]]
            return (
                all(values)
                if kind == "and"
                else any(values)
                if kind == "or"
                else not any(values)
            )
        raise AssertionError(c)

    def matches(self, cs):
        return (
            bool(self.render(cs))
            if isinstance(cs, str)
            else all(self.condition(c) for c in cs)
        )

    def execute(self, seq):
        for step in seq:
            if "variables" in step:
                for k, v in step["variables"].items():
                    self.context[k] = self.render(v)
            elif "condition" in step:
                if not self.condition(step):
                    raise Halt
            elif "choose" in step:
                branch = next(
                    (b for b in step["choose"] if self.matches(b["conditions"])), None
                )
                self.execute(branch["sequence"] if branch else step.get("default", []))
            elif "if" in step:
                self.execute(
                    step.get("then" if self.matches(step["if"]) else "else", [])
                )
            elif "delay" in step:
                self.now += timedelta(**step["delay"])
                if self.delay_change:
                    self.delay_change(self, step["delay"])
            elif "wait_template" in step:
                if not self.render(step["wait_template"]) and not step.get(
                    "continue_on_timeout", True
                ):
                    raise Halt
            elif "action" in step:
                action = step["action"]
                ids = step.get("target", {}).get("entity_id", [])
                if isinstance(ids, str):
                    ids = [ids]
                self.calls.append((action, ids, self.render(step.get("data", {}))))
                for entity in ids:
                    if action == "switch.turn_off" and entity == CHARGE:
                        if self.stop_succeeds:
                            self.states[entity] = "off"
                    elif action == "switch.turn_on" and entity == CHARGE:
                        pass  # async status, not immediate acknowledgement
                    elif action.endswith(".turn_on"):
                        self.states[entity] = "on"
                    elif action.endswith(".turn_off"):
                        self.states[entity] = "off"
                    elif action == "timer.start":
                        self.states[entity] = "active"
                    elif action == "timer.cancel":
                        self.states[entity] = "idle"
            elif "stop" in step:
                raise Halt
            else:
                raise AssertionError(step)

    def poll(self):
        c = json.loads(CANDIDATE.read_text())["candidate_config"]
        self.context = {}
        try:
            self.execute([{"variables": c["variables"]}, *c["actions"]])
        except Halt:
            pass
        return self


def active(**updates):
    return _base_states(
        **{
            OWNER: "on",
            CHARGE: "on",
            "input_boolean.ev_solar_controller_stopped_session": "off",
            "sensor.evcharger_status_connector": "Charging",
            "sensor.evcharger_current_import": "6",
            "sensor.evcharger_power_active_import": "1.44",
            "sensor.deye_essential_power": "3440",
            "sensor.deye_battery_power": "-1000",
            PLAN + "recommended_ev_amps": "0",
            "input_boolean.ev_solar_deficit_stop_pending": "off",
            **updates,
        }
    )


def stops(run):
    return [c for c in run.calls if c[0] == "switch.turn_off" and CHARGE in c[1]]


def test_short_cloud_recovery_cancels_dwell_without_stopping():
    s = active()
    first = Run(s).poll()
    assert s[DEFICIT] == "active" and not stops(first)
    s[PLAN + "recommended_ev_amps"] = "8"
    s["sensor.deye_battery_power"] = "-3500"
    recovered = Run(s).poll()
    assert (
        s[DEFICIT] == "idle"
        and s["input_boolean.ev_solar_deficit_stop_pending"] == "off"
    )
    assert not stops(recovered)


@pytest.mark.parametrize("success", [True, False])
def test_sustained_charge_shortfall_stops_or_retains_ownership(success):
    s = active()
    Run(s).poll()
    s[DEFICIT] = "idle"  # missed timer.finished
    r = Run(s, stop_succeeds=success).poll()
    assert stops(r)
    assert s[OWNER] == ("off" if success else "on")
    assert s[CHARGE] == ("off" if success else "on")
    if not success:
        s[PLAN + "recommended_ev_amps"] = "12"
        retry = Run(s, stop_succeeds=False).poll()
        assert not any(c[0] == "switch.turn_on" and CHARGE in c[1] for c in retry.calls)


def test_target_reached_during_verification_prevents_clear_and_retry():
    s = active(**{PLAN + "recommended_ev_amps": "20"})

    def update(r, duration):
        if duration.get("seconds") == 20:
            r.states["sensor.garage_deye_energy_manager_effective_taycan_soc"] = "80"

    r = Run(s, delay_change=update).poll()
    assert len([c for c in r.calls if c[0] == "ocpp.set_charge_rate"]) == 1
    assert not any(c[0] == "ocpp.clear_profile" for c in r.calls)


def test_stop_then_qualified_restart_retains_pending_until_async_status():
    s = active()
    Run(s).poll()
    s[DEFICIT] = "idle"
    Run(s).poll()
    assert s[CHARGE] == "off" and s[OWNER] == "off"
    s[PLAN + "recommended_ev_amps"] = "8"
    s["sensor.deye_battery_power"] = "-4000"
    s["sensor.evcharger_status_connector"] = "Finishing"
    s["sensor.evcharger_current_import"] = "0"
    s["sensor.evcharger_power_active_import"] = "0"
    restart_timer = "timer.ev_solar_restart_qualification"
    Run(s).poll()
    assert s[restart_timer] == "active"
    s[restart_timer] = "idle"
    start = Run(s).poll()
    assert any(c[0] == "switch.turn_on" and CHARGE in c[1] for c in start.calls)
    assert s["input_boolean.ev_solar_start_confirmation_pending"] == "on"
    assert (
        s[OWNER] == "on"
    )  # Own the request while waiting for its asynchronous result.
    s[CHARGE] = "on"
    s["sensor.evcharger_status_connector"] = "Charging"
    Run(s).poll()
    assert s[OWNER] == "on"
    assert s["input_boolean.ev_solar_start_confirmation_pending"] == "off"


def test_missing_grid_input_does_not_cancel_invalid_data_grace_forever():
    s = active(**{"sensor.deye_grid_ct_power": "unavailable"})
    grace = "timer.ev_solar_invalid_data_grace"
    Run(s).poll()
    assert s[grace] == "active"
    Run(s).poll()
    assert s[grace] == "active"
    s[grace] = "idle"
    expired = Run(s).poll()
    assert stops(expired) and s[OWNER] == "off"


def test_target_reached_during_restart_delay_prevents_start():
    s = _base_states(**{"input_boolean.ev_solar_restart_pending": "on"})

    def update(r, duration):
        r.states["sensor.garage_deye_energy_manager_effective_taycan_soc"] = "80"

    r = Run(s, delay_change=update).poll()
    assert not any(c[0] == "switch.turn_on" and CHARGE in c[1] for c in r.calls)
    assert not any(c[0] == "ocpp.set_charge_rate" for c in r.calls)


def test_handover_of_running_session_at_target_stops_instead_of_abandoning_it():
    s = active(
        **{OWNER: "off", "sensor.garage_deye_energy_manager_effective_taycan_soc": "80"}
    )
    first = Run(s).poll()
    second = Run(s).poll()
    assert stops(first) or stops(second)
    assert s[CHARGE] == "off"


def test_house_load_jump_during_verification_caps_the_retry_at_fresh_site_room():
    s = active(**{PLAN + "recommended_ev_amps": "20"})

    def update(run, duration):
        if duration.get("seconds") == 20:
            run.states["sensor.deye_essential_power"] = "13000"

    run = Run(s, delay_change=update).poll()
    limits = [
        call[2]["custom_profile"]["chargingSchedule"]["chargingSchedulePeriod"][0][
            "limit"
        ]
        for call in run.calls
        if call[0] == "ocpp.set_charge_rate"
    ]
    assert len(limits) == 2
    assert limits[0] == 20
    assert 6 <= limits[1] <= 8  # (13.5 kW - (13 kW - 1.44 kW)) / 240 V


def test_zero_ev_advice_during_verification_prevents_profile_clear():
    s = active(**{PLAN + "recommended_ev_amps": "20"})

    def update(run, duration):
        if duration.get("seconds") == 20:
            run.states[PLAN + "recommended_ev_amps"] = "0"

    run = Run(s, delay_change=update).poll()
    assert len([call for call in run.calls if call[0] == "ocpp.set_charge_rate"]) == 1
    assert not any(call[0] == "ocpp.clear_profile" for call in run.calls)


def test_full_battery_six_amp_start_accepts_soc_verified_by_fresh_manager_plan(
    monkeypatch,
):
    from types import SimpleNamespace

    original = _States.__getattr__

    def domain(self, name):
        source = original(self, name)
        if name != "sensor":
            return source

        class Sensors:
            deye_battery_soc = SimpleNamespace(last_reported=NOW - timedelta(minutes=8))

            def __getattr__(self, key):
                return getattr(source, key)

        return Sensors()

    monkeypatch.setattr(_States, "__getattr__", domain)
    states = _base_states(
        **{
            PLAN + "recommended_ev_amps": "6",
            "input_boolean.ev_solar_restart_pending": "on",
        }
    )
    run = Run(states).poll()
    assert any(call[0] == "switch.turn_on" and CHARGE in call[1] for call in run.calls)


def test_stopped_long_idle_restarts_after_dwell_without_fresh_idle_meters():
    states = _base_states(
        **{
            "input_boolean.ev_solar_controller_stopped_session": "on",
            "input_boolean.ev_solar_restart_pending": "on",
            "switch.evcharger_charge_control": "off",
            "sensor.evcharger_status_connector": "Finishing",
            "sensor.evcharger_transaction_id": "0",
            PLAN + "recommended_ev_amps": "8",
            "timer.ev_solar_restart_qualification": "active",
        }
    )
    stale = NOW - timedelta(minutes=20)
    reported = {
        "sensor.evcharger_current_import": stale,
        "sensor.evcharger_power_active_import": stale,
        "sensor.evcharger_voltage": stale,
        "sensor.evcharger_status_connector": stale,
    }
    run = Run(states, reported_overrides=reported).poll()
    assert not any(call[0] == "switch.turn_on" and CHARGE in call[1] for call in run.calls)
    states["timer.ev_solar_restart_qualification"] = "idle"
    run = Run(states, reported_overrides=reported).poll()
    assert any(call[0] == "switch.turn_on" and CHARGE in call[1] for call in run.calls)
    assert states["input_boolean.ev_solar_start_confirmation_pending"] == "on"


def test_active_session_with_stale_ev_meters_never_sends_profile():
    states = active(**{PLAN + "recommended_ev_amps": "20"})
    stale = NOW - timedelta(minutes=20)
    run = Run(
        states,
        reported_overrides={
            "sensor.evcharger_current_import": stale,
            "sensor.evcharger_power_active_import": stale,
        },
    ).poll()
    limits = [
        call[2]["custom_profile"]["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"]
        for call in run.calls if call[0] == "ocpp.set_charge_rate"
    ]
    assert limits == [6]  # stale active meters only permit the conservative floor
