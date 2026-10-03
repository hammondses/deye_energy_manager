#!/usr/bin/env python3
"""Offline preview from a bounded HA snapshot; never connects to HA or actuators.

The snapshot contains now, sunset, latitude, longitude, forecast (Solcast bins),
and states [{entity_id, state, unit, last_reported}]. A charge curve must be
supplied explicitly. Output names assumptions so a preview is not mistaken for
validated live control. Run from the repository root.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_components.deye_energy_manager.const import DEFAULT_ENTITY_MAP
from custom_components.deye_energy_manager.decision import decide
from custom_components.deye_energy_manager.models import EnergyManagerInputs, EnergyManagerSettings
from custom_components.deye_energy_manager.solar_advisory_adapter import build_daytime_advisory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--curve', required=True, help='Assumed SOC-fraction/DC-kW JSON pairs')
    parser.add_argument('--forecast-weight', type=float, default=0)
    parser.add_argument('--safety-buffer', type=float, default=2)
    parser.add_argument('--committed-load', type=float, default=0)
    args = parser.parse_args()
    raw = json.loads(args.snapshot.read_text())
    states = {
        row['entity_id']: SimpleNamespace(
            state=row['state'], attributes={'unit_of_measurement': row['unit']},
            last_reported=datetime.fromisoformat(row['last_reported']),
        ) for row in raw['states']
    }
    def value(entity):
        return float(states[entity].state)
    prefix = 'garage_deye_energy_manager_'
    def number(key):
        return value('number.' + prefix + key)
    def sensor(key):
        return value('sensor.' + prefix + key)
    def switch(key):
        return states['switch.' + prefix + key].state == 'on'
    states['sun.sun'].attributes['next_setting'] = raw['sunset']
    states[DEFAULT_ENTITY_MAP['forecast_today']].attributes['detailedForecast'] = raw['forecast']
    entity_map = {**DEFAULT_ENTITY_MAP, 'ev_power': 'sensor.evcharger_power_active_import',
                  'inverter_pv_power': 'sensor.deye_pv_power'}
    settings = EnergyManagerSettings(
        battery_capacity_kwh=number('battery_capacity'),
        daily_battery_target_soc=number('daily_battery_target_soc'),
        battery_charge_efficiency=number('battery_charge_efficiency'),
        forecast_safety_buffer_kwh=args.safety_buffer,
        house_load_forecast_buffer_kwh=number('house_load_forecast_buffer'),
        ev_solar_charging_enabled=switch('ev_solar_charging_enabled'),
    )
    inputs = EnergyManagerInputs(
        now=datetime.fromisoformat(raw['now']), battery_soc=value('sensor.deye_battery_soc'),
        base_load_estimate_w=sensor('base_load_estimate'),
        porsche_soc=sensor('effective_taycan_soc'),
        ev_charge_requested=states['switch.evcharger_charge_control'].state == 'on',
        ev_connector_status=states['sensor.evcharger_status_connector'].state,
        ev_manual_charging_override=switch('ev_manual_charging_override'),
    )
    decision = decide(inputs, settings)
    decision.active_reserve_target_soc = sensor('active_reserve_target_soc')
    decision.committed_flexible_load_energy_kwh = args.committed_load
    plan = build_daytime_advisory(
        inputs, settings, decision, states=states, entity_map=entity_map,
        latitude=raw['latitude'], longitude=raw['longitude'], options={
            'daytime_plan_enabled': True,
            'solar_plan_charge_acceptance_curve': args.curve,
            'solar_plan_forecast_risk_blend': args.forecast_weight,
        },
    )
    report = asdict(plan)
    report.pop('physical_scenario_soc_trajectory')
    report.pop('physical_scenario_boundary_times')
    report['assumptions'] = {
        'charge_curve': json.loads(args.curve), 'forecast_weight': args.forecast_weight,
        'safety_buffer_kwh': args.safety_buffer, 'committed_load_kwh': args.committed_load,
        'remaining_electrical_and_array_settings': 'integration defaults',
        'PV_source': 'sensor.deye_pv_power; explicit diagnostic override',
        'EV_power_source': 'native OCPP kW; packet-level freshness not proven',
        'live_control': False,
    }
    print(json.dumps(report, default=str, indent=2))


if __name__ == '__main__':
    main()
