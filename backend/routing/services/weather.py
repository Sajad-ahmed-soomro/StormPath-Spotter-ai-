"""Hourly forecasts from Open-Meteo: request specs and validated parsing.

The visitor's browser downloads the forecasts. Open-Meteo's free tier is
rate-limited per IP address, and hosting platforms share outbound IPs between
many customers, so server-side fetching exhausts a quota we don't control. The
backend still decides *what* to fetch (locations, window, variables, units)
through a request spec, and it validates and interprets what comes back.

Units requested match the risk rules directly: wind in mph, rain and snowfall
in inches. Open-Meteo reports precipitation as the amount accumulated over the
*preceding* hour, so the value stamped HH:00 is the rate for (HH-1:00, HH:00].
Instantaneous fields (wind, temperature) are linearly interpolated to the
exact ETA.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from django.conf import settings

HOURLY_VARS = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "rain",
    "showers",
    "snowfall",
    "temperature_2m",
    "weather_code",
)
BATCH_SIZE = 100  # locations per browser request; keeps URLs well under limits
COORD_DECIMALS = 2  # ~1 km; lets overlapping routes share forecasts


class InvalidWeatherData(ValueError):
    """Forecast data sent by the client doesn't match the request spec."""


@dataclass
class HourlySeries:
    """Hourly forecast for one location, starting at ``start`` (UTC, on the hour)."""

    start: datetime
    wind: np.ndarray
    gust: np.ndarray
    rain: np.ndarray  # rain + showers, in/hr
    snow: np.ndarray  # in/hr
    temp: np.ndarray  # °F
    code: np.ndarray  # WMO weather code

    def _hours(self, when: datetime) -> float:
        return (when - self.start).total_seconds() / 3600

    def _interp(self, values: np.ndarray, when: datetime) -> float:
        h = min(max(self._hours(when), 0.0), len(values) - 1)
        lo = int(math.floor(h))
        hi = min(lo + 1, len(values) - 1)
        return float(values[lo] + (values[hi] - values[lo]) * (h - lo))

    def _bucket(self, values: np.ndarray, when: datetime) -> float:
        # Accumulation stamped at the end of the hour that contains ``when``.
        idx = int(math.floor(self._hours(when))) + 1
        return float(values[min(max(idx, 0), len(values) - 1)])

    def at(self, when: datetime) -> dict:
        return {
            "wind_mph": round(self._interp(self.wind, when), 1),
            "gust_mph": round(self._interp(self.gust, when), 1),
            "rain_in_hr": round(self._bucket(self.rain, when), 3),
            "snow_in_hr": round(self._bucket(self.snow, when), 3),
            "temp_f": round(self._interp(self.temp, when), 1),
            "weather_code": int(self._bucket(self.code, when)),
        }

    def hourly(self, hour_start: datetime) -> dict:
        """Raw values for the hour beginning at ``hour_start`` (on the hour)."""
        idx = int(round(self._hours(hour_start)))
        cur = min(max(idx, 0), len(self.wind) - 1)
        nxt = min(max(idx + 1, 0), len(self.rain) - 1)
        return {
            "wind": float(self.wind[cur]),
            "rain": float(self.rain[nxt]),
            "snow": float(self.snow[nxt]),
        }


def floor_hour(when: datetime) -> datetime:
    return when.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


@dataclass
class WeatherRequest:
    """What to download: unique locations over an hourly window."""

    start: datetime
    hours: int
    locations: list[tuple[float, float]]
    point_index: list[int]  # for each requested point, its index in ``locations``

    def spec(self) -> dict:
        """Everything the browser needs to fetch exactly this data."""
        return {
            "url": settings.OPEN_METEO_URL,
            "batch_size": BATCH_SIZE,
            "locations": [list(p) for p in self.locations],
            "params": {
                "hourly": ",".join(HOURLY_VARS),
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "temperature_unit": "fahrenheit",
                "timezone": "GMT",
                "start_hour": self.start.strftime("%Y-%m-%dT%H:%M"),
                "end_hour": (self.start + timedelta(hours=self.hours - 1)).strftime("%Y-%m-%dT%H:%M"),
            },
        }


def build_request(points: list[tuple[float, float]], start: datetime, hours: int) -> WeatherRequest:
    """Round and de-duplicate points so shared stretches of road are fetched once."""
    start = floor_hour(start)
    rounded = [(round(lat, COORD_DECIMALS), round(lon, COORD_DECIMALS)) for lat, lon in points]
    unique = list(dict.fromkeys(rounded))
    position = {p: i for i, p in enumerate(unique)}
    return WeatherRequest(
        start=start,
        hours=max(int(hours), 2),
        locations=unique,
        point_index=[position[p] for p in rounded],
    )


def _array(hourly: dict, name: str, hours: int) -> np.ndarray:
    values = hourly.get(name)
    if not isinstance(values, list) or len(values) != hours:
        raise InvalidWeatherData(f"'{name}' must be a list of {hours} hourly values.")
    try:
        # Open-Meteo uses null for hours beyond a model's horizon.
        arr = np.array([0.0 if v is None else float(v) for v in values])
    except (TypeError, ValueError):
        raise InvalidWeatherData(f"'{name}' contains non-numeric values.") from None
    if not np.all(np.isfinite(arr)):
        raise InvalidWeatherData(f"'{name}' contains non-finite values.")
    return arr


def parse(request: WeatherRequest, hourly_by_location: list) -> list[HourlySeries]:
    """Validate the client's forecasts and return one series per requested point.

    ``hourly_by_location`` holds the ``hourly`` object Open-Meteo returned for
    each location in the spec, in the same order.
    """
    if not isinstance(hourly_by_location, list) or len(hourly_by_location) != len(request.locations):
        raise InvalidWeatherData(
            f"Expected forecasts for {len(request.locations)} locations."
        )
    series = []
    for hourly in hourly_by_location:
        if not isinstance(hourly, dict):
            raise InvalidWeatherData("Each forecast must be an object of hourly arrays.")
        arrays = {name: _array(hourly, name, request.hours) for name in HOURLY_VARS}
        series.append(
            HourlySeries(
                start=request.start,
                wind=arrays["wind_speed_10m"],
                gust=arrays["wind_gusts_10m"],
                rain=arrays["rain"] + arrays["showers"],
                snow=arrays["snowfall"],
                temp=arrays["temperature_2m"],
                code=arrays["weather_code"],
            )
        )
    return [series[i] for i in request.point_index]


WMO_DESCRIPTIONS = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Freezing fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Heavy freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Heavy showers",
    82: "Violent showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm, hail",
    99: "Severe thunderstorm, hail",
}


def describe(code: int) -> str:
    return WMO_DESCRIPTIONS.get(code, "Unknown")
