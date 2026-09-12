"""Exercise cooling trajectories and the actual coordinator methods without HA."""

import ast
import asyncio
from collections import deque
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from custom_components.deye_energy_manager.decision import (
    cooling_load_collapsed, cooling_recovery_state, decide, inverter_cooling_recommendation,
)
from custom_components.deye_energy_manager.models import EnergyManagerSettings
from test_decision import base_inputs


def coordinator_method(name):
    tree = ast.parse(Path('custom_components/deye_energy_manager/coordinator.py').read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    node.decorator_list = []
    namespace = dict(
        datetime=datetime, timedelta=timedelta, replace=replace, isfinite=isfinite,
        cooling_recovery_state=cooling_recovery_state, cooling_load_collapsed=cooling_load_collapsed,
        inverter_cooling_recommendation=inverter_cooling_recommendation,
        UNAVAILABLE={'unknown', 'unavailable', None},
        dt_util=SimpleNamespace(now=lambda: datetime.now(timezone.utc), utcnow=lambda: datetime.now(timezone.utc)),
    )
    exec(compile('from __future__ import annotations\n' + ast.unparse(node), '<coordinator>', 'exec'), namespace)
    return namespace[name]


def test_recovery_and_missing_temperature_never_release_hot_internal_fans():
    active = False
    for temperature, expected in [(49, False), (50, True), (49, True), (45, True), (44.9, True), (44.1, True), (None, True), (44, False)]:
        active = cooling_recovery_state(active, temperature, temperature is not None)
        assert active is expected
        if active:
            result = inverter_cooling_recommendation(base_inputs(
                inverter_ac_temperature_c=temperature, cooling_temperature_valid=temperature is not None,
                cooling_internal_fan_recovery=active, cooling_fan_percentage=70,
            ), EnergyManagerSettings())
            assert result.recommended_pct == 100
    assert cooling_recovery_state(True, 30, False)
    assert cooling_recovery_state(True, float('nan'), True)
    result = inverter_cooling_recommendation(base_inputs(
        inverter_ac_temperature_c=48, cooling_temperature_valid=True, cooling_fan_percentage=30,
    ), EnergyManagerSettings(cooling_emergency_temp_c=52))
    assert result.recommended_pct == 100
    for temperature in [None, float('nan')]:
        result = inverter_cooling_recommendation(base_inputs(
            inverter_ac_temperature_c=temperature, cooling_temperature_valid=True, cooling_fan_percentage=97,
        ), EnergyManagerSettings())
        assert result.recommended_pct >= 97


def test_trend_includes_unchanged_reports_and_forgets_old_direction():
    sample = SimpleNamespace(state='42', last_reported=datetime.now(timezone.utc))
    c = SimpleNamespace(
        entity_map={'inverter_ac_temperature': 'sensor.temp'},
        hass=SimpleNamespace(states=SimpleNamespace(get=lambda _: sample)),
        _cooling_samples=deque(maxlen=120), _cooling_temperature_sample=None,
        _cooling_temperature_trend_c_per_min=None, _cooling_internal_fan_recovery=False,
        _cooling_temperature_valid=lambda _: True, _schedule_runtime_save=Mock(),
    )
    read = coordinator_method('_cooling_temperature')
    assert read(c)[2] is None
    sample.last_reported += timedelta(seconds=30)
    sample.state = '42.3'
    assert round(read(c)[2], 2) == 0.6
    for _ in range(4):
        sample.last_reported += timedelta(seconds=15)
        read(c)
    assert read(c)[2] == 0
    sample.last_reported += timedelta(minutes=2)
    sample.state = '43'
    assert read(c)[2] is None


def test_fast_loop_only_writes_fans_and_repeated_samples_do_not_step_again():
    async def run():
        inputs = base_inputs(inverter_ac_temperature_c=46, cooling_temperature_valid=True)
        sample_at = datetime.now(timezone.utc)
        service = AsyncMock()
        c = SimpleNamespace(
            data=decide(inputs), _cooling_inputs_snapshot=inputs, _apply_lock=asyncio.Lock(),
            settings=EnergyManagerSettings(inverter_cooling_control_enabled=True),
            _cooling_internal_fan_recovery=False,
            _cooling_temperature=lambda: (46, sample_at, 0.5),
            _cooling_temperature_valid=lambda _: True,
            _cooling_fan_percentage=lambda: 20,
            _state_float=lambda _: 5000,
            async_update_listeners=Mock(),
            entity_map={'inverter_cooling_fan': 'fan.external'},
            hass=SimpleNamespace(states=SimpleNamespace(get=lambda _: SimpleNamespace(state='on')), services=SimpleNamespace(async_call=service)),
            _last_cooling_write_at=None, _last_cooling_feedback_sample_at=None,
        )
        apply = coordinator_method('_apply_inverter_cooling')
        c._apply_inverter_cooling = lambda decision: apply(c, decision)
        update = coordinator_method('_async_update_cooling')
        await update(c, sample_at)
        assert service.await_count == 1
        assert service.call_args.args[:2] == ('fan', 'set_percentage')
        await update(c, sample_at)
        assert service.await_count == 1
        # Safety increase is not starved by the already-consumed sample.
        c._cooling_internal_fan_recovery = True
        await update(c, sample_at)
        assert service.call_args.args[2]['percentage'] == 100
        c.settings = replace(c.settings, inverter_cooling_control_enabled=False)
        count = service.await_count
        await update(c, sample_at)
        assert service.await_count == count
    asyncio.run(run())
