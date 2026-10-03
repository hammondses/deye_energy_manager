"""Tests for the empirical clear-sky DC potential curve."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from custom_components.deye_energy_manager.physical_solar import (
    PhysicalSolarSettings,
    clear_sky_curve,
    clear_sky_dc_potential_kw,
)


def settings(**overrides: float) -> PhysicalSolarSettings:
    values = {"latitude_deg": -43.5, "longitude_deg": 172.6}
    values.update(overrides)
    return PhysicalSolarSettings(**values)


def test_potential_matches_shadow_template_reference_sample() -> None:
    # Offline reference for the existing HA clear-sky equations at 16:00 NZDT
    # (2026-01-15 03:00 UTC), before the 18 kW model cap is reached.
    assert clear_sky_dc_potential_kw(
        datetime(2026, 1, 15, 3, tzinfo=timezone.utc), settings()
    ) == pytest.approx(16.434676, abs=1e-6)


def test_dc_cap_and_weather_scenario_multiplier_are_applied() -> None:
    at = datetime(2026, 1, 15, 0, tzinfo=timezone.utc)
    assert clear_sky_dc_potential_kw(at, settings()) == 18.0
    assert clear_sky_dc_potential_kw(at, settings(), weather_factor=0.5) == pytest.approx(9.753411)
    assert clear_sky_dc_potential_kw(at, settings(), weather_factor=1.1) == 18.0


def test_night_is_zero_and_curve_samples_five_minute_utc_intervals() -> None:
    settings_ = settings()
    night = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    assert clear_sky_dc_potential_kw(night, settings_) == 0.0

    start = datetime(2026, 1, 15, 0, tzinfo=timezone.utc)
    curve = clear_sky_curve(start, start + timedelta(minutes=30), settings_)
    assert len(curve) == 6
    assert [point.at for point in curve] == [
        start + timedelta(minutes=5 * index) for index in range(6)
    ]
    assert all(point.at.utcoffset() == timedelta(0) for point in curve)
    assert all(point.potential_dc_kw == 18.0 for point in curve)


def test_dst_representation_of_same_instant_has_same_solar_power() -> None:
    utc_time = datetime(2026, 9, 27, 1, tzinfo=timezone.utc)
    local_time = utc_time.astimezone(ZoneInfo("Pacific/Auckland"))
    assert clear_sky_dc_potential_kw(utc_time, settings()) == pytest.approx(
        clear_sky_dc_potential_kw(local_time, settings())
    )


@pytest.mark.parametrize(
    ("at", "expected_positive"),
    [
        (datetime(2026, 1, 15, 0, tzinfo=timezone.utc), True),
        (datetime(2026, 7, 15, 0, tzinfo=timezone.utc), True),
    ],
)
def test_southern_hemisphere_summer_and_winter_sun_are_modeled(
    at: datetime, expected_positive: bool
) -> None:
    power = clear_sky_dc_potential_kw(at, settings())
    assert (power > 0) is expected_positive


@pytest.mark.parametrize(
    ("at", "expected_positive"),
    [
        (datetime(2026, 6, 15, 12, tzinfo=timezone.utc), True),
        (datetime(2026, 12, 15, 12, tzinfo=timezone.utc), True),
    ],
)
def test_northern_hemisphere_sun_is_supported(
    at: datetime, expected_positive: bool
) -> None:
    # A north-facing panel at this latitude is intentionally used to ensure
    # the configured azimuth participates in the incidence calculation.
    power = clear_sky_dc_potential_kw(
        at, settings(latitude_deg=51.5, longitude_deg=0.0, panel_azimuth_deg=0.0)
    )
    assert (power > 0) is expected_positive


@pytest.mark.parametrize(
    "bad_settings",
    [
        {"latitude_deg": 91.0},
        {"longitude_deg": -181.0},
        {"panel_tilt_deg": 91.0},
        {"pv_capacity_kw": 0.0},
        {"system_loss_factor": 1.1},
        {"clear_sky_scale": float("nan")},
        {"pv_dc_cap_kw": float("inf")},
        {"step_minutes": 0},
    ],
)
def test_invalid_site_or_array_parameters_raise(bad_settings: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        clear_sky_dc_potential_kw(
            datetime(2026, 1, 15, tzinfo=timezone.utc), settings(**bad_settings)
        )


def test_naive_times_and_unbounded_weather_scenarios_raise() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        clear_sky_dc_potential_kw(datetime(2026, 1, 15), settings())
    with pytest.raises(ValueError, match="weather_factor"):
        clear_sky_dc_potential_kw(
            datetime(2026, 1, 15, tzinfo=timezone.utc), settings(), weather_factor=1.2
        )


def test_curve_rejects_reversed_times_and_empty_ranges_are_valid() -> None:
    start = datetime(2026, 1, 15, tzinfo=timezone.utc)
    assert clear_sky_curve(start, start, settings()) == ()
    with pytest.raises(ValueError, match="must not precede"):
        clear_sky_curve(start + timedelta(minutes=1), start, settings())
