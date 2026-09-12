"""Behavior checks for observations, presets, and transition-only history."""
import asyncio
import ast
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from custom_components.deye_energy_manager.const import DOMAIN, NUMBER_DEFAULTS
from custom_components.deye_energy_manager.decision import decide
from custom_components.deye_energy_manager.models import EnergyManagerSettings
from test_cooling_response import coordinator_method
from test_decision import base_inputs


def test_manual_fan_marker_captures_both_channel_times_and_load():
    mark = coordinator_method('record_internal_fan_observation')
    state = SimpleNamespace(last_reported=datetime.now(timezone.utc))
    values = {'inverter_ac_temperature':44.1,'inverter_dc_temperature':39.2,'inverter_pv_power':5400}
    event = Mock()
    c = SimpleNamespace(entity_map={'inverter_ac_temperature':'sensor.ac','inverter_dc_temperature':'sensor.dc'},
        hass=SimpleNamespace(states=SimpleNamespace(get=lambda _:state)), _state_float=values.get,
        _cooling_fan_percentage=lambda:50, _record_event=event, async_update_listeners=Mock())
    mark(c, 'stopped')
    args = event.call_args.kwargs
    assert args['source']=='manual' and args['observed']=='stopped'
    assert args['ac_temperature_c']==44.1 and args['dc_temperature_c']==39.2
    assert args['ac_reported_at']==state.last_reported.isoformat()
    assert args['pv_power_w']==5400


def test_saved_tuning_restore_is_atomic_and_cannot_enable_actuator_gates():
    save = coordinator_method('save_cooling_preset')
    save.__globals__['NUMBER_DEFAULTS'] = NUMBER_DEFAULTS
    restore = coordinator_method('async_restore_cooling_preset')
    restore.__globals__['NUMBER_DEFAULTS'] = NUMBER_DEFAULTS
    restore.__globals__['HomeAssistantError'] = ValueError
    update = Mock()
    c = SimpleNamespace(settings=EnergyManagerSettings(cooling_target_temp_c=43.2),
        cooling_saved_preset={}, entry=SimpleNamespace(options={'deye_control_enabled':False}),
        hass=SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update)),
        _record_event=Mock(), async_update_listeners=Mock(), async_request_refresh=AsyncMock())
    save(c)
    assert c.cooling_saved_preset['values']['cooling_target_temp_c']==43.2
    assert 'inverter_cooling_control_enabled' not in c.cooling_saved_preset['values']
    c.cooling_saved_preset['values']['deye_control_enabled'] = True
    asyncio.run(restore(c))
    update.assert_called_once()
    assert update.call_args.kwargs['options']['cooling_target_temp_c']==43.2
    assert update.call_args.kwargs['options']['deye_control_enabled'] is False
    c.cooling_saved_preset = {}
    try:
        asyncio.run(restore(c))
    except ValueError:
        pass
    else:
        raise AssertionError('Empty preset must not silently reset settings')


def test_identical_decision_does_not_append_timestamp_or_numeric_reason_churn():
    record = coordinator_method('_append_proposed_action')
    c = SimpleNamespace(recent_proposed_actions=deque(maxlen=10),settings=EnergyManagerSettings(),
        _would_actuate=lambda _:False, _blocked_reason=lambda _:None, _record_event=Mock())
    first = decide(base_inputs())
    record(c, first)
    record(c, replace(first, reason='Same decision with newly measured watts'))
    assert len(c.recent_proposed_actions)==1
    c._record_event.assert_called_once()
    record(c, replace(first, tariff_window='changed_tariff'))
    assert len(c.recent_proposed_actions)==2


def test_timeline_is_bounded_and_restore_preserves_manual_observations_and_preset():
    record = coordinator_method('_record_event')
    record.__globals__['DOMAIN']=DOMAIN
    c = SimpleNamespace(decision_timeline=deque(maxlen=50),entry=SimpleNamespace(entry_id='test'),
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=Mock())),_schedule_runtime_save=Mock())
    for i in range(60): record(c,'internal_fan_observation',str(i),source='manual')
    assert len(c.decision_timeline)==50 and c.decision_timeline[0]['message']=='10'
    saved={'decision_timeline':list(c.decision_timeline),'cooling_saved_preset':{'values':{'cooling_target_temp_c':44}}}
    loaded=SimpleNamespace(_thermal_store=SimpleNamespace(async_load=AsyncMock(return_value=saved)),
        _datetime_map=lambda _: {}, decision_timeline=deque(maxlen=50))
    asyncio.run(coordinator_method('async_load_stored_runtime')(loaded))
    assert len(loaded.decision_timeline)==50
    assert loaded.cooling_saved_preset==saved['cooling_saved_preset']


def test_options_flow_constructor_supports_read_only_config_entry():
    tree=ast.parse(Path('custom_components/deye_energy_manager/config_flow.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='OptionsFlowHandler')
    init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    ns={}
    exec(compile('from __future__ import annotations\n'+ast.unparse(init),'<options flow>','exec'),ns)
    class Flow:
        config_entry=property(lambda _:None)
    flow=Flow()
    ns['__init__'](flow,SimpleNamespace(options={'cooling_target_temp_c':45}))
    assert flow._options['cooling_target_temp_c']==45
