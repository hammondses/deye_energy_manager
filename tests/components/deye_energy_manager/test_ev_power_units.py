"""Exercise the actual coordinator reader without requiring an HA runtime."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.deye_energy_manager.decision import resolved_ev_power_w


@pytest.mark.parametrize(("unit", "value", "expected"), [
    ("kW", 4.84, 4840), ("W", 4840, 4840),
    ("MW", 4.84, None), (None, 4.84, None), ("kW", None, None),
])
def test_ev_power_reader_normalizes_before_house_load_subtraction(unit, value, expected):
    tree = ast.parse(Path("custom_components/deye_energy_manager/coordinator.py").read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_state_float")
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "ev_power_reader", "exec"), namespace)
    coordinator = SimpleNamespace(
        entity_map={"ev_power": "sensor.charger_power", "battery_soc": "sensor.soc"},
        _entity_float=lambda _: value,
        hass=SimpleNamespace(states={"sensor.charger_power": SimpleNamespace(
            attributes={"unit_of_measurement": unit})}),
    )
    measured = namespace["_state_float"](coordinator, "ev_power")
    assert measured == expected
    # A bad or unavailable measured channel falls back to charger amps/volts.
    actual = resolved_ev_power_w(measured, 20, 242)
    assert actual == pytest.approx(4840)
    assert 6440 - actual == pytest.approx(1600)
    # Other readers retain their existing numeric semantics.
    assert namespace["_state_float"](coordinator, "battery_soc") == value
