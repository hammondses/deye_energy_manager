"""The retired manager cannot restart a manually stopped bedroom."""
import ast
from pathlib import Path
import yaml


def test_bedroom_is_button_only_and_manager_has_no_night_actuator():
    config = yaml.safe_load(Path('docs/bedroom-night-heat.yaml').read_text())[0]
    assert config['triggers'] == [{'trigger': 'state', 'entity_id': 'input_button.bedroom_night_heat',
                                  'not_from': ['unknown', 'unavailable'], 'not_to': ['unknown', 'unavailable']}]
    assert config['conditions'] == [{'condition': 'template', 'value_template': '{{ trigger.from_state is not none }}'},
                                    {'condition': 'state', 'entity_id': 'climate.bedroom_heatpump', 'state': 'off'}]
    assert len(config['actions']) == 1
    assert config['actions'][0]['data'] == {'hvac_mode': 'heat', 'temperature': 17}
    source = Path('custom_components/deye_energy_manager/coordinator.py').read_text()
    names = {n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.AsyncFunctionDef)}
    assert not names & {'_apply_bedroom_night_heating', '_direct_set_bedroom_night_heating', 'async_set_bedroom_night_heating'}
    # Persisted old armed sessions must not survive upgrade.
    assert 'self.bedroom_night_heating_armed = bool' not in source
    assert 'BedroomNightHeatingSwitch' not in Path('custom_components/deye_energy_manager/switch.py').read_text()
