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
    ), EnergyManagerSettings(cooling_emergency_temp_c=48))
    assert result.recommended_pct == 100
    for temperature in [None, float('nan')]:
        result = inverter_cooling_recommendation(base_inputs(
            inverter_ac_temperature_c=temperature, cooling_temperature_valid=True, cooling_fan_percentage=97,
        ), EnergyManagerSettings())
        assert result.recommended_pct >= 97


def test_trend_includes_unchanged_reports_and_forgets_old_direction():
    sample = SimpleNamespace(state='42', last_reported=datetime.now(timezone.utc))
    c = SimpleNamespace(
        _temperature_reported_at=lambda state: state.last_reported,
        entity_map={'inverter_ac_temperature': 'sensor.temp'},
        hass=SimpleNamespace(states=SimpleNamespace(get=lambda _: sample)),
        settings=EnergyManagerSettings(),
        _cooling_samples=deque(maxlen=600), _cooling_temperature_sample=None,
        _cooling_temperature_trend_c_per_min=None, _cooling_internal_fan_recovery=False,
        _cooling_temperature_valid=lambda _: True, _schedule_runtime_save=Mock(), _record_event=Mock(),
    )
    read = coordinator_method('_cooling_temperature')
    assert read(c)[2] is None
    sample.last_reported += timedelta(seconds=15)
    sample.state = '42.3'
    assert read(c)[2] is None
    c.settings = replace(c.settings, cooling_trend_min_observation_s=15)
    assert round(read(c)[2], 2) == 1.2
    sample.last_reported += timedelta(seconds=15)
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
            _cooling_fan_health=lambda _: (True, 1000),
            _record_event=Mock(),
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


def test_tuning_uses_configured_thresholds_instead_of_hidden_caps():
    settings = EnergyManagerSettings(
        cooling_emergency_temp_c=52,
        cooling_recovery_trigger_temp_c=49,
        cooling_recovery_release_temp_c=46,
    )
    inputs = base_inputs(inverter_ac_temperature_c=48, cooling_temperature_valid=True, cooling_fan_percentage=30)
    assert inverter_cooling_recommendation(inputs, settings).recommended_pct < 100
    assert inverter_cooling_recommendation(replace(inputs, inverter_ac_temperature_c=52), settings).recommended_pct == 100
    assert cooling_recovery_state(False, 49, True, settings)
    assert cooling_recovery_state(True, 46.1, True, settings)
    assert not cooling_recovery_state(True, 46, True, settings)
    recovered = inverter_cooling_recommendation(replace(inputs, cooling_internal_fan_recovery=True), settings)
    assert '46C' in recovered.reason


def test_interval_changes_replace_only_the_cooling_timer():
    configure = coordinator_method('_configure_cooling_timer')
    cancel = Mock()
    register = Mock(return_value=cancel)
    configure.__globals__['async_track_time_interval'] = register
    c = SimpleNamespace(settings=EnergyManagerSettings(), hass=object(),
        _cooling_timer_cancel=None, _cooling_timer_interval=None, _async_update_cooling=AsyncMock())
    configure(c)
    assert register.call_args.args[2] == timedelta(seconds=5)
    configure(c)
    assert register.call_count == 1
    c.settings = replace(c.settings, cooling_update_interval_s=2)
    configure(c)
    cancel.assert_called_once()
    assert register.call_args.args[2] == timedelta(seconds=2)


def test_stale_timeout_can_change_live_and_uses_report_timestamp():
    valid = coordinator_method('_cooling_temperature_valid')
    now = datetime.now(timezone.utc)
    state = SimpleNamespace(state='45', last_reported=now-timedelta(seconds=40), last_updated=now-timedelta(hours=1))
    c = SimpleNamespace(_temperature_reported_at=lambda state: state.last_reported, settings=EnergyManagerSettings(), entity_map={'inverter_ac_temperature':'sensor.temp'},
        hass=SimpleNamespace(states=SimpleNamespace(get=lambda _: state)))
    assert valid(c, now)
    c.settings = replace(c.settings, cooling_temperature_stale_s=30)
    assert not valid(c, now)


def test_adaptive_hunt_step_scales_with_error_and_honours_live_cap():
    settings = EnergyManagerSettings(cooling_minimum_hunt_enabled=True, cooling_emergency_temp_c=55)
    for temp, trend, expected in [(45, .3, 41), (46.1, .3, 41), (46.5, .3, 43), (47, .3, 45), (48, .3, 50),
                                  (45, -.3, 39), (43.9, -.3, 39), (43.5, -.3, 37), (43, -.3, 35), (42, -.3, 30)]:
        inputs = base_inputs(inverter_ac_temperature_c=temp, cooling_temperature_valid=True,
                             cooling_fan_percentage=40, cooling_temperature_trend_c_per_min=trend)
        assert inverter_cooling_recommendation(inputs, settings).recommended_pct == expected
    settings = replace(settings, cooling_feedback_step_pct=3)
    assert inverter_cooling_recommendation(inputs, settings).recommended_pct == 37
    # A legacy cap above the new supported range cannot exceed ten points.
    settings = replace(settings, cooling_feedback_step_pct=20)
    assert inverter_cooling_recommendation(inputs, settings).recommended_pct == 30


def test_one_percent_writes_and_duplicate_or_older_samples_cannot_advance_hunt():
    async def run():
        stamp = datetime.now(timezone.utc)
        inputs = base_inputs(inverter_ac_temperature_c=44.1, cooling_temperature_valid=True,
                             cooling_temperature_sample_at=stamp, cooling_fan_percentage=30,
                             cooling_temperature_trend_c_per_min=.3)
        settings = EnergyManagerSettings(cooling_minimum_hunt_enabled=True, cooling_max_normal_fan_pct=100)
        current = 30
        async def service(domain, action, data, **kwargs):
            nonlocal current
            current = data['percentage']
        call = AsyncMock(side_effect=service)
        c = SimpleNamespace(settings=settings, _cooling_internal_fan_recovery=False,
            _cooling_fan_percentage=lambda: current, _cooling_temperature_valid=lambda _: True,
            _last_cooling_write_at=None, _last_cooling_feedback_sample_at=None,
            entity_map={'inverter_cooling_fan':'fan.external'}, _record_event=Mock(),
            hass=SimpleNamespace(states=SimpleNamespace(get=lambda _: SimpleNamespace(state='on')),
                                 services=SimpleNamespace(async_call=call)))
        apply = coordinator_method('_apply_inverter_cooling')
        decision = decide(inputs, settings)
        await apply(c, decision)
        assert current == 31
        for sample in [stamp, stamp-timedelta(seconds=15)]:
            for load_change in [0, 2000, -2000]:
                repeated = replace(decision, cooling_recommended_fan_pct=32,
                                   cooling_temperature_sample_at=sample, cooling_load_change_w=load_change)
                await apply(c, repeated)
                await apply(c, replace(repeated, cooling_recommended_fan_pct=30))
        assert call.await_count == 1
        # Normal control reaching 100 is not itself an emergency exemption.
        await apply(c, replace(decision, cooling_recommended_fan_pct=100))
        assert call.await_count == 1
        await apply(c, replace(decision, cooling_recommended_fan_pct=32,
                               cooling_temperature_sample_at=stamp+timedelta(seconds=15)))
        assert current == 32
        # Genuine safety still acts immediately on an already-consumed report.
        await apply(c, replace(decision, inverter_ac_temperature_c=48, cooling_recommended_fan_pct=100))
        assert current == 100
    asyncio.run(run())
