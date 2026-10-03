"""Parse detailed PV forecasts into validated, short solar intervals.

The values in this module retain the Solcast forecast's PV-output meaning. They
are not classified as DC input, AC output, clipped energy, or battery energy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

SOURCE_BIN_DURATION = timedelta(minutes=30)
MAX_INTERVAL_DURATION = timedelta(minutes=5)
_PV_FIELDS = ("pv_estimate10", "pv_estimate", "pv_estimate90")


class SolarForecastError(ValueError):
    """Raised when a detailed forecast is stale, malformed, or incomplete."""


@dataclass(frozen=True, slots=True)
class SolarForecastInterval:
    """A clipped and subdivided interval with forecast PV output in kW."""

    start: datetime
    end: datetime
    pv_estimate10_kw: float
    pv_estimate_kw: float
    pv_estimate90_kw: float

    @property
    def duration_hours(self) -> float:
        """Return the interval duration using elapsed, timezone-aware seconds."""

        return (self.end - self.start).total_seconds() / 3600.0

    def energy_kwh(self, estimate: str = "pv_estimate") -> float:
        """Return forecast PV energy for one of the three Solcast estimates."""

        if estimate == "pv_estimate10":
            power_kw = self.pv_estimate10_kw
        elif estimate == "pv_estimate":
            power_kw = self.pv_estimate_kw
        elif estimate == "pv_estimate90":
            power_kw = self.pv_estimate90_kw
        else:
            raise ValueError(f"unknown PV estimate: {estimate}")
        return power_kw * self.duration_hours


@dataclass(frozen=True, slots=True)
class SolarForecast:
    """Validated forecast coverage and its bounded PV-output intervals."""

    source_updated_at: datetime
    start: datetime
    deadline: datetime
    intervals: tuple[SolarForecastInterval, ...]

    def energy_kwh(self, estimate: str = "pv_estimate") -> float:
        """Sum the PV-output energy for one Solcast estimate across the horizon."""

        return sum(interval.energy_kwh(estimate) for interval in self.intervals)


def parse_detailed_forecast(
    detailed_forecast: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    deadline: datetime,
    source_updated_at: datetime,
    max_age: timedelta,
) -> SolarForecast:
    """Validate and subdivide 30-minute detailed forecast bins.

    Bins are interpreted as constant average PV output in kW over their actual
    30-minute elapsed duration. The requested horizon is clipped to ``now`` and
    ``deadline``; values are then subdivided into intervals no longer than five
    minutes without changing their energy. Missing coverage is rejected rather
    than treated as zero forecast.
    """

    now_utc = _as_utc(now, "now")
    deadline_utc = _as_utc(deadline, "deadline")
    updated_utc = _as_utc(source_updated_at, "source_updated_at")
    if deadline_utc <= now_utc:
        raise SolarForecastError("deadline must be after now")
    if not isinstance(max_age, timedelta) or max_age < timedelta(0):
        raise SolarForecastError("max_age must be a non-negative timedelta")
    age = now_utc - updated_utc
    if age < timedelta(0):
        raise SolarForecastError("forecast source timestamp is in the future")
    if age > max_age:
        raise SolarForecastError("forecast source timestamp is stale")
    if not isinstance(detailed_forecast, Sequence) or isinstance(detailed_forecast, (str, bytes)):
        raise SolarForecastError("detailed forecast must be a sequence of bins")

    bins: list[tuple[datetime, datetime, tuple[float, float, float]]] = []
    for index, item in enumerate(detailed_forecast):
        if not isinstance(item, Mapping):
            raise SolarForecastError(f"forecast bin {index} is not a mapping")
        start_utc = _parse_period_start(item.get("period_start"), index)
        end_utc = start_utc + SOURCE_BIN_DURATION
        if end_utc <= now_utc or start_utc >= deadline_utc:
            continue
        estimates = tuple(_read_nonnegative_finite(item, field, index) for field in _PV_FIELDS)
        p10, estimate, p90 = estimates
        if not p10 <= estimate <= p90:
            raise SolarForecastError(f"forecast bin {index} has disordered PV quantiles")
        bins.append((start_utc, end_utc, estimates))

    bins.sort(key=lambda row: row[0])
    if not bins:
        raise SolarForecastError("detailed forecast does not cover the requested horizon")
    cursor = now_utc
    intervals: list[SolarForecastInterval] = []
    for index, (bin_start, bin_end, estimates) in enumerate(bins):
        clipped_start = max(bin_start, now_utc)
        clipped_end = min(bin_end, deadline_utc)
        if clipped_start > cursor:
            raise SolarForecastError("detailed forecast has a coverage gap")
        if clipped_start < cursor:
            raise SolarForecastError("detailed forecast bins overlap")
        if clipped_end <= clipped_start:
            raise SolarForecastError(f"forecast bin {index} has no positive horizon overlap")

        sub_start = clipped_start
        while sub_start < clipped_end:
            sub_end = min(sub_start + MAX_INTERVAL_DURATION, clipped_end)
            intervals.append(
                SolarForecastInterval(
                    start=sub_start,
                    end=sub_end,
                    pv_estimate10_kw=estimates[0],
                    pv_estimate_kw=estimates[1],
                    pv_estimate90_kw=estimates[2],
                )
            )
            sub_start = sub_end
        cursor = clipped_end

    if cursor < deadline_utc:
        raise SolarForecastError("detailed forecast does not cover through deadline")
    return SolarForecast(
        source_updated_at=updated_utc,
        start=now_utc,
        deadline=deadline_utc,
        intervals=tuple(intervals),
    )


def _as_utc(value: datetime, label: str) -> datetime:
    """Require an aware datetime and normalize it to UTC."""

    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise SolarForecastError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _parse_period_start(value: Any, index: int) -> datetime:
    """Parse and validate a detailed forecast period start."""

    if isinstance(value, datetime):
        return _as_utc(value, f"forecast bin {index} period_start")
    if not isinstance(value, str):
        raise SolarForecastError(f"forecast bin {index} period_start must be an aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise SolarForecastError(f"forecast bin {index} period_start is invalid") from err
    return _as_utc(parsed, f"forecast bin {index} period_start")


def _read_nonnegative_finite(item: Mapping[str, Any], field: str, index: int) -> float:
    """Read one numeric, finite, non-negative forecast estimate."""

    value = item.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SolarForecastError(f"forecast bin {index} {field} must be numeric")
    estimate = float(value)
    if not isfinite(estimate) or estimate < 0:
        raise SolarForecastError(f"forecast bin {index} {field} must be finite and non-negative")
    return estimate
