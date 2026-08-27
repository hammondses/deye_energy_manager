"""Safety and source-selection tests for event-driven WiCAN SOC."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ast
import math
from pathlib import Path

import pytest

from custom_components.deye_energy_manager.wican import WicanSocState, parse_wican_soc_response, resolve_taycan_soc

NOW = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).parents[3]


def observe(
    state: WicanSocState,
    identity: str,
    *,
    connected: bool = True,
    charging: bool = False,
    energy: float | None = 0.0,
    enabled: bool = True,
) -> str | None:
    return state.automatic_trigger(
        event_identity=identity,
        connected=connected,
        charging=charging,
        energy_kwh=energy,
        threshold_kwh=1.0,
        enabled=enabled,
    )


def test_restore_and_disabled_observation_never_create_boot_or_timer_trigger() -> None:
    restored = WicanSocState.restore(
        {
            "connector_connected": True,
            "charging_active": False,
            "last_event_identity": "before-restart",
            "soc": 42.5,
            "updated_at": NOW.isoformat(),
        }
    )

    assert restored.soc == 42.5
    assert observe(restored, "same-state", enabled=False) is None
    assert restored.last_trigger == "none"


def test_one_request_per_connector_transition_and_duplicate_event() -> None:
    state = WicanSocState(connector_connected=False, charging_active=False)

    assert observe(state, "plug-1") == "connector_connected"
    assert observe(state, "plug-1") is None
    assert observe(state, "churn") is None


def test_charging_start_and_stop_each_trigger_once_while_connected() -> None:
    state = WicanSocState(connector_connected=True, charging_active=False)

    assert observe(state, "start", charging=True) == "charging_start"
    assert observe(state, "start-churn", charging=True) is None
    assert observe(state, "stop", charging=False) == "charging_stop"
    assert observe(state, "unplug", connected=False) is None


def test_energy_threshold_uses_last_successful_anchor() -> None:
    state = WicanSocState(connector_connected=True, charging_active=True)
    state.record_success(35.5, "7AE 04 62 1D D0 47", NOW, "manual", 2.0)

    assert observe(state, "energy-1", charging=True, energy=2.99) is None
    assert observe(state, "energy-2", charging=True, energy=3.0) == "energy_threshold"
    assert state.energy_until_next_query(2.5, 1.0) == 0.5


def test_energy_reset_reanchors_without_request() -> None:
    state = WicanSocState(
        connector_connected=True,
        charging_active=True,
        last_success_energy_kwh=8.0,
        energy_anchor_kwh=8.0,
        last_energy_kwh=8.5,
    )

    assert observe(state, "reset", charging=True, energy=0.0) is None
    assert state.last_success_energy_kwh == 8.0
    assert state.energy_anchor_kwh == 0.0
    assert observe(state, "after-reset", charging=True, energy=1.0) == "energy_threshold"


def test_unavailable_energy_does_not_trigger_or_destroy_baseline() -> None:
    state = WicanSocState(connector_connected=True, charging_active=True, energy_anchor_kwh=2.0)

    assert observe(state, "unavailable", charging=True, energy=None) is None
    assert state.energy_anchor_kwh == 2.0


def test_failure_is_persisted_and_same_event_does_not_retry() -> None:
    state = WicanSocState(connector_connected=False, charging_active=False)
    assert observe(state, "plug") == "connector_connected"
    state.record_failure("connector_connected", "NO DATA")

    restored = WicanSocState.restore(state.payload())
    assert restored.last_result == "error"
    assert restored.last_error == "NO DATA"
    assert observe(restored, "plug") is None


def test_failed_energy_query_waits_for_another_full_threshold() -> None:
    state = WicanSocState(connector_connected=True, charging_active=True, energy_anchor_kwh=2.0, last_energy_kwh=2.9)
    assert observe(state, "threshold", charging=True, energy=3.0) == "energy_threshold"
    state.record_failure("energy_threshold", "timeout", 3.0)

    assert observe(state, "small-advance", charging=True, energy=3.1) is None
    assert observe(state, "next-threshold", charging=True, energy=4.0) == "energy_threshold"


def test_failed_connector_query_establishes_energy_attempt_anchor() -> None:
    state = WicanSocState(connector_connected=True, charging_active=False)
    state.record_failure("connector_connected", "NO DATA", 2.0)

    assert state.last_success_energy_kwh is None
    assert observe(state, "below-threshold", energy=2.9) is None
    assert observe(state, "threshold", energy=3.0) == "energy_threshold"


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"ok": False, "value": 35.5, "raw": "data"},
        {"ok": True, "value": "35.5", "raw": "data"},
        {"ok": True, "value": math.nan, "raw": "data"},
        {"ok": True, "value": -1, "raw": "data"},
        {"ok": True, "value": 101, "raw": "data"},
        {"ok": True, "value": 35.5, "raw": "NO DATA"},
    ],
)
def test_response_validation_rejects_invalid_payloads(response: object) -> None:
    with pytest.raises(ValueError):
        parse_wican_soc_response(response)


def test_response_validation_preserves_raw_and_decoded_soc() -> None:
    raw = "7AE 04 62 1D D0 47 \r\r>"
    assert parse_wican_soc_response({"ok": True, "raw": raw, "value": 35.5, "unit": ""}) == (35.5, raw)


def test_source_freshness_fallback_and_newer_local_last_known_good() -> None:
    assert resolve_taycan_soc(40, NOW - timedelta(minutes=5), 35, NOW, NOW, 60) == (40, "wican", 5.0)
    assert resolve_taycan_soc(40, NOW - timedelta(minutes=90), 42, NOW - timedelta(minutes=2), NOW, 60) == (
        42,
        "porsche_connect",
        2.0,
    )
    assert resolve_taycan_soc(44, NOW - timedelta(minutes=90), 35, NOW - timedelta(hours=3), NOW, 60) == (
        44,
        "wican_last_known_good",
        90.0,
    )


def test_coordinator_timer_startup_and_refresh_have_no_wican_query_call() -> None:
    coordinator = ast.parse((ROOT / "custom_components/deye_energy_manager/coordinator.py").read_text())
    setup = ast.parse((ROOT / "custom_components/deye_energy_manager/__init__.py").read_text())

    for tree, function_names in (
        (coordinator, {"_handle_time_interval", "_async_update_data"}),
        (setup, {"async_setup_entry"}),
    ):
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in function_names:
            assert "async_query_wican_soc" not in ast.unparse(functions[name])


def test_query_implementation_has_one_post_and_no_retry_loop() -> None:
    tree = ast.parse((ROOT / "custom_components/deye_energy_manager/coordinator.py").read_text())
    query = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_query_wican_soc")

    assert not any(isinstance(node, (ast.For, ast.AsyncFor, ast.While)) for node in ast.walk(query))
    assert sum(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "post" for node in ast.walk(query)) == 1
    assert ".locked()" in ast.unparse(query)
