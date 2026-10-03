"""Tests for strict Solcast detailed forecast parsing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from custom_components.deye_energy_manager.solar_forecast import (
    SolarForecastError,
    parse_detailed_forecast,
)

UTC = timezone.utc


def forecast_bin(start: str, p10: float = 0.8, estimate: float = 1.0, p90: float = 1.2) -> dict[str, object]:
    """Return one representative detailed forecast bin."""

    return {
        "period_start": start,
        "pv_estimate10": p10,
        "pv_estimate": estimate,
        "pv_estimate90": p90,
    }


def parse(bins: list[dict[str, object]], *, now: datetime, deadline: datetime, updated: datetime | None = None):
    """Parse bins with a fresh source timestamp by default."""

    return parse_detailed_forecast(
        bins,
        now=now,
        deadline=deadline,
        source_updated_at=updated or now,
        max_age=timedelta(minutes=30),
    )


def test_partial_bins_are_clipped_and_subdivided_without_changing_energy() -> None:
    now = datetime(2026, 10, 3, 10, 7, tzinfo=UTC)
    deadline = datetime(2026, 10, 3, 10, 42, tzinfo=UTC)
    result = parse(
        [
            forecast_bin("2026-10-03T10:00:00Z", 0.8, 1.0, 1.2),
            forecast_bin("2026-10-03T10:30:00+00:00", 1.6, 2.0, 2.4),
            # Starts at the deadline, so it cannot affect the requested horizon.
            {"period_start": "2026-10-03T11:00:00Z", "pv_estimate10": "bad"},
        ],
        now=now,
        deadline=deadline,
    )

    assert result.start == now
    assert result.deadline == deadline
    assert result.energy_kwh() == pytest.approx((23 / 60) + (2 * 12 / 60))
    assert result.energy_kwh("pv_estimate10") == pytest.approx((0.8 * 23 / 60) + (1.6 * 12 / 60))
    assert result.energy_kwh("pv_estimate90") == pytest.approx((1.2 * 23 / 60) + (2.4 * 12 / 60))
    assert result.intervals[0].start == now
    assert result.intervals[-1].end == deadline
    assert all(0 < (item.end - item.start).total_seconds() <= 300 for item in result.intervals)


def test_past_bins_are_trimmed_and_timezone_offsets_are_normalized() -> None:
    tz = ZoneInfo("Pacific/Auckland")
    now = datetime(2026, 10, 4, 22, 7, tzinfo=tz)
    deadline = datetime(2026, 10, 4, 22, 14, tzinfo=tz)
    result = parse(
        [
                forecast_bin("2026-10-04T21:30:00+13:00", 0.5, 0.8, 1.0),
                forecast_bin("2026-10-04T22:00:00+13:00", 1.0, 1.2, 1.5),
        ],
        now=now,
        deadline=deadline,
    )

    assert result.start.tzinfo is UTC
    assert result.source_updated_at.tzinfo is UTC
    assert result.energy_kwh() == pytest.approx(1.2 * 7 / 60)


def test_dst_spring_forward_uses_elapsed_seconds_not_wall_clock_labels() -> None:
    now = datetime.fromisoformat("2026-10-04T01:45:00+12:00")
    deadline = datetime.fromisoformat("2026-10-04T03:15:00+13:00")
    result = parse(
        [
            forecast_bin("2026-10-04T01:30:00+12:00", 0.8, 1.0, 1.2),
            forecast_bin("2026-10-04T03:00:00+13:00", 1.6, 2.0, 2.4),
        ],
        now=now,
        deadline=deadline,
    )

    assert result.start == now.astimezone(UTC)
    assert result.deadline == deadline.astimezone(UTC)
    assert sum(item.duration_hours for item in result.intervals) == pytest.approx(0.5)
    assert result.energy_kwh() == pytest.approx(0.25 + 0.5)
    assert result.intervals[0].start.isoformat() == "2026-10-03T13:45:00+00:00"
    assert result.intervals[-1].end.isoformat() == "2026-10-03T14:15:00+00:00"


@pytest.mark.parametrize(
    ("bins", "message"),
    [
        ([forecast_bin("2026-10-03T10:05:00Z")], "gap"),
        (
            [forecast_bin("2026-10-03T10:00:00Z"), forecast_bin("2026-10-03T10:25:00Z")],
            "overlap",
        ),
        ([forecast_bin("2026-10-03T10:00:00Z")], "does not cover through deadline"),
        ([], "does not cover"),
    ],
)
def test_missing_coverage_and_overlap_are_rejected(bins: list[dict[str, object]], message: str) -> None:
    with pytest.raises(SolarForecastError, match=message):
        parse(
            bins,
            now=datetime(2026, 10, 3, 10, 0, tzinfo=UTC),
            deadline=datetime(2026, 10, 3, 10, 55, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pv_estimate10", -0.1),
        ("pv_estimate", float("nan")),
        ("pv_estimate90", float("inf")),
        ("pv_estimate", "1.0"),
    ],
)
def test_invalid_power_values_are_rejected(field: str, value: object) -> None:
    item: dict[str, object] = forecast_bin("2026-10-03T10:00:00Z")
    item[field] = value
    with pytest.raises(SolarForecastError):
        parse(
            [item],
            now=datetime(2026, 10, 3, 10, 0, tzinfo=UTC),
            deadline=datetime(2026, 10, 3, 10, 20, tzinfo=UTC),
        )


def test_quantile_order_and_naive_period_start_are_rejected() -> None:
    now = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
    deadline = datetime(2026, 10, 3, 10, 20, tzinfo=UTC)
    with pytest.raises(SolarForecastError, match="disordered"):
        parse([forecast_bin("2026-10-03T10:00:00Z", 1.1, 1.0, 1.2)], now=now, deadline=deadline)
    with pytest.raises(SolarForecastError, match="timezone-aware"):
        parse([forecast_bin("2026-10-03T10:00:00")], now=now, deadline=deadline)


@pytest.mark.parametrize("label", ["now", "deadline", "source_updated_at"])
def test_naive_horizon_and_source_datetimes_are_rejected(label: str) -> None:
    now = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
    deadline = datetime(2026, 10, 3, 10, 20, tzinfo=UTC)
    updated = now
    if label == "now":
        now = now.replace(tzinfo=None)
    elif label == "deadline":
        deadline = deadline.replace(tzinfo=None)
    else:
        updated = updated.replace(tzinfo=None)
    with pytest.raises(SolarForecastError, match="timezone-aware"):
        parse_detailed_forecast(
            [forecast_bin("2026-10-03T10:00:00Z")],
            now=now,
            deadline=deadline,
            source_updated_at=updated,
            max_age=timedelta(minutes=30),
        )


def test_stale_future_source_and_invalid_deadline_are_rejected() -> None:
    now = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
    deadline = datetime(2026, 10, 3, 10, 20, tzinfo=UTC)
    bins = [forecast_bin("2026-10-03T10:00:00Z")]
    with pytest.raises(SolarForecastError, match="stale"):
        parse(bins, now=now, deadline=deadline, updated=now - timedelta(minutes=31))
    with pytest.raises(SolarForecastError, match="future"):
        parse(bins, now=now, deadline=deadline, updated=now + timedelta(seconds=1))
    with pytest.raises(SolarForecastError, match="after now"):
        parse(bins, now=now, deadline=now)
