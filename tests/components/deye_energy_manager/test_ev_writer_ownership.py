"""Daytime EV writer ownership gates only automatic charger writes."""

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from custom_components.deye_energy_manager.const import (
    DEFAULT_DAYTIME_EV_WRITER,
    DAYTIME_EV_WRITER_OPTIONS,
)
from custom_components.deye_energy_manager.models import EnergyManagerDecision, EnergyManagerSettings


TZ = ZoneInfo("Pacific/Auckland")


@pytest.mark.parametrize(
    ("writer", "hour", "manual", "action", "expected_service"),
    [
        ("manager", 14, False, "ev_charger_start", "script"),
        ("manager", 14, False, "ev_charger_stop", "switch"),
        ("external_automation", 14, False, "ev_charger_start", None),
        ("external_automation", 14, False, "ev_charger_stop", None),
        ("external_automation", 7, False, "ev_charger_stop", None),
        ("external_automation", 21, False, "ev_charger_stop", "switch"),
        ("external_automation", 22, False, "ev_charger_start", "script"),
        ("external_automation", 22, False, "ev_charger_stop", "switch"),
        ("external_automation", 14, True, "ev_charger_start", "script"),
        ("external_automation", 14, True, "ev_charger_stop", "switch"),
    ],
)
def test_daytime_writer_only_suppresses_nonmanual_daytime_charger_writes(
    writer, hour, manual, action, expected_service
):
    source = Path("custom_components/deye_energy_manager/coordinator.py").read_text()
    tree = ast.parse(source)
    ownership_helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_manager_owns_automatic_ev_charger"
    )
    apply_method = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_apply_decision"
    )
    isolated = ast.Module(body=[ownership_helper, apply_method], type_ignores=[])
    namespace = {
        "asyncio": asyncio,
        "datetime": datetime,
        "timedelta": timedelta,
        "EnergyManagerSettings": EnergyManagerSettings,
        "EnergyManagerDecision": EnergyManagerDecision,
        "dt_util": SimpleNamespace(utcnow=lambda: datetime.now(timezone.utc)),
        "build_deye_plan": lambda *_args: "plan",
    }
    exec(compile(isolated, "coordinator_ev_apply_test", "exec"), namespace)

    async def run():
        writes = []
        started_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        settings = EnergyManagerSettings(
            ev_control_enabled=True,
            daytime_ev_writer=writer,
        )
        decision = SimpleNamespace(
            now=datetime(2026, 10, 3, hour, 30, tzinfo=TZ),
            control_blocked=False,
            cooling_inverter_protection_required=False,
            ev_expected_action=action,
            ev_decision_reason="test EV action",
            ev_soc_cutoff_reached=False,
        )
        coordinator = SimpleNamespace(
            _apply_lock=asyncio.Lock(),
            data=decision,
            started_at=started_at,
            settings=settings,
            ev_manual_charging_override=manual,
            cooling_inverter_protection_active=False,
            inverter_cooling_protection_active=False,
            last_control_action=None,
            entity_map={},
        )

        async def call_script(entity_id, *, reason=""):
            writes.append(("script", entity_id))

        async def call_switch(entity_id, on, *, reason="", emergency=False, force=False):
            writes.append(("switch", entity_id, on))

        async def apply_deye_plan(plan, *, force=False, override_gates=False):
            writes.append(("deye_plan", plan))

        coordinator._call_script = call_script
        coordinator._call_switch = call_switch
        coordinator._apply_deye_plan = apply_deye_plan
        await namespace["async_apply_decision"](coordinator, decision)

        ev_writes = [row for row in writes if row[0] in {"script", "switch"}]
        assert (ev_writes[0][0] if ev_writes else None) == expected_service
        # The writer select does not gate Deye bypass/programme-plan updates.
        assert any(row[0] == "deye_plan" for row in writes)

    asyncio.run(run())


def test_daytime_ev_writer_has_manager_default_and_external_option():
    assert DEFAULT_DAYTIME_EV_WRITER == "manager"
    assert DAYTIME_EV_WRITER_OPTIONS == ["manager", "external_automation"]
