#!/usr/bin/env python3
"""Replay deterministic, synthetic daytime cases through the pure advisory.

This is an offline algorithm smoke check, not HA integration testing or a
year-round energy-yield estimate. See docs/daytime-scenario-replay.md for the
model boundary and assumptions. Run from any directory with Python and the
repository source available.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.deye_energy_manager.solar_advisory import (  # noqa: E402
    SolarAdvisoryInput,
    recommend_solar_action,
)
from custom_components.deye_energy_manager.solar_forecast import (  # noqa: E402
    SolarForecast,
    SolarForecastInterval,
)


@dataclass(frozen=True)
class Scenario:
    name: str
    daylight_hours: int
    peak_pv_dc_kw: float
    initial_soc_pct: float
    expected_reachable: bool


SCENARIOS = (
    Scenario("short_low_solar", 8, 8.0, 60.0, True),
    Scenario("long_high_solar", 12, 16.5, 30.0, True),
    Scenario("medium_solar", 10, 12.0, 40.0, True),
    Scenario("target_unreachable", 4, 1.0, 20.0, False),
)


@dataclass(frozen=True)
class ReplayResult:
    scenario: str
    target_reachable_at_start: bool
    ever_target_reachable: bool
    target_physically_reached: bool
    max_soc_pct: float
    end_soc_pct: float
    ev_energy_kwh: float
    estimated_clipped_energy_kwh: float
    house_grid_import_kwh: float


def _forecast(now: datetime, powers_dc_kw: list[float]) -> SolarForecast:
    intervals = tuple(
        SolarForecastInterval(
            start=now + timedelta(minutes=index * 5),
            end=now + timedelta(minutes=(index + 1) * 5),
            pv_estimate10_kw=power * 0.96,
            pv_estimate_kw=power * 0.96,
            pv_estimate90_kw=power * 0.96,
        )
        for index, power in enumerate(powers_dc_kw)
    )
    return SolarForecast(
        source_updated_at=now,
        start=now,
        deadline=intervals[-1].end,
        intervals=intervals,
    )


def replay(scenario: Scenario) -> ReplayResult:
    """Run one receding-horizon advisory and simple power-balance replay."""

    count = scenario.daylight_hours * 12
    start = datetime(2026, 1, 15, 7, tzinfo=timezone.utc)
    powers_dc_kw = [
        scenario.peak_pv_dc_kw * math.sin(math.pi * (index + 0.5) / count)
        for index in range(count)
    ]

    stored_kwh = 32.0 * scenario.initial_soc_pct / 100.0
    max_stored_kwh = stored_kwh
    clipped_kwh = 0.0
    ev_kwh = 0.0
    house_grid_import_kwh = 0.0
    ever_reachable = False
    reachable_at_start = False

    for index, pv_dc_kw in enumerate(powers_dc_kw):
        now = start + timedelta(minutes=index * 5)
        remaining_power = powers_dc_kw[index:]
        plan = recommend_solar_action(
            SolarAdvisoryInput(
                forecast=_forecast(now, remaining_power),
                now=now,
                current_soc_pct=stored_kwh / 32.0 * 100.0,
                capacity_kwh=32.0,
                target_soc_pct=100.0,
                reserve_energy_kwh=3.2,
                non_ev_base_house_kw=1.6,
                current_non_ev_house_kw=1.6,
                live_pv_dc_kw=pv_dc_kw,
                voltage_v=240.0,
                live_bms_max_dc_kw=13.5,
                max_battery_dc_kw=13.5,
                max_discharge_dc_kw=13.5,
                soc_charge_curve=((0.0, 13.5),),
                site_ac_limit_kw=13.5,
                inverter_ac_limit_kw=12.0,
                export_limit_kw=10.0,
                battery_charge_efficiency=0.94,
                battery_discharge_efficiency=0.94,
                inverter_efficiency=0.96,
                safety_buffer_kwh=0.0,
                max_ev_amps=32,
                ev_allowed=True,
                forecast_p50_weight=0.0,
                physical_dc_upper_kw=tuple(remaining_power),
                clipping_envelope_dc_kw=tuple(remaining_power),
            )
        )
        if not plan.valid:
            raise RuntimeError(f"{scenario.name}: advisory invalid at step {index}: {plan.reason}")
        if plan.recommended_ev_amps != 0 and not 6 <= plan.recommended_ev_amps <= 32:
            raise AssertionError(
                f"{scenario.name}: EV recommendation outside 0 or 6..32 A: "
                f"{plan.recommended_ev_amps}"
            )

        if index == 0:
            reachable_at_start = plan.target_reachable
        ever_reachable |= plan.target_reachable

        # Independent 5-minute power-balance approximation: EV and house take
        # AC first; accepted battery DC is then capped by the advisory request,
        # available PV, BMS limit and remaining capacity. Export uses remaining
        # AC headroom, with the rest classed as DC clipping.
        ev_kw = plan.recommended_ev_amps * 0.24
        house_pv_ac_kw = min(1.6, pv_dc_kw * 0.96)
        if ev_kw and pv_dc_kw * 0.96 + 1e-9 < house_pv_ac_kw + ev_kw:
            raise AssertionError(
                f"{scenario.name}: advisory EV current exceeds live solar support"
            )
        pv_after_ac_load_kw = max(
            pv_dc_kw - house_pv_ac_kw / 0.96 - ev_kw / 0.96,
            0.0,
        )
        accepted_battery_dc_kw = min(
            plan.recommended_battery_dc_kw,
            pv_after_ac_load_kw,
            13.5,
            max(32.0 - stored_kwh, 0.0) * 12.0 / 0.94,
        )
        export_kw = min(
            10.0,
            max(12.0 - house_pv_ac_kw - ev_kw, 0.0),
            max(pv_after_ac_load_kw - accepted_battery_dc_kw, 0.0) * 0.96,
        )
        clipped_kwh += max(
            pv_after_ac_load_kw - accepted_battery_dc_kw - export_kw / 0.96,
            0.0,
        ) / 12.0
        stored_kwh += accepted_battery_dc_kw * 0.94 / 12.0

        # House-load shortfalls draw down the home battery to a 10% reserve;
        # EV energy is never supplied by battery in this simplified replay.
        house_deficit_kw = max(1.6 - house_pv_ac_kw, 0.0)
        stored_before_house_discharge_kwh = stored_kwh
        requested_house_discharge_kwh = house_deficit_kw / (0.94 * 0.96 * 12.0)
        stored_kwh = max(3.2, stored_kwh - requested_house_discharge_kwh)
        actual_house_discharge_kwh = stored_before_house_discharge_kwh - stored_kwh
        house_served_by_battery_kwh = actual_house_discharge_kwh * 0.94 * 0.96
        house_grid_import_kwh += max(
            house_deficit_kw / 12.0 - house_served_by_battery_kwh,
            0.0,
        )
        ev_kwh += ev_kw / 12.0
        max_stored_kwh = max(max_stored_kwh, stored_kwh)

    max_soc_pct = max_stored_kwh / 32.0 * 100.0
    target_physically_reached = max_soc_pct >= 100.0 - 1e-9
    if target_physically_reached != scenario.expected_reachable:
        raise AssertionError(
            f"{scenario.name}: expected physical target reached="
            f"{scenario.expected_reachable}, got {target_physically_reached}"
        )
    if scenario.expected_reachable and clipped_kwh > 1e-9:
        raise AssertionError(
            f"{scenario.name}: expected no residual clipping, got {clipped_kwh:.6f} kWh"
        )
    if not scenario.expected_reachable and ev_kwh > 1e-9:
        raise AssertionError(
            f"{scenario.name}: unreachable case unexpectedly allocated {ev_kwh:.6f} kWh to EV"
        )
    if scenario.name == "target_unreachable" and house_grid_import_kwh <= 0:
        raise AssertionError("target_unreachable: expected house grid import after reserve binds")
    return ReplayResult(
        scenario=scenario.name,
        target_reachable_at_start=reachable_at_start,
        ever_target_reachable=ever_reachable,
        target_physically_reached=target_physically_reached,
        max_soc_pct=max_soc_pct,
        end_soc_pct=stored_kwh / 32.0 * 100.0,
        ev_energy_kwh=ev_kwh,
        estimated_clipped_energy_kwh=clipped_kwh,
        house_grid_import_kwh=house_grid_import_kwh,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument(
        "--case",
        action="append",
        choices=[scenario.name for scenario in SCENARIOS],
        help="run selected case(s); repeat the flag; default is all cases",
    )
    args = parser.parse_args()
    selected = set(args.case or ())
    scenarios = [s for s in SCENARIOS if not selected or s.name in selected]
    results = [replay(scenario) for scenario in scenarios]

    for scenario, result in zip(scenarios, results, strict=True):
        if result.ever_target_reachable != scenario.expected_reachable:
            raise AssertionError(
                f"{scenario.name}: expected ever_target_reachable="
                f"{scenario.expected_reachable}, got {result.ever_target_reachable}"
            )

    if args.json:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        print("scenario              feasible(start/ever) actual100?  maxSOC  endSOC  EV kWh  clipped kWh  house grid kWh")
        for result in results:
            print(
                f"{result.scenario:21} "
                f"{str(result.target_reachable_at_start):>5}/{str(result.ever_target_reachable):<5} "
                f"{str(result.target_physically_reached):>9} "
                f"{result.max_soc_pct:6.2f}% "
                f"{result.end_soc_pct:6.2f}% "
                f"{result.ev_energy_kwh:7.2f} "
                f"{result.estimated_clipped_energy_kwh:11.3f} "
                f"{result.house_grid_import_kwh:14.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
