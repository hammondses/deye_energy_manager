"""Empirical clear-sky PV potential used by the physical shadow planner.

This reproduces the Home Assistant shadow template's declination, air-mass,
DNI, plane-of-array, loss, scale, and DC-cap equations. It is a plausible
clear-sky scenario, not a guaranteed physical upper bound or a cloud forecast.
All power values are DC kW. No external astronomy dependency is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math


@dataclass(frozen=True, slots=True)
class PhysicalSolarSettings:
    """Site and array parameters for the empirical clear-sky curve."""

    latitude_deg: float
    longitude_deg: float
    panel_tilt_deg: float = 8.0
    panel_azimuth_deg: float = 2.0
    pv_capacity_kw: float = 16.56
    system_loss_factor: float = 0.96
    clear_sky_scale: float = 1.25
    pv_dc_cap_kw: float = 18.0
    step_minutes: int = 5


@dataclass(frozen=True, slots=True)
class PhysicalSolarPoint:
    """Potential DC power at a timestamp, before weather-scenario scaling."""

    at: datetime
    potential_dc_kw: float


def _finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _validate(settings: PhysicalSolarSettings) -> None:
    for name in (
        "latitude_deg", "longitude_deg", "panel_tilt_deg", "panel_azimuth_deg",
        "pv_capacity_kw", "system_loss_factor", "clear_sky_scale", "pv_dc_cap_kw",
    ):
        _finite(name, getattr(settings, name))
    if not -90 <= settings.latitude_deg <= 90:
        raise ValueError("latitude_deg must be between -90 and 90")
    if not -180 <= settings.longitude_deg <= 180:
        raise ValueError("longitude_deg must be between -180 and 180")
    if not -90 <= settings.panel_tilt_deg <= 90:
        raise ValueError("panel_tilt_deg must be between -90 and 90")
    if not -180 <= settings.panel_azimuth_deg <= 180:
        raise ValueError("panel_azimuth_deg must be between -180 and 180")
    if settings.pv_capacity_kw <= 0 or settings.pv_dc_cap_kw <= 0:
        raise ValueError("PV capacity and DC cap must be greater than zero")
    if not 0 < settings.system_loss_factor <= 1:
        raise ValueError("system_loss_factor must be in (0, 1]")
    if settings.clear_sky_scale <= 0:
        raise ValueError("clear_sky_scale must be greater than zero")
    if isinstance(settings.step_minutes, bool) or not isinstance(settings.step_minutes, int) or settings.step_minutes <= 0:
        raise ValueError("step_minutes must be a positive integer")


def _equation_of_time_minutes(day_of_year: int, local_hour: float) -> float:
    """NOAA approximation for apparent-solar-time correction."""

    gamma = 2 * math.pi / 365 * (day_of_year - 1 + (local_hour - 12) / 24)
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )


def clear_sky_dc_potential_kw(
    at: datetime,
    settings: PhysicalSolarSettings,
    *,
    weather_factor: float = 1.0,
) -> float:
    """Return the existing shadow model's potential DC kW at an aware time.

    ``weather_factor`` is an explicit scenario multiplier in [0, 1.1]. Values
    above one allow a modest cloud-enhancement scenario; they are not a
    probability, forecast quantile, or guaranteed bound. The configured DC cap
    is applied after scaling.
    """

    _validate(settings)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    _finite("weather_factor", weather_factor)
    if not 0 <= weather_factor <= 1.1:
        raise ValueError("weather_factor must be between 0 and 1.1")

    utc_at = at.astimezone(timezone.utc)
    day = utc_at.timetuple().tm_yday
    utc_hour = utc_at.hour + utc_at.minute / 60 + utc_at.second / 3600 + utc_at.microsecond / 3.6e9
    declination_deg = 23.45 * math.sin(math.radians(360 * (284 + day) / 365))
    equation_minutes = _equation_of_time_minutes(day, utc_hour)
    true_solar_minutes = (utc_hour * 60 + equation_minutes + 4 * settings.longitude_deg) % 1440
    hour_angle_deg = true_solar_minutes / 4 - 180

    latitude = math.radians(settings.latitude_deg)
    declination = math.radians(declination_deg)
    hour_angle = math.radians(hour_angle_deg)
    cos_zenith = (
        math.sin(latitude) * math.sin(declination)
        + math.cos(latitude) * math.cos(declination) * math.cos(hour_angle)
    )
    elevation_rad = math.asin(max(-1.0, min(1.0, cos_zenith)))
    elevation_deg = math.degrees(elevation_rad)
    if elevation_deg <= 0:
        return 0.0

    # Kasten-Young air mass and the same empirical clear-sky DNI curve as HA.
    sine_elevation = math.sin(elevation_rad)
    air_mass = 1 / (
        sine_elevation + 0.50572 * ((elevation_deg + 6.07995) ** -1.6364)
    )
    dni = 1353 * (0.7 ** (air_mass ** 0.678))

    # Plane-of-array incidence, using the configured azimuth clockwise from north.
    tilt = math.radians(settings.panel_tilt_deg)
    cosine_solar_elevation = max(0.0, math.cos(elevation_rad))
    solar_azimuth = math.atan2(
        -math.cos(declination) * math.sin(hour_angle),
        math.sin(declination) * math.cos(latitude)
        - math.cos(declination) * math.cos(hour_angle) * math.sin(latitude),
    )
    panel_azimuth = math.radians(settings.panel_azimuth_deg)
    cosine_incidence = (
        math.sin(elevation_rad) * math.cos(tilt)
        + cosine_solar_elevation * math.sin(tilt) * math.cos(solar_azimuth - panel_azimuth)
    )
    poa_w_m2 = dni * max(0.0, cosine_incidence) + 0.10 * dni * (1 + math.cos(tilt)) / 2
    potential_kw = (
        poa_w_m2 / 1000
        * settings.pv_capacity_kw
        * settings.system_loss_factor
        * settings.clear_sky_scale
        * weather_factor
    )
    return min(settings.pv_dc_cap_kw, max(0.0, potential_kw))


def clear_sky_curve(
    start: datetime,
    end: datetime,
    settings: PhysicalSolarSettings,
    *,
    weather_factor: float = 1.0,
) -> tuple[PhysicalSolarPoint, ...]:
    """Sample the clear-sky scenario every configured N minutes in [start,end)."""

    _validate(settings)
    if start.tzinfo is None or start.utcoffset() is None or end.tzinfo is None or end.utcoffset() is None:
        raise ValueError("start and end must be timezone-aware")
    if end < start:
        raise ValueError("end must not precede start")
    step = timedelta(minutes=settings.step_minutes)
    points: list[PhysicalSolarPoint] = []
    at = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    while at < end_utc:
        points.append(PhysicalSolarPoint(at, clear_sky_dc_potential_kw(
            at, settings, weather_factor=weather_factor
        )))
        at += step
    return tuple(points)
