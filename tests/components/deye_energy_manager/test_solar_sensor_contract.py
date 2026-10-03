"""Check the HA sensor boundary used by the separate EV automation."""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.deye_energy_manager.solar_advisory import SolarAdvisory


def _expected_charge_sensor():
    # Evaluate the real description and value helper without an HA runtime.
    tree = ast.parse(Path("custom_components/deye_energy_manager/sensor.py").read_text())
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_solar_plan_value")
    description = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "DeyeSensorDescription"
        and any(keyword.arg == "key" and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == "solar_plan_expected_battery_dc_power"
                for keyword in node.keywords)
    )
    namespace = {
        "Any": Any,
        "EnergyManagerDecision": SimpleNamespace,
        "DeyeSensorDescription": SimpleNamespace,
        "UnitOfPower": SimpleNamespace(KILO_WATT="kW"),
        "SensorStateClass": SimpleNamespace(MEASUREMENT="measurement"),
    }
    exec(compile(ast.Module(body=[helper], type_ignores=[]), "sensor_helper", "exec"), namespace)
    return eval(compile(ast.Expression(description), "sensor_description", "eval"), namespace)


@pytest.mark.parametrize("valid", [True, False])
def test_expected_charge_exposes_accepted_average_not_command_ceiling(valid):
    sensor = _expected_charge_sensor()
    plan = SolarAdvisory(valid=valid, recommended_battery_dc_kw=13.5,
                        recommended_battery_expected_average_dc_kw=3.2)
    assert sensor.native_unit_of_measurement == "kW"
    assert sensor.value_fn(SimpleNamespace(solar_plan=plan)) == (3.2 if valid else None)


def test_disabled_plan_does_not_publish_zero_as_a_valid_charge_expectation():
    assert _expected_charge_sensor().value_fn(SimpleNamespace(solar_plan=None)) is None
