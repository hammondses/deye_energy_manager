"""Exercise the entity form with real voluptuous default validation."""

import ast
from pathlib import Path
from types import SimpleNamespace

import voluptuous as vol

from custom_components.deye_energy_manager.const import DEFAULT_ENTITY_MAP


def entity_schema(defaults):
    tree = ast.parse(Path("custom_components/deye_energy_manager/config_flow.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_entity_schema")

    def entity_id(value):
        # Match the relevant HA EntitySelector contract: a nonempty entity ID.
        if not isinstance(value, str) or "." not in value or not value.split(".", 1)[1]:
            raise vol.Invalid("Invalid entity ID")
        return value

    namespace = {
        "vol": vol,
        "selector": SimpleNamespace(EntitySelector=lambda: entity_id),
        "DEFAULT_ENTITY_MAP": DEFAULT_ENTITY_MAP,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "entity_schema", "exec"), namespace)
    return namespace["_entity_schema"](defaults)


def test_mapping_ev_power_does_not_validate_unmapped_optional_inputs():
    defaults = {**DEFAULT_ENTITY_MAP, "inverter_ac_temperature": "sensor.custom_ac_temperature"}
    result = entity_schema(defaults)({"ev_power": "sensor.evcharger_power_active_import"})
    assert result["ev_power"] == "sensor.evcharger_power_active_import"
    assert result["inverter_ac_temperature"] == "sensor.custom_ac_temperature"
    assert result["battery_soc"] == "sensor.deye_battery_soc"
    assert "outdoor_temperature" not in result
    assert "home_occupancy" not in result


def test_unconfigured_ev_power_is_optional_but_configured_mapping_is_preserved():
    assert "ev_power" not in entity_schema(DEFAULT_ENTITY_MAP)({})
    defaults = {**DEFAULT_ENTITY_MAP, "ev_power": "sensor.ev_power"}
    assert entity_schema(defaults)({})["ev_power"] == "sensor.ev_power"
