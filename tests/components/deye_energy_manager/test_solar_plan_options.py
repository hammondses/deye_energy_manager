"""Safe defaults and option-only controls for the daytime solar advisory."""

import ast
from pathlib import Path

from custom_components.deye_energy_manager.const import (
    DEFAULT_ENTITY_MAP,
    FEATURE_DEFAULTS,
    NUMBER_DEFAULTS,
    TEXT_DEFAULTS,
)


def test_daytime_solar_planner_defaults_are_advisory_only() -> None:
    assert FEATURE_DEFAULTS["daytime_plan_enabled"] is False
    assert FEATURE_DEFAULTS["deye_control_enabled"] is False
    assert FEATURE_DEFAULTS["ev_control_enabled"] is False
    assert NUMBER_DEFAULTS["solar_plan_inverter_ac_limit_kw"] == 12.0
    assert NUMBER_DEFAULTS["solar_plan_export_limit_kw"] == 10.0
    assert NUMBER_DEFAULTS["solar_plan_site_ac_limit_kw"] == 13.5
    assert NUMBER_DEFAULTS["solar_plan_battery_max_charge_dc_kw"] == 13.5
    assert NUMBER_DEFAULTS["solar_plan_battery_max_discharge_dc_kw"] == 13.5
    assert NUMBER_DEFAULTS["solar_plan_inverter_efficiency"] == 0.96
    assert NUMBER_DEFAULTS["solar_plan_discharge_efficiency"] == 0.96
    assert NUMBER_DEFAULTS["solar_plan_max_forecast_age_minutes"] == 120.0
    assert NUMBER_DEFAULTS["solar_plan_forecast_risk_blend"] == 0.0
    assert NUMBER_DEFAULTS["solar_plan_array_capacity_kw"] == 16.56
    assert NUMBER_DEFAULTS["solar_plan_array_tilt_deg"] == 8.0
    assert NUMBER_DEFAULTS["solar_plan_array_azimuth_deg"] == 2.0
    assert NUMBER_DEFAULTS["solar_plan_clear_sky_scale"] == 1.25
    assert NUMBER_DEFAULTS["solar_plan_pv_dc_limit_kw"] == 18.0
    assert NUMBER_DEFAULTS["solar_plan_clear_sky_weather_factor"] == 1.0
    assert TEXT_DEFAULTS["solar_plan_charge_acceptance_curve"] == ""


def test_solar_plan_inputs_have_local_entity_defaults() -> None:
    assert DEFAULT_ENTITY_MAP["forecast_updated_at"] == "sensor.solcast_pv_forecast_api_last_polled"
    assert DEFAULT_ENTITY_MAP["battery_charge_limit_current"] == "sensor.deye_battery_charge_limit_current"
    assert DEFAULT_ENTITY_MAP["battery_voltage"] == "sensor.deye_battery_voltage"
    assert DEFAULT_ENTITY_MAP["sun"] == "sun.sun"


def test_daytime_plan_switch_only_changes_its_option() -> None:
    source = Path("custom_components/deye_energy_manager/switch.py").read_text()
    tree = ast.parse(source)
    switch_map = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SWITCHES" for target in node.targets)
    )
    assert any(
        isinstance(key, ast.Constant)
        and key.value == "daytime_plan_enabled"
        for key in switch_map.keys
    )
    switch_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DeyeFeatureSwitch"
    )
    methods = {node.name: node for node in switch_class.body if isinstance(node, ast.AsyncFunctionDef)}
    for method_name in ("async_turn_on", "async_turn_off"):
        calls = [
            node.func.attr
            for node in ast.walk(methods[method_name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        assert calls == ["async_set_option"]


def test_forecast_proxy_sensor_uses_advisory_result_contract() -> None:
    tree = ast.parse(Path("custom_components/deye_energy_manager/sensor.py").read_text())
    descriptions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "DeyeSensorDescription"
    ]
    proxy = next(
        description
        for description in descriptions
        if any(
            keyword.arg == "key"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "solar_plan_forecast_ac_proxy_used"
            for keyword in description.keywords
        )
    )
    assert any(
        isinstance(node, ast.Constant) and node.value == "forecast_ac_proxy_used"
        for node in ast.walk(proxy)
    )


def test_plan_freshness_and_target_reachability_sensors_use_result_fields() -> None:
    tree = ast.parse(Path("custom_components/deye_energy_manager/sensor.py").read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "DeyeSensorDescription"
    ]
    keys_to_fields = {
        "solar_plan_generated_at": "generated_at",
        "solar_plan_target_reachable": "target_reachable",
    }
    for key, field in keys_to_fields.items():
        description = next(
            call
            for call in calls
            if any(
                keyword.arg == "key"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == key
                for keyword in call.keywords
            )
        )
        assert any(
            isinstance(node, ast.Constant) and node.value == field
            for node in ast.walk(description)
        )
