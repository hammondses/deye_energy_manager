"""Event-driven one-shot WiCAN Taycan SOC support."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any

WICAN_SOC_REQUEST = {
    "kind": "vehicle",
    "name": "SOC_D",
    "init": "ATST96;ATFCSD300000;ATFCSM1;",
    "pid_init": "ATSP6;ATCP18;ATSH744;ATFCSH744;ATFCSD300000;ATFCSM1;ATCRA7AE;",
    "pid": "221DD01",
    "expr": "B4/2",
}


def parse_wican_soc_response(data: object) -> tuple[float, str]:
    """Validate and return a WiCAN SOC_D response."""

    if not isinstance(data, dict) or data.get("ok") is not True:
        raise ValueError("WiCAN response was not successful")
    value = data.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("WiCAN SOC value was not numeric")
    soc = float(value)
    if not math.isfinite(soc) or not 0.0 <= soc <= 100.0:
        raise ValueError("WiCAN SOC value was outside 0..100")
    raw = data.get("raw")
    if not isinstance(raw, str) or not raw.strip() or "NO DATA" in raw.upper():
        raise ValueError("WiCAN SOC raw response was invalid")
    return soc, raw


def connector_connected(state: str | None) -> bool:
    """Return whether charger state indicates a cable-connected vehicle."""

    normalised = (state or "").strip().lower().replace("_", "").replace(" ", "")
    return normalised not in {"", "available", "disconnected", "notconnected", "unknown", "unavailable", "none"}


def charging_active(connector_state: str | None, current_a: float | None, power_w: float | None) -> bool:
    """Return whether charger telemetry indicates active charging."""

    normalised = (connector_state or "").strip().lower().replace("_", "").replace(" ", "")
    return normalised == "charging" or (current_a is not None and current_a > 0.5) or (power_w is not None and power_w > 300.0)


@dataclass(slots=True)
class WicanSocState:
    """Persisted SOC result and automatic-trigger state."""

    soc: float | None = None
    updated_at: datetime | None = None
    raw: str | None = None
    last_trigger: str = "none"
    last_result: str = "never queried"
    last_error: str | None = None
    last_success_energy_kwh: float | None = None
    energy_anchor_kwh: float | None = None
    last_energy_kwh: float | None = None
    connector_connected: bool | None = None
    charging_active: bool | None = None
    last_event_identity: str | None = None
    last_attempt_at: datetime | None = None

    @classmethod
    def restore(cls, data: object) -> WicanSocState:
        """Restore valid persisted values without producing a trigger."""

        if not isinstance(data, dict):
            return cls()
        state = cls()
        for field in ("soc", "last_success_energy_kwh", "energy_anchor_kwh", "last_energy_kwh"):
            value = data.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                setattr(state, field, float(value))
        updated = data.get("updated_at")
        if isinstance(updated, str):
            try:
                state.updated_at = datetime.fromisoformat(updated)
            except ValueError:
                pass
        attempted = data.get("last_attempt_at")
        if isinstance(attempted, str):
            try:
                state.last_attempt_at = datetime.fromisoformat(attempted)
            except ValueError:
                pass
        for field in ("raw", "last_trigger", "last_result", "last_error", "last_event_identity"):
            value = data.get(field)
            if field in data and (value is None or isinstance(value, str)):
                setattr(state, field, value)
        for field in ("connector_connected", "charging_active"):
            value = data.get(field)
            if isinstance(value, bool):
                setattr(state, field, value)
        if state.soc is not None and not 0.0 <= state.soc <= 100.0:
            state.soc = None
            state.updated_at = None
        return state

    def payload(self) -> dict[str, Any]:
        """Return JSON-safe persisted state."""

        return {
            "soc": self.soc,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "raw": self.raw,
            "last_trigger": self.last_trigger,
            "last_result": self.last_result,
            "last_error": self.last_error,
            "last_success_energy_kwh": self.last_success_energy_kwh,
            "energy_anchor_kwh": self.energy_anchor_kwh,
            "last_energy_kwh": self.last_energy_kwh,
            "connector_connected": self.connector_connected,
            "charging_active": self.charging_active,
            "last_event_identity": self.last_event_identity,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
        }

    def automatic_trigger(
        self,
        *,
        event_identity: str,
        connected: bool,
        charging: bool,
        energy_kwh: float | None,
        threshold_kwh: float,
        enabled: bool,
    ) -> str | None:
        """Observe one charger event and return at most one query trigger."""

        previous_connected = self.connector_connected
        previous_charging = self.charging_active
        duplicate = event_identity == self.last_event_identity
        self.connector_connected = connected
        self.charging_active = charging
        self.last_event_identity = event_identity

        valid_energy = energy_kwh is not None and math.isfinite(energy_kwh) and energy_kwh >= 0.0
        if valid_energy:
            if self.last_energy_kwh is not None and energy_kwh < self.last_energy_kwh:
                self.energy_anchor_kwh = energy_kwh
            self.last_energy_kwh = energy_kwh

        if not enabled or duplicate or not connected:
            return None
        if previous_connected is False and connected:
            return "connector_connected"
        if previous_charging is False and charging:
            return "charging_start"
        if previous_charging is True and not charging:
            return "charging_stop"
        if (
            valid_energy
            and self.energy_anchor_kwh is not None
            and energy_kwh >= self.energy_anchor_kwh + max(threshold_kwh, 0.1)
        ):
            return "energy_threshold"
        return None

    def record_success(self, soc: float, raw: str, now: datetime, trigger: str, energy_kwh: float | None) -> None:
        """Record one successful one-shot query."""

        self.soc = soc
        self.raw = raw
        self.updated_at = now
        self.last_trigger = trigger
        self.last_result = "success"
        self.last_error = None
        if energy_kwh is not None and math.isfinite(energy_kwh) and energy_kwh >= 0.0:
            self.last_success_energy_kwh = energy_kwh
            self.energy_anchor_kwh = energy_kwh
            self.last_energy_kwh = energy_kwh

    def record_failure(self, trigger: str, error: str, energy_kwh: float | None = None) -> None:
        """Record one failed request; callers must wait for a new event."""

        self.last_trigger = trigger
        self.last_result = "error"
        self.last_error = error
        if energy_kwh is not None and math.isfinite(energy_kwh) and energy_kwh >= 0.0:
            self.energy_anchor_kwh = energy_kwh
            self.last_energy_kwh = energy_kwh

    def energy_until_next_query(self, energy_kwh: float | None, threshold_kwh: float) -> float | None:
        """Return remaining session energy before the next automatic request."""

        if energy_kwh is None or self.energy_anchor_kwh is None or not math.isfinite(energy_kwh):
            return None
        if energy_kwh < self.energy_anchor_kwh:
            return max(threshold_kwh, 0.1)
        return max(self.energy_anchor_kwh + max(threshold_kwh, 0.1) - energy_kwh, 0.0)


def resolve_taycan_soc(
    local_soc: float | None,
    local_updated: datetime | None,
    cloud_soc: float | None,
    cloud_updated: datetime | None,
    now: datetime,
    fresh_minutes: float,
) -> tuple[float | None, str, float | None]:
    """Prefer fresh local SOC, then fresh cloud, then newest last-known-good."""

    samples: list[tuple[str, float, datetime, float]] = []
    for source, value, updated in (("wican", local_soc, local_updated), ("porsche_connect", cloud_soc, cloud_updated)):
        if value is None or updated is None or not math.isfinite(value) or not 0.0 <= value <= 100.0:
            continue
        age = max((now - updated).total_seconds() / 60.0, 0.0)
        samples.append((source, value, updated, age))
    local = next((sample for sample in samples if sample[0] == "wican"), None)
    if local and local[3] <= fresh_minutes:
        return local[1], local[0], local[3]
    cloud = next((sample for sample in samples if sample[0] == "porsche_connect"), None)
    if cloud and cloud[3] <= fresh_minutes and (local is None or cloud[2] >= local[2]):
        return cloud[1], cloud[0], cloud[3]
    if not samples:
        return None, "unavailable", None
    newest = max(samples, key=lambda sample: sample[2])
    return newest[1], f"{newest[0]}_last_known_good", newest[3]
